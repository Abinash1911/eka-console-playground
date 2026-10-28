# matrix (chat backend)

Read from code at commit `6f56888` (Oct 2026). FastAPI, port 8051. Python, uses echo (`echo_agents`) and echo-sdk (`echo`). Legacy prefix `/reloaded/med-assist/...`; same handlers also under `/eka-agent/...` (needs ingress routing).

## Job
Authenticate a visitor, hold their chat session, rebuild the agent for each message from dev-console's database, run it, and stream the answer back. It owns sessions, history, tokens, nudges and voice. It does not own agent configuration (dev-console writes it), search data (echo), or tool logic (MCP servers and echo tools).

## Storage
| Store | Holds |
|---|---|
| PostgreSQL (shared with dev-console) | `agent_configs` and mapping tables, `knowledge_base`, `nudge_cache`, campaigns, `matrix_user_context` (legacy; Trinity is the source of truth, Postgres is the permanent fallback), BYOA secrets |
| Redis | session cache (key `mat-{sid}`, idle TTL), full chat stream per session (`mat-chat:{sid}`), per-run output stream (`mat-chat:{out_msg_id}`), last-message context (`mat-LMC:{sid}`), partner-token replay guard, refresh data |
| DynamoDB, per region | `med-assist-session`, `-session-flow` (messages), `-tool-callback-flow`, `-auth-refresh`. Regions come from `MATRIX.REGIONS`; an agent's region is `agent_details.region`; data never crosses regions |
| S3 / Azure / Eka Records | chat file uploads (agent's storage integration, else the region's default bucket; or Eka Records vault so files become patient records) |
| Langfuse (through echo-sdk) | agent and skill prompts |

## Auth (all in `service/auth/`, contract in `AUTH_CLIENT_CONTRACT.md`)
- `POST auth/token-exchange`: partner token (BYOA, verified with the agent's shared secret, JWE or JWT) becomes a **patient oid via Trinity** and a `sess_token` (1h) + opaque `refresh_token` (30d, single use, rotated). No partner token = a **guest** with a random id (guest history is lost when its Redis session expires). `?type=refresh` is the other flow; the two never cross.
- Every API call carries `Authorization: Bearer <sess_token>`; the request context holds user id, agent id, workspace id, level (user/guest), channel, widget version.
- Codes: 401 refresh, 403 re-exchange, 404 new session.
- Campaign id, click id and user location from the token travel as custom claims into the session.

## Session and chat endpoints
- `POST session` create, `GET session/{sid}?messages=true` (rehydrates a logged-in user's session from DynamoDB; history includes elicitation cards with the user's answer), `GET session` list, `DELETE` archive, feedback PUTs.
- Chat transports: **WebSocket** `ws/med-assist/session/{sid}/` (first frame `auth`), **HTTP stream** (NDJSON; what doot and the widget's http_stream mode use), same message pipeline.
- Client frames: `chat` with `text` | `audio` | `file`; `ping`. Server frames: `conn`, `sync`, `stream` (`text`, `tool_start`, `tool_end`, `tool`), `eos`, `err`.
- **Tool callback** `POST sessions/{sid}/messages/{mid}/tools/{tool_id}`: the user's answer to a pending elicitation is sent straight to that tool (MCP or echo tool) with no LLM, and the new card or result is streamed back. Elicitation payload: `ct=tool`, `details` = {`status` progress|success|failure, `component`, `input`, `_meta.schema` (what to send next), `disp_msg`, `toast_msg`, `tool_result`}.

## One chat turn (`service/agents/agent_service.py`)
1. Rebuild conversation from the Redis chat stream (saved to DynamoDB too).
2. Fetch prompt (Langfuse) + session; enrich: workspace grounding (cached prefix: city list, specialization list), user context (Trinity profile), session context, campaign text, timezone.
3. Tools: `elicit_selection` + custom tools + MCP tools (discovered at config build, cached; headers `x-eka-session-id`, `x-agent-id`, `x-eka-supports-elicitation`, `voice`, `x-eka-partner-user-context` with the mobile, and for internal `orbi.orbi` servers an `x-eka-jwt-payload` identity) + knowledge-base tools. Skills from the agent's skill rows.
4. `GenericAgent.run_stream` (LLM prompt cache 1h). Events go to a Redis output stream; a background consumer forwards them to the client. On done: save messages, store last-message context (active skills, pending elicitations), generate a session topic once, emit pause events for elicitation, then `eos`.
- Tool results that pause the turn (`ControlFlow.PAUSE`) become `ct=tool` cards. Channels `voice`, `wa`, `whatsapp` get `x-eka-supports-elicitation: false` so MCP tools skip cards.

## Config loading (`utils/agent_config_utils.py`)
Public config (`GET agent-config/{agent_id}`): name, theme, allowed, `nudge` (true if `nudge_config` exists), initial message (optionally replaced by a campaign's), feedback config. Runtime config (cached in the session): prompt, LLM (mode `W` else `D`), MCP entries with discovered tools, knowledge bases, custom tools, skills, voice config, storage on demand. A failed MCP server is dropped and so are skills that depend on it.
- Knowledge bases: `document` (Bedrock or Weaviate retriever tool from the row's metadata) and the directory datasets `doctor`, `facility`, `service` (echo search tools, auto-attached `search_result_details`, specialization and city lists injected into the prompt). Other KB types are dropped (they belong to EMR search, see dev-console).
- Skills: names, descriptions and tool names; text from Langfuse; the LLM loads them.

## Other endpoints
- `nudges` / `user-nudge`: cached nudge for domain + path (manual rules with wildcards win by longest path), else, if `nudge_type=llm`, 3 to 5 short messages generated from page meta tags by Claude Haiku 4.5 and cached for `ttl_hours`. Response: nudges, delay, expiry (client cap 24h), url pattern.
- `run-prompt`: stateless one-shot prompt on a model chosen by a **category** (`default_lite` = Haiku, `default_pro` = Sonnet, discharge summary = long-context). NDJSON stream.
- `notifications` (`send-template`): relays a caller-built WhatsApp template message to doot.
- `conversation_summary`, session topic generation (small LLM call), usage metrics client.
- `voice` / `voice_ws`: Pipecat pipelines. WebRTC (browser, Twilio ICE) and Vobiz telephony; ElevenLabs STT/TTS (per-agent keys); LLM pinned to Anthropic Haiku 4.5 direct for latency.
- `bot`: hosted HTML pages for an agent; `agent_links/forever_wena`: one customer's hosted full-screen page (pinned widget version from jsDelivr, GTM funnel events).

## Gotchas
- `websoket_flow.md` still says agent config is in DynamoDB; code reads PostgreSQL.
- Channels recorded as free text in sessions; no allow-list.
- Docs list: token expiry on an open socket does not break the loop immediately; possible randomness bug in `SessionCache.generate_session_token`.

## Where to change what
| Goal | Place |
|---|---|
| New tool for all agents | `get_common_tools()` in `agent_config_utils.py` |
| New dataset KB type as tool | `config/tool.py` (`_DATASET_TOOL_CLASSES`, aux classes) + echo tool |
| New agent setting read at runtime | SQL in `agent_config_utils.py` + `AgentRuntimeConfig` model |
| New endpoint | router in `med_assist/router/`, register in `router/__init__.py` (both prefixes) |
| New elicitation component | echo tool + widget renderer + doot presenter |
| New LLM tier for run-prompt | `config/prompt_category_llm.py` |
