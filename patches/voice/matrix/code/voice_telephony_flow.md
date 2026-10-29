# Voice Telephony Agent Flow Learning Guide (Vobiz/Plivo WS)

This guide explains **the complete telephony voice agent flow** implemented in `med_assist`, including:

- `@med_assist/router/voice.py` (`/voice/answer`)
- `@med_assist/router/voice_ws.py` (`/ws/.../voice/session/{session_id}`)
- Voice pipeline assembly and runtime in `med_assist/service/voice/pipeline.py`
- STT/TTS provider creation in `med_assist/service/voice/providers.py`
- VAD/turn detection configuration in `med_assist/config/voice.py`
- The LLM bridge processor `med_assist/service/voice/agent_processor.py`

This is written so you can confidently build the same “voice agent” experience for the web (WebRTC) using the same primitives.

---

## 0) Big picture in one minute

Telephony flow is:

1. Telephony provider (Vobiz/Plivo) hits **`POST /reloaded/med-assist/voice/answer?agent_id=...`** when a call is answered.
2. Server creates a **normal `med_assist` session** (`session_id`, `session_token`) and returns **XML** telling the provider to open a **bidirectional audio WebSocket**.
3. Provider connects to **`wss://.../reloaded/ws/med-assist/voice/session/{session_id}/?token=...`** and starts streaming audio frames.
4. Server validates token, builds the **Pipecat pipeline**:
   - WebSocket transport (mulaw 8kHz) → STT → VAD/turn aggregator → LLM agent processor → TTS → transport output
5. Server queues a greeting (“initial message”) once pipeline starts.
6. While call is active:
   - inbound audio is decoded/normalized by transport + serializer
   - STT yields transcript pieces
   - VAD aggregator decides user turns
   - LLM generates response streaming text
   - TTS converts text to audio and sends audio frames back to provider
7. On call end / idle timeout / max duration, pipeline stops and transcript is persisted to Dynamo.

---

## 1) Entry point: “Answer” endpoint (`med_assist/router/voice.py`)

### 1.1 Route: `vobiz_answer()` (`POST /answer`)

This endpoint exists **only** for telephony providers that need an XML response describing a WebSocket stream.

Key behavior:

- **Inputs**:
  - `agent_id` (query param). Note: the code treats it as a base64 blob which includes `wid`.
  - `From`, `To`, `CallUUID` form fields (telephony provider posts these).

- **Agent decoding**:
  - It does `base64.b64decode(agent_id).decode("utf-8")` and reads the `wid` via `split("#")[1]`.
  - Why: telephony doesn’t call your normal “validate_agent_request” header flow; so the answer endpoint reconstructs what it needs.

- **Agent config existence**:
  - `get_agent_config_from_db(agent_id)` ensures:
    - agent exists
    - agent is not archived (`arc`)
    - agent has `prompt_config` (required for LLM).

- **Phone normalization**:
  - `From` might come with `%2B` encoding and is normalized to `+<number>`.
  - Why: ensure user context has a consistent mobile format for downstream prompt injection / logging.

- **Session creation**:
  - Builds an `AgentRequest` manually with:
    - `client="vobiz"`
    - `device_id=CallUUID` (ties session to call UUID)
  - Builds `CreateSessionRequest`:
    - `user_context.mobile = From`
    - `session_context` includes channel/caller/callee/call_uuid
    - `referer="vobiz-telephony"` (important: `USER_CONTEXT_ALLOW_LIST` contains this)
  - Calls `create_session(req_agent, request_body)` which writes:
    - Dynamo session row
    - Redis session cache key `mat-{sid}` with token and expiry

- **WS URL synthesis**:
  - Uses `get_config()["HOST"]` and converts `http(s)` → `ws(s)`.
  - Special case: if domain includes `matrix.eka.care`, it rewrites host to `matrix-ws.eka.care`.
  - Produces:
    - `.../reloaded/ws/med-assist/voice/session/{session_id}/?token={token}`

- **Return XML**:
  - Returns `<Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000" ...>`
  - This line is **the telephony contract**:
    - audio encoding: **mulaw**
    - sample rate: **8000 Hz**
  - Why 8k mulaw: PSTN/telephony is typically 8kHz narrowband, and providers stream mulaw PCM for efficiency.

### 1.2 What this endpoint is NOT doing

- It does **not** run the voice pipeline itself.
- It does **not** open the WS; it only instructs provider where to connect.
- It does **not** store audio. Only transcripts are persisted later.

---

## 2) WebSocket endpoint: telephony audio stream (`med_assist/router/voice_ws.py`)

### 2.1 Route: `vobiz_voice_ws()` (`/session/{session_id}/?token=...`)

The provider connects here after it receives the `<Stream>` XML.

Key behavior:

- **Accept first**:
  - `await websocket.accept()` happens before validation.
  - Why: some provider protocols require accept to proceed with their handshake.

- **Token validation**:
  - `token` comes from query string.
  - `get_session_from_cache(session_id)` loads `SessionCache` from Redis.
  - It compares `session_cache.session_token != token` and closes if mismatch.
  - It checks expiry `session_cache.exp < now` and closes if expired.

- **Agent config + voice config**:
  - loads `agent_config = get_agent_config_from_db(session_cache.agent_id)`
  - requires:
    - `agent_config.prompt_config`
    - `agent_config.voice_config`
    - `voice_config.stt_config` and `voice_config.tts_config`

