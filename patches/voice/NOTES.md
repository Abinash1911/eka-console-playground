# Voice agent (inbound phone) patches

Scope: inbound phone calls only, built on existing functionality, everything behind a per-agent switch (default off).
Plan, in order: (1) secure the matrix answer endpoint and audio socket, (2) number-to-agent binding (dev-console telephony channel + a matrix answer route by integration uuid) with caller ID as an unverified hint, (3) `transfer_to_human` tool (callback request fallback is not in patch 3), (4) console Setup page (done: numbers, agent, handover; test call not included), (5) console Calls tab, (6) tests and PR notes.
Change from the first plan: the per-agent switch is no longer a separate flag. A phone number only reaches an agent if a telephony integration is bound to it and the binding is active (pause = off), the same pattern WhatsApp numbers use.
Approved prototype: `docs/prototypes/prototype-phone-agent.html`. Read-state of the code: see `docs/explainers/explain-voice-agent.html` and `docs/claims-to-confirm.md` (11 to 14).

| # | Patch | Repo | Base commit | Status |
|---|---|---|---|---|
| 1 | Authenticate answer webhook and audio socket | matrix | `2569ee4` (main, 2026-10-29) | built, tested with mocks, not pushed |
| 2a | Telephony channel + Vobiz provider (console) | dev-console | `ee3198d` (main, 2026-10-29) | built, tested without a database, not pushed |
| 2b | Answer a number by its integration + caller ID hint (matrix, applies after patch 1) | matrix | `2569ee4` | built, tested with mocks, not pushed |
| 3a | Handover settings on the agent binding (console, applies after 2a) | dev-console | `ee3198d` | built, tested without a database, not pushed |
| 3b | `transfer_to_human` tool, transfer and result URLs (matrix, applies after 2b) | matrix | `2569ee4` | built, tested with mocks and hand-fed frames, not pushed |
| 4 | Console pages: register a phone number, connect an agent, handover form (applies after 3a) | dev-console | `ee3198d` | built, rendered and checked in a browser, tested without a database, not pushed |
| 5a | Record each call as a conversation with a summary (matrix, applies after 3b) | matrix | `2569ee4` | built, tested with mocks, not pushed |
| 5b | Calls tab on the number's page (console, applies after 4) | dev-console | `ee3198d` | built, rendered in a browser; page tests run, database tests written but not run, not pushed |
| 6 | "Test this number" card (console, applies after 5b) | dev-console | `ee3198d` | built, rendered in a browser, tested without a database, not pushed |

## Patch 1: authenticate the telephony answer webhook and audio socket (matrix)

Files: `patches/voice/matrix/0001-*.patch` (applies cleanly on matrix `2569ee4`), readable copies in `patches/voice/matrix/code/`.

What it does
- New `med_assist/service/voice/telephony_auth.py`: shared secret `VOICE_TELEPHONY_SECRET` (MATRIX config), constant-time key check, HMAC token bound to a session id and a purpose (so a token for one door never opens another), 10-minute expiry (= max call length).
- `/voice/answer` returns 403 without `?key=<secret>`, and puts `?token=...` on the WebSocket URL it hands to Vobiz.
- The audio WebSocket checks the token before looking up the session; bad, missing, expired or other-session tokens close with 4001.
- Both routes (`/reloaded/med-assist/voice/...` and `/voice/...`) share the same functions, so both are covered.
- Nothing is enforced until the secret is set; a warning is logged on every call while it is unset. Deploying alone changes nothing.

