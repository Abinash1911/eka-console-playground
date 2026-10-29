# Voice agent (inbound phone) patches

Scope: inbound phone calls only, built on existing functionality, everything behind a per-agent switch (default off).
Plan, in order: (1) secure the matrix answer endpoint and audio socket, (2) number-to-agent binding (dev-console telephony channel + a matrix answer route by integration uuid) with caller ID as an unverified hint, (3) `transfer_to_human` tool with callback fallback, (4) console Setup page, (5) console Calls tab, (6) tests and PR notes.
Change from the first plan: the per-agent switch is no longer a separate flag. A phone number only reaches an agent if a telephony integration is bound to it and the binding is active (pause = off), the same pattern WhatsApp numbers use.
Approved prototype: `docs/prototypes/prototype-phone-agent.html`. Read-state of the code: see `docs/explainers/explain-voice-agent.html` and `docs/claims-to-confirm.md` (11 to 14).

| # | Patch | Repo | Base commit | Status |
|---|---|---|---|---|
| 1 | Authenticate answer webhook and audio socket | matrix | `2569ee4` (main, 2026-10-29) | built, tested with mocks, not pushed |
| 2 | Number-to-agent + caller ID | matrix, dev-console | | not started |

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