- **Pipeline run**:
  - `await run_voice_ws_pipeline(websocket, session_cache, agent_config, voice_config)`
  - This blocks until call ends or pipeline stops.

This WS endpoint is essentially:

- auth + config guardrail
- then “hand the socket to Pipecat transport and run the pipeline”.

---

## 3) Telephony pipeline assembly (`med_assist/service/voice/pipeline.py`)

There are two pipelines in this file:

- **WebRTC voice pipeline** (`run_voice_pipeline`) — for browser/SmallWebRTCTransport, typically 16kHz.
- **Telephony voice pipeline** (`run_voice_ws_pipeline`) — for Vobiz/Plivo over FastAPI WebSocket, mulaw 8kHz.

This document focuses on telephony, but you must understand both if you want to build web WebRTC “like telephony”.

---

## 4) Telephony pipeline: `run_voice_ws_pipeline()`

### 4.1 First message: provider “start” event

Telephony WS begins with a JSON “start” message.

Code:

- `first_msg = await websocket.receive_text()`
- `start_data = orjson.loads(first_msg).get("start", {})`
- extracts:
  - `stream_id = start_data.get("streamId", "")`
  - `call_id = start_data.get("callId")`

Why this exists:

- Vobiz/Plivo serializer needs stream/call IDs to format outgoing frames correctly.
- If you skip this, you may send malformed frames and provider will drop audio.

### 4.2 Serializer: `PlivoFrameSerializer`

Then:

- `serializer = PlivoFrameSerializer(...)`
  - includes `auth_id` and `auth_token` from env vars:
    - `VOBIZ_AUTH_ID`
    - `VOBIZ_AUTH_TOKEN`

What serializer does (conceptually):

- **Deserializes inbound frames** from provider protocol into Pipecat audio frames.
- **Serializes outbound frames** from Pipecat into provider protocol JSON messages.

This is where “audio chunk format” gets interpreted for telephony.

### 4.3 Transport: `FastAPIWebsocketTransport`

Transport created with:

- `audio_in_sample_rate=8000`
- `audio_out_sample_rate=8000`
- `serializer=serializer`

What transport does (conceptually):

- Reads WS frames → uses serializer to decode provider messages → yields audio frames into the pipeline.
- Accepts audio frames from later pipeline stages (TTS) → uses serializer to encode provider messages → sends on WS.

Where you handle “audio chunk serialization/deserialization”:

- **Telephony**: almost entirely inside `PlivoFrameSerializer` + `FastAPIWebsocketTransport`.
- Your application code generally never manipulates raw mulaw bytes directly.

### 4.4 Why telephony is explicitly 8kHz and mulaw

Telephony providers commonly stream:

- **Encoding**: \( \mu \)-law (mulaw) companded PCM, a standard PSTN representation.
- **Sample rate**: **8000 Hz**, narrowband.

The code enforces 8kHz in:

- XML contract in `voice.py` (`contentType="audio/x-mulaw;rate=8000"`)
- pipeline transport parameters (`audio_in_sample_rate=8000`, `audio_out_sample_rate=8000`)
- STT creation (`create_stt_service(..., sample_rate=8000)`)
- pipeline task params (`PipelineParams(..., audio_in_sample_rate=8000)`)

The reason to “enforce everywhere” is to avoid silent resampling mismatches, STT garbage transcription, or TTS output being interpreted at wrong speed/pitch.

---

## 5) VAD / turn detection: why it exists and how it is tuned for telephony

### 5.1 What VAD does here

VAD = Voice Activity Detection. In this system it is used for **turn management**, not just “detect speech”.

The user aggregator uses:

- `SileroVADAnalyzer(params=VADParams(...))`

and decides when a user turn:

- **starts** (speech begins)
- **ends** (speech stops for long enough)

Once a user turn ends, the aggregator emits an `LLMContextFrame` containing the user’s latest text, which is what triggers the LLM agent processor.

### 5.2 Telephony VAD defaults (`med_assist/config/voice.py`)

There are two configs:

- `VADConfig`: WebRTC defaults (16kHz)
- `TelephonyVADConfig`: Telephony defaults (8kHz mulaw)

Telephony config is stricter because 8kHz has less information and more noise:

- higher `vad_confidence`
- longer `vad_start_secs` and `vad_stop_secs`
- higher `vad_min_volume`
- longer `user_turn_stop_timeout`

The file documents the reasoning explicitly:

- 8kHz Silero VAD uses fewer samples/frame, reducing accuracy
- phone lines have hum/line noise/background speakers
- caller is closer to mic than background speakers → leverage min_volume
- disable transcription-start strategies that might trigger turns from background transcriptions

### 5.3 The “turn start strategy” difference for telephony

In `run_voice_ws_pipeline`, the user aggregator sets:

- `user_turn_strategies=UserTurnStrategies(start=[VADUserTurnStartStrategy()])`

This ensures turns start based on VAD detection only.

The pipeline comment highlights an important reason:

- If you allow “transcription-based turn start” at 8kHz telephony, background speech can create spurious user turns (causing the agent to talk over the caller).

---

## 6) STT: how audio becomes text (`med_assist/service/voice/providers.py`)

### 6.1 Factory entry: `create_stt_service(voice_config, sample_rate=...)`

