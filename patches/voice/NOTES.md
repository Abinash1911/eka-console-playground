# Voice agent (inbound phone) patches

Scope: inbound phone calls only, built on existing functionality, everything behind a per-agent switch (default off).
Plan, in order: (1) secure the matrix answer endpoint and add the switch, (2) number-to-agent binding with caller ID in the session, (3) `transfer_to_human` tool with callback fallback, (4) console Setup page, (5) console Calls tab, (6) tests and PR notes.
Approved prototype: `docs/prototypes/prototype-phone-agent.html`. Read-state of the code: see `docs/explainers/explain-voice-agent.html` and `docs/claims-to-confirm.md` (11 to 14).

| # | Patch | Repo | Base commit | Status |
|---|---|---|---|---|
| 1 | Secure answer endpoint + switch | matrix | | not started |
| 2 | Number-to-agent + caller ID | matrix, dev-console | | not started |