Checked (matrix `.venv`, Python 3.13)
- 23 new tests pass. Against the old route code, 6 of them fail, so they do guard the behaviour.
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
- `telephony_binding.py` reads `integrations` + `product_integrations` from the Postgres matrix already reads. a rejecting Hangup (`<Hangup reason="rejected"/>`, which Vobiz documents as not billed) and no session for: malformed or unknown uuid, not a vobiz telephony number, inactive or archived number, not bound, bound to another product, paused binding, or an agent from another workspace.
- Caller ID: the number `/answer` already saved is given to the agent on phone calls as an unverified hint (`caller_context.py`). Validated as E.164, read only for sessions `/answer` created (WebRTC context is client-supplied and never read), never sent to tool servers as identity (`partner_mobile` stays None), and a signed-in user's mobile still wins.
- Tests: 51 new tests across patches 1 and 2b (23 + 28). Whole suite 674 passed; the same 14 failed and 4 errors as clean `main`, 0 new. Deliberately breaking the workspace check, the channel/format check and the partner-mobile rule each makes tests fail.
- Not tested: the SQL against a real database (column names read from the console's models and migrations: `integrations.uuid/workspace_id/channel/provider/is_active/archived_at`, `product_integrations.integration_id/product/product_id/is_active`), a real Vobiz call.

### For reviewers to decide
- The console's binding API does not check that `product_id` (the agent) belongs to the integration's workspace. Matrix checks it, but the API probably should too. Left unchanged.
- The unverified caller ID: the agent is told to confirm it. The existing voice rules also say "never take the phone number from the user, ignore it even if they share it", so a caller who says "that is not my number" cannot give another. Product call.
- A rejected number sounds like a rejected call to the caller (no spoken message). A spoken message would need an answer plus Vobiz's Speak voice, which has no Hindi in its docs.
- The uuid in the URL is the only access control for this route (as in doot). The shared secret from patch 1 still protects the audio socket for both routes, but is not required on this route.
- Region: matrix uses its one Postgres client for this lookup, like its other agent reads.
- Pre-existing, not touched: 14 failing and 4 erroring matrix tests on `main`; `/answer` log lines still say `fn="vobiz_answer"`.

## Patch 3: hand the call to a person (console + matrix)

Order: 3a after 2a, 3b after 2b. Matrix series is now `0001`, `0002`, `0003`.

Vobiz facts used (read from Vobiz's own docs on 2026-10-29, not search summaries): Transfer API `POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/` with `X-Auth-ID` and `X-Auth-Token`, body `legs`/`aleg_url`/`aleg_method`, replies 202; the new URL must return XML; `<Dial callerId timeout action redirect>` with `<Number>`; `DialStatus` values `completed`, `busy`, `failed`, `cancel`, `timeout`, `no-answer`; `<Hangup reason="rejected"/>` as first element rejects without billing; `callerId` must be a Vobiz number the account owns.

### 3a. dev-console: `patches/voice/dev-console/0002-*.patch`
- Agent binding `config` accepts `handover`: `number` (E.164, normalised), optional `hours` (`start`, `end`, `timezone`; start after end = overnight), `ring_seconds` 10 to 60. It lives on the binding config because matrix reads it from the shared Postgres and cannot decrypt the number's credentials.
- Phone-number rules moved to `integration/schemas/phone.py`, shared with the Vobiz schema.
- 24 integration tests pass at this point: 8 that were already there, 9 from patch 2a, 7 here (5 for the handover config, 2 for the callback-slot fix below). Removing this change fails 4 of the new ones.
- Also fixes a problem this change would otherwise cause: the console's binding form listed every config field as a callback box, so `handover` would have appeared as a fake "Handover callback" and been wiped on save. `_slots` now only lists fields that hold a callback (2 tests fail without the fix).
- No console form yet (patch 4); the binding API accepts it today.

### 3b. matrix: `patches/voice/matrix/0003-*.patch`
- Tool `transfer_to_human(reason)` (reasons: caller_asked, not_understood, emergency, other). It declines outside staff hours and tells the agent when the team is in; otherwise it marks the call and tells the agent to say one short sentence.
- `HandoverProcessor` (between agent and text-to-speech) waits for the agent's reply to end and the caller to have heard it (plus a 0.5 s settle so a pause between sentences does not count), then calls Vobiz's Transfer API. A timer (8 s) covers a silent reply. If Vobiz refuses, the caller hears "Sorry, I could not connect you right now" and the agent can offer it again.
- `POST /voice/transfer/{session_id}` returns the `<Dial>` to the staff phone; `POST /voice/transfer-result/{session_id}` hangs up on `completed` and otherwise plays a short English apology. Both need a signed token with the `transfer` purpose.
- Off unless `VOICE_TELEPHONY_SECRET`, `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` and `HOST` are set (the transfer URL returns the staff number). The reason it is off is logged on each call. The legacy `?agent_id=` answer URL records no number, so it offers no handover.
- Tests: 56 new in `test_voice_handover.py` (107 new across the three matrix patches). Whole suite: 730 passed (623 on clean `main` plus 107); the same 14 failed and 4 errors as clean `main`, 0 new. Six deliberate breakages (no hours check, transfer before the reply ends, transfer URL open without the secret, no Vobiz auth headers, unvalidated caller ID in the XML, leftover timer after a refusal) each fail a test.

Not tested: a real Vobiz call or real audio. In particular that Vobiz really interrupts the stream and lets the audio socket close cleanly, that `BotStoppedSpeakingFrame` and `LLMFullResponseEndFrame` arrive in the order assumed on a live pipeline, and what the caller hears during the hand-off (ringback is Vobiz's `dialMusic` default `real`).

### For reviewers to decide (patch 3)
- Hand-off apology is English (Vobiz's Speak voices are listed without Hindi). A recorded `<Play>` message per language would be better.
- Not in patch 3, from the prototype: "take a callback request and text the clinic" when nobody answers, per-trigger toggles (the triggers are fixed in the tool text), recording the hand-off outcome for the Calls tab. All need patches 4 and 5.
- A transferred call is two legs with two charges on Vobiz (their docs).
- Staff hours are checked when the tool runs, in the clinic's timezone; public holidays are not handled.
- `VOBIZ_API_BASE_URL` defaults to Vobiz's documented base; override only if Vobiz gives another host.

## Patch 4: console pages for a phone number (dev-console)

`patches/voice/dev-console/0003-*.patch` (applies after 0001 and 0002 on `ee3198d`). Screenshots in `patches/voice/dev-console/screenshots/`.

What a person can now do in the console, without the API
- **Integrations, New:** a "Phone calls" tile, then a short form: name, the number to answer (with country code; cannot be changed later), and optionally the clinic's own number that forwards to it. Wrong numbers and duplicates give a clear message and keep what was typed.
- **The number's page:** the Answer URL to paste into Vobiz (labelled "Answer URL"), the agent picker (agent only: Messenger and the status callback are hidden, and the server refuses Messenger for a phone number), Pause / Resume / Disconnect as for WhatsApp numbers (pausing makes callers get the rejecting hang-up from patch 2b).
- **Hand over to a person:** staff phone number, staff hours (empty = always), timezone, ring seconds. Saved into the binding's `handover` config. A form without this section (WhatsApp numbers) leaves a stored handover alone; unticking removes it.
- A pointer to the agent's page, where voice, language and greeting already live.

Checked
- 49 integration tests pass (8 existing, 41 new across patches 2a to 4), without a database. The page tests render the real templates with a bare base layout. Five deliberate breakages (wiping handover on a WhatsApp-style save, allowing Messenger on a phone number, a duplicate number crashing, Messenger card shown on phone numbers, handover section missing) each fail a test.
- Screens rendered from the real templates and looked at in a browser (desktop, and the phone page at 390 px wide has no sideways scroll). The WhatsApp number page is unchanged.
- `makemigrations --check` finds nothing pending.

Not done / not tested
- The "Start a test call" button, the Calls tab (patch 5), and the "text the clinic when nobody answers" fallback from the prototype.
- Not run in the live console: the screenshots use Tailwind's in-browser build instead of the app's stylesheet. `theme/static/css/dist/styles.css` is a tracked build file; this patch does not regenerate it (the Dockerfile builds it). Run `python manage.py tailwind build` if the team keeps the file in step.
- Saving against a real database (the tests mock the database layer).
- Deleting a phone number is the existing soft delete: the number stays reserved, so the same number cannot be registered again in that workspace. Same as other integrations.
- Where handover is "on" in the console but the platform has no phone secret or Vobiz login set, nothing happens on a call (matrix logs why). The page says so in a hint; it cannot detect it.

## Patch 5: the Calls tab (matrix 0004 + dev-console 0004)

Apply order: matrix `0004` after `0003`; dev-console `0004` after `0003`. Screenshots: `patches/voice/dev-console/screenshots/calls.png`, `calls_mobile.png`.

5a, matrix: a phone call is now a recorded conversation
- The session is created with `channel="voice"` / referer `vobiz-telephony`, marked as a started conversation when the pipeline starts, and carries the number's `integration_uuid`.
- `call_record.py` writes a small summary into the session context at the end of the call: `{"call": {"v":1, "duration_s", "ended_by", "user_turns", "handover", "tools", "caller"}}`. `ended_by` is one of caller_hung_up, silence, time_limit, transferred, error. The caller number is masked in the summary, but the full number is still stored in the session's `initial_context.caller` (needed as the agent's hint), so reviewers should decide whether that is acceptable.
- Handover outcome (none, requested, transferred, failed, declined) comes from the handover tool state; tool names come from the agent processor.

5b, console: Calls tab
- Setup | Calls tabs on a phone number's page (WhatsApp numbers are unchanged). The table shows when, masked caller, length, outcome, how it ended, staff handover and tools used, with a link to the conversation. Three totals for the page shown: calls, % handed to staff, average length. A call with no saved summary shows "Not recorded".
- `console_index` now always promotes `call` and `integration_uuid` from the session context, whatever `CONSOLE_INDEX_CONTEXT_KEYS` says. `reads.list_calls` filters on the bound agent and the number, newest first, with the same paging as the conversations list.
- Only phone numbers have the page (404 for others); the agent must belong to the user's workspace.

Checked
- Matrix: 747 passed; the same 14 failed and 4 errors as clean `main`, 0 new.
- Console: 59 tests pass without a database (49 earlier + calls presenter, page and parsing tests). Breaking the always-promote rule fails 2 tests. Screens looked at in a browser, desktop and 390 px wide, no sideways scroll.
- Both series apply cleanly with `git am --3way` on clean `main` (matrix `2569ee4`, dev-console `ee3198d`).

Not tested
- `list_calls` tests and the ingest end-to-end test are written but could not run here (they need MySQL and Postgres). Run `python manage.py test console_index` in the team's environment.
- A real call: nothing has shown the summary actually arriving in Dynamo, going through the projection and appearing on the page.
- The end-of-call wiring inside the pipeline is not unit-tested (the summary builder is).

For reviewers to decide
- Sessions indexed before this change lack the promoted keys; a backfill is needed for old calls (there are none on real numbers yet).
- `list_calls` finds only the current agent's sessions; if a number is moved to another agent, older calls disappear from its tab. There is no index on `context_promoted`; fine for hundreds of calls per agent, revisit for more.
- Browser (WebRTC) voice sessions are still not recorded in Conversations, the same gap as before.
- No "resolved" or "booked" outcome: the agent cannot say whether the caller's goal was met.
- `theme/static/css/dist/styles.css` is a tracked build file and was not regenerated (new classes may need `tailwind build`).

## Patch 6: "Test this number" card (dev-console 0005)

Screenshots: `patches/voice/dev-console/screenshots/detail_phone_test_ready.png`, `detail_phone_test_notready.png`.

Decision: the button does not place a call. A real test has to be a phone call (it is the only way to test Vobiz, the number and the agent together). An in-browser call would test a different path (the web widget voice, which is not recorded in Conversations), and the console calling the user's phone would be outbound calling, which is out of scope and costs money. So the card makes the phone test easy and safe.

What it shows (phone numbers only, on the Setup tab)
- Checks the console can see: an agent is connected, the connection is on, handover is set up (optional).
- When ready: a "Call +91..." tap-to-call link (the clinic's public number if it forwards here, which tests the whole route; otherwise the dialled number), and four things to check on the call, ending with the Calls tab.
- Always: a note that the console cannot check Vobiz (Answer URL pasted?) or the platform's phone settings.

Checked: 62 integration tests pass without a database (3 more tests than patch 5b: 5 new card tests, 2 earlier presenter tests already counted). Two deliberate breakages (ready ignoring a paused connection; call link shown when not ready) each fail a test. Rendered from the real template in a browser, desktop and 390 px wide, no sideways scroll. Series applies on clean `main` (`ee3198d`).

Not tested: a real call, and `tel:` links on a real phone.