This returns a Pipecat `FrameProcessor` that converts audio frames into transcription frames.

Key idea:

- The pipeline never calls an STT SDK directly.
- It constructs a service based on the agent’s `voice_config.stt_config` type.

Branches:

- **Deepgram** (`DeepgramSTTService`)
  - uses `LiveOptions(...)` with interim results enabled.
  - `sample_rate` is passed in and must match transport audio sample rate.
- **Sarvam** (`SarvamSTTService`)
  - special-case: if model is `saaras:v2.5` language auto-detects; else language map is applied.
- **ElevenLabs** (`ElevenLabsRealtimeSTTService`)
  - uses params:
    - language_code (or auto)
    - include_language_detection enabled by default (see config constants)

Why sample rate is passed into STT:

- Real-time STT expects correct sample rate metadata to decode waveform duration and spectral features.
- Wrong sample rate often produces:
  - empty transcript
  - hallucinated words
  - timing drift, broken VAD/turn segmentation

---

## 7) TTS: how text becomes audio (`med_assist/service/voice/providers.py`)

### 7.1 Factory entry: `create_tts_service(voice_config)`

Branches:

- **Deepgram** (`DeepgramTTSService`)
- **Sarvam** (`SarvamTTSService`) but wrapped via `InterruptableSarvamTTSService`
- **ElevenLabs** (`ElevenLabsTTSService`) with tuned constants for stability/similarity/style/speed

### 7.2 Why `InterruptableSarvamTTSService` exists

It fixes interruption behavior:

- Pipecat’s “interruptible” base behavior only disconnects streaming audio if it thinks bot is already speaking.
- In practice, interruption may occur before `BotStartedSpeakingFrame` propagates.
- Result: old audio keeps streaming even after user interrupts.

This subclass forces a disconnect/reconnect even if `_bot_speaking` is false, ensuring in-flight audio is killed.

Why this matters for WebRTC too:

- In “full duplex” voice UX, interruption is non-negotiable.
- If your web flow supports barge-in, you need the same guarantee that TTS output can be stopped promptly.

---

## 8) Agent construction for voice: `_build_agent()` in `pipeline.py`

This is intentionally “parallel” to the chat agent wiring, but with voice-specific guardrails.

### 8.1 Prompt config

- `echo_config = await get_echo_agent_config(agent_config.prompt_config)`

### 8.2 User context injection (mobile)

- fetches user context via `get_user_context_by_id(session_cache.userid)`
- appends:
  - `<USER_CONTEXT>{"mobile":"..."}</USER_CONTEXT>`

Why:

- telephony identity is the phone number; voice system needs to consistently supply it without user speaking it.
- prompt rules explicitly say “take phone number from USER_CONTEXT, never from user”.

### 8.3 Voice guardrails appended to prompt

The code appends constraints such as:

- “You are in a voice conversation”
- plain spoken language, short sentences
- no markdown formatting
- one question at a time
- language mirroring

Why:

- TTS reads literally; markdown and structured formatting sound unnatural and can leak system structure.
- voice latency and interruptions are worse when responses are long.

### 8.4 Tools list

For voice `_build_agent()`:

- tools start empty (it explicitly says “no common elicitation tools for voice”)
- then adds:
  - MCP tools (with tool_context)
  - KB tools
  - custom tools

Why “no elicitation tools”:

- Voice UX cannot easily render multi-select pills/cards.
- Elicitation requires UI affordances not present in a phone call.

---

## 9) The LLM bridge: `EchoAgentProcessor` (`med_assist/service/voice/agent_processor.py`)

This is the key piece that makes voice work without reusing the chat Redis-stream machinery.

### 9.1 What frames it cares about

It is a Pipecat `FrameProcessor`.

- For any frame that is **not** `LLMContextFrame`, it passes through unchanged.
- For `LLMContextFrame`, it extracts the last user message and runs the LLM.

### 9.2 How it extracts user text

It inspects the context aggregator’s messages:

- finds last message with `role == "user"`
- if `content` is list, it joins all `type=="text"` parts.

Why this implementation exists:

- Different Pipecat context formats can represent content as list-of-items (to support multi-modal).
- Voice wants plain text.

### 9.3 In-memory conversation state (no Redis)

It maintains:

- `self._conversation_history: list[Message]`

and appends:

- user messages as `MessageRole.USER`
- assistant final responses as `MessageRole.ASSISTANT`

Why it’s in-memory:

- A phone call is a short-lived realtime session.
- Keeping voice turns in Redis streams adds latency and complexity.
- Transcript persistence is done once at the end (to Dynamo) for durability.

### 9.4 LLM streaming → sentence buffering → TTS

Core behavior:

- calls `self._agent.run_stream(context, out_msg_id)`
- on each `StreamEventType.TEXT` chunk:
  - append to `text_buffer`
  - when it sees sentence boundary (`[.!?\n]`), flush that sentence as an `LLMTextFrame`

Why sentence buffering exists:

- TTS services perform better on coherent sentence-like segments.
- Streaming every token causes robotic cadence and too many TTS API calls.
- Not flushing until DONE increases latency; buffering by sentence is a balance.

### 9.5 Start/end frames

It pushes:

- `LLMFullResponseStartFrame()` before starting agent stream
- `LLMFullResponseEndFrame()` in `finally` block always

Why:

