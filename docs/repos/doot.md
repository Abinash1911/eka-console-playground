# doot (WhatsApp bridge)

Read from code and docs at commit `36e7eeb` ("scribesnap renamed to Doot"). **Scribesnap = Doot** (older docstrings and the echo code still say scribesnap). FastAPI, Redis, port 8000.

## Job
Connects WhatsApp users to the chat backend (matrix) and sends outbound WhatsApp templates. It is a translator: WhatsApp messages in, matrix chat calls out, matrix replies back as WhatsApp buttons, lists and text.

## Two bots
- **Medassist** (this is the chat agent path).
- **EkaScribe** (a login + recording bot for doctors; handlers in `app/handlers/scribe_handler.py`, PDF generation). Not part of the chat-agent work.

## Inbound path (WhatsApp user to agent)
```
WhatsApp provider (Meta, Interakt, Interakt-TP, Netcore, Turn.io, Twilio)
  -> POST /wh/{provider}/{bot}?agent_id=...        static route, handlers registered at startup
  -> POST /wh/{product}?agent_id=...               dynamic route: handler built on first request from dev-console
  -> POST /integration/v1/channel/whatsapp/messages/inbound/{integration_uuid}   newer route: account -> binding -> product
verify signature (HMAC per provider) -> dedupe -> MedassistBridge.run()
```
- **Dynamic route:** `GET console.orbi.orbi/internal/agents/{agent_id}/integration/` returns provider + credentials. The built handler is cached in pod memory with no expiry (rotating credentials needs a pod restart).
- **Newer route:** an integration uuid resolves through dev-console (`/api/resolve/{integrations|product-integrations}/{uuid}/`) to an account and a binding (`product` = `agent`, `product_id` = agent id). A paused or missing binding drops the message with a 200.
- Always answers 200 on inbound, because providers retry the whole batch on any non-2xx.

## What `MedassistBridge.run()` does, in order
1. Ignore status events; dedupe on provider message id (Redis).
2. `reset` command clears the session. "delete me" flow runs before everything else.
3. **Journey mute** (Turn.io): while a Turn journey owns the chat, stay silent and buffer the Q&A. When the journey ends, the buffered Q&A is injected once as context into the first agent message.
4. Send a "thinking" acknowledgement (feature flag).
5. Get or create the user's session record (Redis, per user and agent).
6. If no matrix session: **consent gate** (agent-specific, stored in Redis forever plus a dev-console audit row, re-prompts when the consent version changes), then **session choice** (resume a session a template opened, or start new), else create a matrix session.
7. If an elicitation is pending, try to resolve the user's reply locally (no LLM). On no match, clear it and send the text with a `[TOOL DECLINED ...]` marker.
8. Otherwise build a payload (text, voice transcribed to text, photo or document upload, location) and stream a chat turn from matrix, with retry.
9. Render the reply (below).

## Talking to matrix (`MedassistClient`)
- Token exchange `POST /reloaded/med-assist/auth/token-exchange` (BYOA: doot mints a short-lived encrypted token with the agent's shared secret, user identity = the phone number), refresh with `?type=refresh`, tokens cached per agent and phone.
- `POST /reloaded/med-assist/session`, `GET .../session/{sid}`, `GET .../session` (list), `POST .../session/{sid}/chat` (NDJSON stream; also the file-upload handshake), tool callback endpoint, `GET .../agent-config/{agent_id}`.
- Header `x-channel` is the WhatsApp channel value (matrix suppresses card/pill elicitation for `wa`/`whatsapp`, but doot renders its own).

## Rendering matrix replies as WhatsApp
- Text chunks go as messages. Elicitation chunks (`ct=tool`) are parsed into a pending state and shown natively:
  - `pills` / `multi`: list (up to 10) or numbered buttons.
  - `card`: numbered list; match by number or title.
  - `doctor_card`: doctor list, then dates, then slot pills (4 per page plus "More"); a slot pick sends `[SLOT SELECTED: ...]` to the model.
  - `mobile_number`, `otp`, `email_address`: plain prompt; free text captured.
  - `media_card`: voucher text, terminal.
- **Two ways to answer an elicitation:** if the server marked it `status: progress`, doot calls the tool callback directly (no LLM); otherwise it sends a marker message (`[SELECTION: x]`, `[DOCTOR SELECTED: ...]`) and the model decides. So a prompt must define handlers for these markers.
- List row ids are `{token}.{n}`; the token is a hash of the list's content, so nothing is stored to resolve a tap.

## Outbound (proactive) messages
- `POST /send/template` (internal only): pick the agent's WhatsApp integration, map a logical `template_id` to the provider's template (`app/config/templates.yml`, or `templates` in the integration config), build the components, send, dedupe on an idempotency key (Redis, 24h). 502 means retryable, 422 means do not retry.
- `POST /integration/v1/channel/whatsapp/messages/outbound/{binding_uuid}`: send one message through a binding (so a reassigned number fails closed).
- When a template is sent, doot resets the cached session and stores `t_sid`, so the user's reply re-enters session selection and "Continue" resumes the session that sent it.
- WhatsApp rule behind all this: free text is allowed only 24h after the user's last message; anything later must be a pre-approved template.
- Who calls send/template: matrix `notifications` relays it (echo builds the message, Jugaad schedules replays).

## Integration events out
`dispatch.py` posts normalised events (messages, statuses) to callback URLs in a binding's config. One attempt, no retry; failures log the full event.

## Providers
`app/services/whatsapp/providers/`: Meta, Interakt (legacy), Interakt-TP, Netcore, Turn.io, Twilio. Credentials per agent come from dev-console integrations; a static fallback lists numbers in `app/config/number_config.yml` (env-injected).

## Known risks (from its own doc)
No TTL on the dynamic handler cache; a missing `DEV_CONSOLE_INTERNAL_URL` silently drops webhooks; no webhook dedupe on the legacy static routes; a concurrent cold start fetches twice.

## Where to change what
| Goal | Place |
|---|---|
| New WhatsApp template | `app/config/templates.yml` (or the integration's `templates`) |
| New elicitation type on WhatsApp | `app/bridge/medassist/elicitation.py`, `presenter.py` |
| New WhatsApp provider | `app/services/whatsapp/providers/` + factory |
| New consent rule | agent integration config + `consent.py` |
