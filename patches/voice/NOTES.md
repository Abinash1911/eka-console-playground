# Voice agent (inbound phone) patches

Scope: inbound phone calls only, built on existing functionality, everything behind a per-agent switch (default off).
Plan, in order: (1) secure the matrix answer endpoint and audio socket, (2) number-to-agent binding (dev-console telephony channel + a matrix answer route by integration uuid) with caller ID as an unverified hint, (3) `transfer_to_human` tool with callback fallback, (4) console Setup page, (5) console Calls tab, (6) tests and PR notes.
Change from the first plan: the per-agent switch is no longer a separate flag. A phone number only reaches an agent if a telephony integration is bound to it and the binding is active (pause = off), the same pattern WhatsApp numbers use.
Approved prototype: `docs/prototypes/prototype-phone-agent.html`. Read-state of the code: see `docs/explainers/explain-voice-agent.html` and `docs/claims-to-confirm.md` (11 to 14).

| # | Patch | Repo | Base commit | Status |
|---|---|---|---|---|
| 1 | Authenticate answer webhook and audio socket | matrix | `2569ee4` (main, 2026-10-29) | built, tested with mocks, not pushed |
| 2a | Telephony channel + Vobiz provider (console) | dev-console | `ee3198d` (main, 2026-10-29) | built, tested without a database, not pushed |
| 2b | Answer a number by its integration + caller ID hint (matrix, applies after patch 1) | matrix | `2569ee4` | built, tested with mocks, not pushed |

## Patch 1: authenticate the telephony answer webhook and audio socket (matrix)

Files: `patches/voice/matrix/0001-*.patch` (applies cleanly on matrix `2569ee4`), readable copies in `patches/voice/matrix/code/`.

What it does
- New `med_assist/service/voice/telephony_auth.py`: shared secret `VOICE_TELEPHONY_SECRET` (MATRIX config), constant-time key check, HMAC token bound to a session id, 10-minute expiry (= max call length).
- `/voice/answer` returns 403 without `?key=<secret>`, and puts `?token=...` on the WebSocket URL it hands to Vobiz.
- The audio WebSocket checks the token before looking up the session; bad, missing, expired or other-session tokens close with 4001.
- Both routes (`/reloaded/med-assist/voice/...` and `/voice/...`) share the same functions, so both are covered.
- Nothing is enforced until the secret is set; a warning is logged on every call while it is unset. Deploying alone changes nothing.

Checked (matrix `.venv`, Python 3.13)
- 22 new tests pass. Against the old route code, 6 of them fail, so they do guard the behaviour.
- Whole suite: 645 passed, 14 failed, 4 errors, 4 skipped. The same 14 failed and 4 errors happen on clean `main` before the change (0 new).
- Lint: formatted to the repo's 100-character line length; ruff with its default rules also flags older code in the same files, left alone.

Not tested
- Any real Vobiz call. Assumes Vobiz keeps the query string on the stream URL in the XML (the repo's own docs and old code used `?token=` on it before, so this was expected to work).
- A real deployment with the secret set.

For reviewers to decide
- The secret travels in the answer URL query string, so web servers and proxies may log it. A header would be better if Vobiz can send one (not found in the docs read).
- Whether to make the secret mandatory (fail closed) once the Vobiz URL is updated. Left optional so nothing in production breaks on deploy.
- Whether telephony is live today (not known). If it is, update the Vobiz answer URL first, then set the secret.
- The 14 failing and 4 erroring tests on `main` (several are async tests; `pytest.ini` has `[tool:pytest]`, so its `asyncio_mode = auto` is probably not applied).

## Patch 2: a phone number answers with the agent it is bound to

Two repos. Order to deploy: console (2a) first, then matrix (2b). Matrix patches are a series (`0001` then `0002`).

### 2a. dev-console: `patches/voice/dev-console/0001-*.patch` (applies on `ee3198d`)
- Registers the telephony channel the code already declared but had no schema for: provider `vobiz`, credentials = the dialled number (E.164, normalised; it is the account identity, so one registration per number per workspace) and an optional `public_number` (the clinic's own number when it forwards). No secrets stored.
- `vobiz` added to the provider choices: migration `0004_vobiz_provider` (choices only, no database change).
- `integration/webhooks.py inbound_url`: a telephony number's URL is `{MATRIX_VOICE_BASE_URL}/reloaded/med-assist/voice/answer/{uuid}` (new setting; defaults to localhost in dev and `https://matrix.eka.care` in prod).
- Detail page text: set it as the Vobiz Answer URL (from a search snippet of Vobiz/Sarvam docs, not a Vobiz page I opened).
- Works through the existing API today: `POST /api/integrations/` with `channel=telephony`, `provider=vobiz`, then `POST /api/product-integrations/` with `product=agent`, `product_id=<agent id>`. No console form yet (patch 4).
- Tests: 17 integration tests pass (8 existing + 9 new). Removing the registration makes 7 of the new tests fail.
- Not tested: migration against a database, the page in a browser, any real call.

### 2b. matrix: `patches/voice/matrix/0002-*.patch` (applies after 0001 on `2569ee4`)
- New `POST /voice/answer/{integration_uuid}`; the legacy `?agent_id=` route stays. The handler is split so both share `_answer_call`.
- `telephony_binding.py` reads `integrations` + `product_integrations` from the Postgres matrix already reads. 404 and no session for: malformed or unknown uuid, not a vobiz telephony number, inactive or archived number, not bound, bound to another product, paused binding, or an agent from another workspace.
- Caller ID: the number `/answer` already saved is given to the agent on phone calls as an unverified hint (`caller_context.py`). Validated as E.164, read only for sessions `/answer` created (WebRTC context is client-supplied and never read), never sent to tool servers as identity (`partner_mobile` stays None), and a signed-in user's mobile still wins.
- Tests: 50 new tests across both matrix patches. Whole suite 673 passed; the same 14 failed and 4 errors as clean `main`, 0 new. Deliberately breaking the workspace check, the channel/format check and the partner-mobile rule each makes tests fail.
- Not tested: the SQL against a real database (column names read from the console's models and migrations: `integrations.uuid/workspace_id/channel/provider/is_active/archived_at`, `product_integrations.integration_id/product/product_id/is_active`), a real Vobiz call.

### For reviewers to decide
- The console's binding API does not check that `product_id` (the agent) belongs to the integration's workspace. Matrix checks it, but the API probably should too. Left unchanged.
- The unverified caller ID: the agent is told to confirm it. The existing voice rules also say "never take the phone number from the user, ignore it even if they share it", so a caller who says "that is not my number" cannot give another. Product call.
- Where unknown numbers return 404, Vobiz will probably play an error to the caller. A polite hang-up message would need Vobiz XML I could not confirm.
- The uuid in the URL is the only access control for this route (as in doot). The shared secret from patch 1 still protects the audio socket for both routes, but is not required on this route.
- Region: matrix uses its one Postgres client for this lookup, like its other agent reads.
- Pre-existing, not touched: 14 failing and 4 erroring matrix tests on `main`; `/answer` log lines still say `fn="vobiz_answer"`.