- downstream processors (TTS/transport/aggregators) may depend on these delimiters for consistent state.

### 9.6 Interruptions / cancellation

On `asyncio.CancelledError`:

- logs interruption
- persists partial `full_response` to history
- re-raises cancellation so Pipecat can stop the turn.

Important for UX:

- If caller interrupts, you want to stop TTS quickly but still keep partial history for transcript/debugging.

---

## 10) Pipeline orchestration: `Pipeline`, `PipelineTask`, events, timeouts

### 10.1 Pipeline chain for telephony

In `run_voice_ws_pipeline()`:

- `transport.input()`
- `stt`
- `user_aggregator`
- `agent_processor`
- `tts`
- `transport.output()`
- `assistant_aggregator`

Think of it as a conveyor belt:

- audio in → transcript → user turn → LLM text → speech audio out

### 10.2 Task params

`PipelineTask(..., params=PipelineParams(allow_interruptions=True, audio_in_sample_rate=8000), idle_timeout_secs=60, cancel_on_idle_timeout=False)`

- `allow_interruptions=True`: enables “barge-in” semantics; upstream can cancel downstream.
- `audio_in_sample_rate=8000`: reinforces telephony contract for internal timing.
- `idle_timeout_secs=60`: if no activity for 60s, it triggers the idle handler.
- `cancel_on_idle_timeout=False`: instead of hard cancel, it queues a goodbye message and stops gracefully.

### 10.3 Greeting injection

On `on_pipeline_started` event:

- adds assistant greeting to conversation history
- queues `TTSSpeakFrame(text=greeting)`

Why:

- You want the assistant to speak first in a phone call.
- This ensures TTS starts only when the whole pipeline is ready (transport + STT + TTS initialized).

### 10.4 Disconnect handler

Transport event `on_client_disconnected` cancels the task.

Why:

- provider disconnect means call ended; cleanly stop processing.

### 10.5 Idle timeout handler

On idle timeout:

- queue goodbye message
- `stop_when_done()`

Why:

- avoid silent hanging calls and compute burn
- provide polite closure to user

### 10.6 Max call duration

The runner is wrapped in `asyncio.wait_for(..., timeout=600)`.

On timeout:

- queue a maximum duration message
- sleep 3 seconds to let audio play
- cancel task

Why:

- enforce cost/safety constraints
- prevent stuck calls

---

## 11) Transcript persistence (`_persist_transcript()` in `pipeline.py`)

On pipeline shutdown (finally block), it writes transcript to Dynamo.

Key behavior:

- Converts each in-memory `Message` into a `SessionFlow` row.
- Uses `ev=IncomingEventType.VOICE`.
- Writes to `DYNAMO_SESSION_FLOW_TABLE` (`med-assist-session-flow`).

What is persisted:

- role (USER/ASSISTANT)
- content (text items)
- timestamps
- usage metrics if present

What is NOT persisted:

- raw audio bytes/chunks

Why audio is not persisted:

- privacy and cost
- large payload volume
- easier compliance boundary (store text only)

---

## 12) Audio serialization/deserialization: where it actually happens

You asked specifically about “serialization or deserialization of audio and chunks”.

In this codebase:

- Telephony audio handling is delegated to **Pipecat transport + Plivo serializer**.
- Your code configures:
  - sample rate in transport
  - serializer instance constructed with stream_id/call_id/auth

So the right mental model is:

- **Your business code** deals with *turns and text*.
- **Pipecat transport+serializer** deals with *wire protocol and audio bytes*.

This is also why:

- there is no custom “audio chunk parser” in `med_assist` for telephony.

---

## 13) Why RNNoise is disabled for telephony

In `run_voice_ws_pipeline()` there is an explicit comment:

- RNNoise requires 48kHz internally
- 8k → 48k → 8k resampling degrades quality
- certain resampler quality settings cause artifacts at 8k
- for telephony noise, rely on carrier/provider suppression

This is a key engineering constraint:

- do not “blindly reuse” WebRTC noise filtering for telephony.

---

## 14) WebRTC vs Telephony: what is the same and what changes

### 14.1 Same building blocks

- STT factory (`create_stt_service`)
- TTS factory (`create_tts_service`)
- VAD aggregator (`SileroVADAnalyzer`)
- LLM processor (`EchoAgentProcessor`)
- Pipeline assembly order
- Greeting injection
- Idle timeout, max duration logic
- Transcript persistence pattern

### 14.2 What changes

- **Transport**:
  - Telephony: `FastAPIWebsocketTransport` + `PlivoFrameSerializer`
  - Web: `SmallWebRTCTransport` + `SmallWebRTCConnection`
- **Audio sample rate**:
  - Telephony: 8kHz mulaw (provider contract)
  - WebRTC: typically 16kHz PCM (configured by `VADConfig.audio_sample_rate`)
- **VAD tuning**:
  - Telephony uses `TelephonyVADConfig` stricter thresholds
  - WebRTC uses `VADConfig` more permissive thresholds and can optionally enable RNNoise

---

## 15) How to build WebRTC “like telephony” (practical mapping)

If your goal is: “build the voice agent flow for web using WebRTC the same as telephony”, the recipe is:

- Reuse the WebRTC path already implemented in `voice.py`:
  - `/offer` + `SmallWebRTCConnection` + `SmallWebRTCTransport`
  - `run_voice_pipeline(...)` calls `_run_voice_pipeline_inner(...)`
- Ensure your web UI sends:
  - `session_id` and `token` in `request_data` inside `/offer` payload (that is what server expects)
- Match telephony behavior by aligning:
  - greeting handling (`on_pipeline_started`)
  - interruption settings (`allow_interruptions=True`)
  - max duration + idle timeout behavior
  - transcript persistence behavior (already shared)

Where you should *not* copy telephony literally:

- do not use Plivo serializer for WebRTC
- do not force 8kHz on WebRTC unless you have a reason (it reduces quality and can hurt STT)

---

## 16) Required environment/config checklist for telephony

To make telephony work reliably:

- **`MATRIX` config includes**:
  - `HOST` (public URL) used to build WS URL in `/answer`
  - `VOICE_TELEPHONY_SECRET` (optional): when set, `/answer` requires `&key=<secret>` on the answer URL
    configured in Vobiz (403 otherwise) and puts a signed, 10-minute `?token=` on the WebSocket URL, which
    the WebSocket checks (close code 4001 if bad). When unset, both are open as before and a warning is
    logged on every call. See `med_assist/service/voice/telephony_auth.py`. Update the Vobiz answer URL
    *before* setting the secret.
- **Numbers registered in the console** (channel `telephony`, provider `vobiz`) use
  `POST /reloaded/med-assist/voice/answer/{integration_uuid}` as the Vobiz answer URL (the console shows it on
  the number's page). The agent is whichever agent the number is bound to (`integrations` +
  `product_integrations`, read by `med_assist/service/voice/telephony_binding.py`); an unknown, unbound,
  paused or foreign number gets a 404. No `key` is needed: the uuid is the access control. The caller ID
  (`From`) is given to the agent as an unverified hint (`caller_context.py`) and is not sent to tool servers
  as the user's identity.
- **Handover to a person** (agent tool `transfer_to_human`, phone calls on a registered number only): the
  number's binding config carries `handover` (staff number, optional hours, ring seconds), set in the console.
  When the agent calls the tool inside staff hours, matrix lets it finish saying it is connecting the caller,
  then calls Vobiz's Transfer API (`POST {VOBIZ_API_BASE_URL}/Account/{auth_id}/Call/{call_uuid}/`, default
  base `https://api.vobiz.ai/api/v1`) pointing the caller's leg at `POST /voice/transfer/{session_id}`, which
  returns a `<Dial>` to the staff phone (caller ID = the dialled Vobiz number). When the Dial ends Vobiz posts
  to `/voice/transfer-result/{session_id}`: `completed` hangs up, anything else plays a short English
  apology. Both URLs carry a signed 10-minute token; the feature is off unless `VOICE_TELEPHONY_SECRET`,
  `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` and `HOST` are set. See `med_assist/service/voice/handover*.py`.
- **Call record** (`med_assist/service/voice/call_record.py`): phone sessions use channel `voice`. When the call
  connects, `mark_conversation_initiated` writes the session row to DynamoDB (without it the console's
  Conversations page never sees the call). When it ends, the facts only the pipeline knows are merged into
  the session's `initial_context` under `call`: duration, how it ended (`caller_hung_up`, `silence`,
  `time_limit`, `transferred`, `error`), caller turns, handover outcome, tools used, and the caller's number
  masked. The full caller number stays in `initial_context.caller`, as saved by `/answer`.
- **Env vars**:
  - `VOBIZ_AUTH_ID`
  - `VOBIZ_AUTH_TOKEN`
  - STT/TTS provider API keys if not present in agent config (provider code reads env as fallback)

Agent config must have:

- `prompt_config`
- `voice_config` with:
  - `stt_provider`, `stt_config`
  - `tts_provider`, `tts_config`

---

## 17) Failure modes and what they mean

### 17.1 Provider connects but no audio

Common causes:

- missing/incorrect `PlivoFrameSerializer` IDs (streamId/callId parse failed)
- wrong content type / sample rate mismatch between provider and transport
- provider didn’t send expected “start” message (or server didn’t parse it)

### 17.2 STT works but agent doesn’t respond

Common causes:

- VAD thresholds too strict (no “turn end” event)
- aggregator never produces `LLMContextFrame`
- agent prompt config missing or invalid

### 17.3 Agent responds but user can’t interrupt

Common causes:

- `allow_interruptions` disabled
- TTS provider doesn’t stop streaming; Sarvam fix exists for this reason

### 17.4 Call ends but no transcript saved

Common causes:

- pipeline crashes before `finally` runs (rare)
- Dynamo permissions / table name mismatch

---

## 18) Read order (telephony mastery)

1. `med_assist/router/voice.py` (`vobiz_answer`)
2. `med_assist/router/voice_ws.py` (`vobiz_voice_ws`)
3. `med_assist/service/voice/pipeline.py` (`run_voice_ws_pipeline`, `_persist_transcript`)
4. `med_assist/config/voice.py` (`TelephonyVADConfig` + constants)
5. `med_assist/service/voice/providers.py` (STT/TTS factories + Sarvam interruption fix)
6. `med_assist/service/voice/agent_processor.py` (LLM streaming + sentence buffering)

If you understand those six, you can safely implement the web WebRTC voice path with the same semantics.

---

## 19) Line-by-line annotated walkthrough (do not skip)

This section is the “source-of-truth” mapping from code → behavior.

### 19.1 `med_assist/router/voice.py` (telephony `POST /answer`, plus WebRTC `/offer`)

#### File purpose

- **L1–L6**: module docstring clarifies this router owns voice endpoints (WebRTC signaling and telephony answer).
- **L8–L27**: imports.
  - `get_config()` (L18) is used to build public WS URL.
  - `create_session()` (L24) is reused from chat to create session/token for calls.
  - `run_voice_pipeline()` (L25) is used for browser WebRTC voice.

#### Shared router setup

- **L29–L35**: `router = APIRouter()` and `_pcs_map` for tracking active WebRTC peer connections by `pc_id`.
  - **Why**: WebRTC renegotiation/connection reuse requires keeping a server-side handle.
  - **Telephony does not use `_pcs_map`**.

#### WebRTC signaling endpoint (useful for your “web voice agent” goal)

- **L36–L191**: `webrtc_offer()`.
  - **L46–L52**: imports `SmallWebRTCConnection` and constructs STUN config.
  - **L55–L64**: extracts `session_id` and `token` from `request["request_data"]`.
    - **Why**: for WebRTC, auth is carried out-of-band with SDP offer; it is not part of WS query string.
  - **L66–L75**: loads session from Redis and validates session token + expiry.
    - **Why**: prevents anonymous callers from opening WebRTC voice without a valid session.
  - **L77–119**: loads agent config and validates `prompt_config`, `voice_config`, `stt_config`, `tts_config`.
    - **Why**: pipeline can’t run without prompt and provider keys.
  - **L121–163**: reuse/initialize peer connection, set `closed` handler to evict from `_pcs_map`.
  - **L155–162**: runs `run_voice_pipeline(...)` in background.
    - **Why**: signaling endpoint must return quickly with SDP answer; pipeline is long-running.
  - **L164–174**: returns SDP answer (includes `pc_id`).

#### Telephony “answer” endpoint (call bootstrap)

- **L194–319**: `vobiz_answer(...)`.
  - **L196–201**: parameters:
    - `agent_id` as query param
    - `From`, `To`, `CallUUID` from form body
  - **L213–223**: validates `agent_id` present and base64-decodes it.
    - **Why**: for telephony, they pass `agent_id` differently than normal HTTP chat flow.
  - **L224**: extracts `wid` from decoded agent token `split("#")[1]`.
    - **Why**: session creation requires workspace id.
  - **L225–229**: loads agent config and requires `prompt_config`.
    - **Why**: call must run an LLM; no prompt config means no agent.
  - **L231–236**: normalizes caller number into `+...` E.164-like form.
    - **Why**: consistent mobile formatting for user context and prompt guardrails.
  - **L238–243**: builds `AgentRequest` manually (client=`"vobiz"`, device_id=`CallUUID`).
    - **Why**: there is no `validate_agent_request()` for provider callbacks; we construct what we need.
  - **L245–263**: builds `CreateSessionRequest`:
    - `user_context.mobile = From` (L246–255)
    - `session_context` includes channel/caller/callee/call_uuid (L256–261)
    - `referer="vobiz-telephony"` (L262) — must match allow-list logic in session creation.
  - **L265–268**: calls `create_session()` and extracts `session_id` + `token`.
  - **L269–282**: builds provider WS URL:
    - **L270** reads `HOST` from `MATRIX` config.
    - **L275–277** converts http(s)→ws(s) and rewrites domain for `matrix-ws.eka.care`.
    - **L279–282** constructs `/reloaded/ws/med-assist/voice/session/{sid}/?token=...`
  - **L284–295**: constructs and returns XML `<Stream ...>`.
    - **Important**: in current code this is **`audio/x-l16;rate=16000`** (L288).
    - **Why**: Vobiz is sending higher-quality raw PCM (L16) for inbound audio to improve STT.
  - **L328–351**: long docstring includes older example showing mulaw/8k; treat that as historical.

### 19.2 `med_assist/router/voice_ws.py` (telephony WS endpoint)

#### File purpose

- **L1–L6**: describes telephony voice WS endpoint.
- **L21–107**: `vobiz_voice_ws(websocket, session_id, token="")`.

#### Step-by-step

- **L32–34**: accepts WS immediately.
  - **Why**: provider expects accept handshake before it starts streaming frames.
- **L36–43**: ensures token is present; closes `4001` if missing.
- **L45–47**: loads session cache from Redis (`get_session_from_cache`).
- **L49–56**: token match check; closes `4001` if mismatch.
- **L57–63**: expiry check; closes `4001` if expired.
- **L65–74**: loads agent config; requires `prompt_config`; closes `4002` if missing.
- **L76–95**: requires `voice_config`, `stt_config`, `tts_config`; closes `4003` if missing.
- **L104–108**: runs `run_voice_ws_pipeline(...)` until call ends.
  - **Why**: for telephony, the WS handler itself becomes the “call runtime”.

### 19.3 `med_assist/service/voice/pipeline.py` (pipeline factory + transcript persistence)

#### File purpose and key invariants

- **L1–L8**: defines the canonical pipeline chain.
- **Important runtime rule**: pipeline is the only place where STT/VAD/LLM/TTS are wired together.

#### Agent builder: `_build_agent()`

- **L74–145**: builds `GenericAgent` for voice.
  - **L79**: loads Echo prompt config from prompt provider (`get_echo_agent_config`).
  - **L82–90**: fetches user context and injects `<USER_CONTEXT>{"mobile":...}</USER_CONTEXT>`.
    - **Why**: the voice prompt rules rely on phone number being provided via context, not user speech.
  - **L92–113**: appends voice-specific guardrails (“no markdown”, short sentences, one question at a time).
    - **Why**: TTS reads literally; markdown or long text degrades UX.
  - **L115–137**: tool wiring for voice:
    - starts with `tools = []` (no UI elicitation tool)
    - optionally adds MCP/KB/custom tools
  - **L138–144**: uses agent’s `primary_llm_config` if provided.

#### Telephony pipeline entry: `run_voice_ws_pipeline()`

- **L314–511**: telephony pipeline.

**(A) Provider start message parse**

- **L329–344**: reads first WS text message and parses `start.streamId` and `start.callId`.
  - **Why**: serializer needs these identifiers to format outbound frames and track the stream.

**(B) Serializer choice (THIS is where audio deserialization happens)**

- **L345–351**: constructs `VobizL16FrameSerializer(...)` using env `VOBIZ_AUTH_ID/TOKEN`.
  - **Why**: Vobiz inbound audio is L16/16k (high quality for STT), but outbound may still be constrained by telephony.

**(C) Transport**

- **L359–366**: creates `FastAPIWebsocketTransport` with serializer.
  - **Why**: transport converts WS frames ↔ Pipecat frames using serializer (your business code does not parse base64 audio).

**(D) STT + TTS services**

- **L368–370**: `stt = create_stt_service(...)`, `tts = create_tts_service(...)`.
  - **Why**: provider selection is per-agent config; pipeline stays stable.

**(E) LLM processor**

- **L375–383**: builds agent and wraps into `EchoAgentProcessor(agent, session_id=...)`.
  - **Why**: bridges Pipecat “turn frame” world to Echo `GenericAgent.run_stream()` world.

**(F) VAD + turn strategies**

- **L386–408**: constructs user/assistant aggregators.
  - `TelephonyVADConfig()` (L386) supplies thresholds.
  - `SileroVADAnalyzer(VADParams(...))` controls start/stop of speech.
  - `UserTurnStrategies`:
    - `start=[VADUserTurnStartStrategy()]` (L399–401)
      - **Why**: telephony echo/sidetone can create transcripts from the bot itself; do not let STT trigger start-of-turn.
    - `stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=...)]` (L401–405)
      - **Why**: closes the turn even if final transcript arrives late or never arrives.

**(G) Pipeline assembly**

- **L410–421**: assembles processors in order:
  - transport.input → stt → user_aggregator → agent_processor → tts → transport.output → assistant_aggregator

**(H) Task + runtime policy**

- **L424–434**: creates `PipelineTask`:
  - `allow_interruptions=True`: permits barge-in (caller can interrupt bot).
  - `audio_out_sample_rate=16000` (L428): this is the internal desired output rate for TTS frames.
  - metrics flags tie to `VOICE_PROFILING_ENABLED`.
  - idle timeout uses module constant `IDLE_TIMEOUT_SECS` (L65 = 10s in this file).

**(I) Greeting**

- **L436–460**: on pipeline start, queues `TTSSpeakFrame(text=greeting)` and appends assistant greeting to history.
  - **Why**: voice assistants should start with a greeting once pipeline is fully ready.

**(J) Shutdown and transcript persistence**

- **L484–494**: runner is bounded by `MAX_CALL_DURATION_SECS` and persists transcript in `finally`.
- **L513–561**: `_persist_transcript()` writes each in-memory voice `Message` into Dynamo as `SessionFlow` with `ev=IncomingEventType.VOICE`.
  - **Why**: persist textual transcript for auditing/debugging without storing raw audio.

#### IMPORTANT NOTE about telephony sample rate in this repo

There is a mix of “telephony is 8k mulaw” documentation and “Vobiz is 16k L16” implementation.

- The live telephony WS path currently uses:
  - **Inbound**: L16/16k (XML + serializer override)
  - **Outbound**: parent `PlivoFrameSerializer` behavior (see serializer file below)

When implementing WebRTC voice, follow the **actual code paths**, not the older comments.

### 19.4 `med_assist/service/voice/vobiz_serializer.py` (the actual audio deserialize/serialize boundary)

This file is the most important one for “audio chunk serialization/deserialization”.

- **L1–L9**: docstring states:
  - Input deserialize: raw L16/16kHz PCM from Vobiz
  - Output serialize: mulaw/8kHz via parent `PlivoFrameSerializer`
  - Used when XML contentType is `audio/x-l16;rate=16000`
- **L23–26**: declares `VOBIZ_INPUT_SAMPLE_RATE = 16000`.
- **L28–43**: `VobizL16FrameSerializer` extends `PlivoFrameSerializer`.
  - Does not override `serialize` → outbound stays parent behavior.
- **L44–76**: `deserialize(self, data)`:
  - **L46–49**: parse JSON; if invalid, drop message.
  - **L51–56**: only handles `event == "media"` with base64 payload.
  - **L58**: base64-decodes audio bytes.
  - **L60–63**: resamples payload from 16k to `self._sample_rate` using `self._input_resampler`.
    - **Why**: pipeline and STT must agree on a sample rate; resampling ensures consistent internal rate even if provider differs.
  - **L67–71**: returns `InputAudioRawFrame(audio=..., num_channels=1, sample_rate=self._sample_rate)`.
    - **Why**: Pipecat pipeline operates on typed frames, not raw websocket strings.
  - **L73–75**: delegates `dtmf` to parent.

### 19.5 `med_assist/service/voice/providers.py` (STT/TTS factories)

This file chooses which Pipecat provider service to instantiate based on agent config.

#### STT: `create_stt_service()`

- **L37–71**:
  - **L41–68**: supports `ElevenLabsRealtimeSTTService`.
  - **L48–55**: api key from config or env, commit strategy MANUAL.
    - **Why**: manual commit prevents partial interim results from prematurely closing turns in noisy telephony.
  - **L49**: passes `sample_rate` into STT.
    - **Why**: STT model depends on correct sample rate.
  - **L56–62**: sets model + optional language.

#### TTS: `create_tts_service()`

- **L74–105**:
  - **L78–103**: supports `ElevenLabsTTSService`.
  - **L86–87**: `TextAggregationMode.SENTENCE`.
    - **Why**: TTS service buffers text into sentence-like chunks for natural prosody.
    - **Consequence**: your `EchoAgentProcessor` can stream smaller text chunks safely.
  - **L87**: `sample_rate` is set (this should match pipeline/transport expectations).

### 19.6 `med_assist/service/voice/agent_processor.py` (LLM streaming → TTS frames)

This is the “voice equivalent” of the chat WebSocket + Redis stream consumer, but it’s in-process and frame-based.

- **L19–23**: IST clock helper used for profiling logs.
- **L47–207**: `EchoAgentProcessor`.

Key control flow:

- **L70–76**: only handles `LLMContextFrame` specially; everything else is passed through.
  - **Why**: the processor should not break transport/STT/VAD frames.
- **L77–100**: extracts last user text from context messages.
  - Handles list-of-content-items vs string.
  - **Why**: context aggregator provides generic multi-part content.
- **L104–112**: appends user message to in-memory history (`self._conversation_history`).
  - **Why**: voice pipeline persists transcript at the end; it needs history.
- **L114–121**: builds `ConversationContext` and pushes `LLMFullResponseStartFrame()`.
  - **Why**: downstream may use start/end markers.
- **L129–169**: runs `self._agent.run_stream(context, out_msg_id)` and processes events:
  - `TEXT`: pushes `LLMTextFrame(text=chunk)` (L132–144)
    - **Why**: TTS (ElevenLabs) performs sentence aggregation; processor need not buffer by sentence.
  - `DONE`: appends assistant message to history (L145–160)
  - `ERROR`: logs error (L161–166)
- **L170–185**: cancellation path for interruptions (barge-in):
  - saves partial assistant text to history, re-raises cancellation.
- **L196–202**: always closes generator and emits `LLMFullResponseEndFrame()` in `finally`.
  - **Why**: ensures cleanup and consistent downstream state.

### 19.7 `med_assist/config/voice.py` (VAD + ElevenLabs tuning constants)

- **L6–9**: `VOICE_PROFILING_ENABLED` env flag.
- **L15–70**: ElevenLabs defaults and tuning constants:
  - stability, similarity, style, speaker boost, speed, normalization
  - **Why**: these are opinionated defaults to preserve consistent voice quality across agents.
- **L73–83**: `VADConfig` (WebRTC defaults at 16k).
- **L85–106**: `TelephonyVADConfig`.
  - **Note**: docstring references “8k mulaw”, but current telephony path uses L16/16k input.
  - The parameters still matter because:
    - telephony has echo/sidetone/background noise, independent of sample rate.
- **L108–116**: inline explanation of `SpeechTimeoutUserTurnStopStrategy` behavior.

### 19.8 Session bootstrap utilities used by telephony

Telephony uses the same session model as chat.

#### `common/config.py`

- **L9–16**: `get_config()` reads env `MATRIX` and parses JSON.
  - **Why**: telephony `/answer` uses `HOST` to form public WS URL.

#### `med_assist/service/manage_session.py`

- **L77–189**: `create_session()` is used by `vobiz_answer`.
  - User context allow-list behavior is controlled by `USER_CONTEXT_ALLOW_LIST` and `referer` in the request body.
  - **Why**: telephony calls are unauthenticated but still attach user context (mobile).

#### `med_assist/utils/session_utils.py`

- **L63–74**: `save_session_to_cache()` writes Redis key `mat-{sid}` with TTL.
- **L77–91**: `get_session_from_cache()` reads Redis key and returns `SessionCache`.
  - This is what `voice_ws.py` uses for token validation.

---

## 20) “Do not make mistakes” checklist for building WebRTC voice like telephony

- **Match the real audio contract**:
  - Telephony inbound is currently `audio/x-l16;rate=16000` and deserialized by `VobizL16FrameSerializer`.
  - Telephony outbound is inherited from `PlivoFrameSerializer` (often mulaw/8k in telephony world).
- **Keep STT sample_rate consistent** with transport/internal frames.
- **Use VAD-based start strategy** to avoid bot-echo triggering false user turns.
- **Enable interruptions** (`allow_interruptions=True`) for barge-in.
- **Do not store raw audio** unless requirements explicitly change; current system persists transcript only.

