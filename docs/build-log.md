# Build log (running)

Goal: build features in the real repos' own code, style and quality, so developers can review and ship with minimal rework. Rule: write to GitHub only when explicitly asked ("raise a PR" / "push"), never to `main`.

Last updated: 2026-10-28

## Repos connected (read) 
dev-console, synapse-sdk (read + push), doot, echo, matrix, eka-remote-mcp, eka-mcp-sdk (public, read-only), this repo (private, personal account; can be moved under eka-care later). Developer docs: developer.eka.care (allowed in network settings).

## Shipped / delivered

| Item | State | Where |
|---|---|---|
| Size feature LIFE-3141 (configurable floating widget size) | PR open (draft) | https://github.com/eka-care/synapse-sdk/pull/214, branch `feature/life-3141-widget-size` (the usual `feature/life-3141` holds another developer's commits, untouched) |
| Centered widget (search-bar launcher + centred dialog) | Built, NOT pushed, no PR | `centered-widget.zip`: `centered-widget.patch`, `centered-widget-with-size.patch`, `centered-widget-console.patch` (dev-console), `code/`, notes, screenshots. Local branch `feature/centered-widget` in the synapse-sdk clone (empty, patch applies cleanly on main d3c8268) |

## Centered widget: decisions made
- Launcher: narrow search-style bar ("Ask AI a question"), up to 560px, opens the same chat as a 560x640 dialog over a dimmed backdrop. Mobile uses the existing full-screen layout.
- Spec deviations (from `task-center-display-mode.md`): 560 not 720 wide; bar launcher not round icon; no `mobile-display-mode`.
- Esc / backdrop / X close; focus moves into dialog and back; Tab trapped.
- No nudge popup in this mode. The bar's text box shows the page's nudge text after the nudge's own delay; default "Ask AI a question" when nudges are off or none exist; rotates every 4.5s if several; still under reduced motion.
- One short glow (~2s) when the nudge text appears, in the agent's `theme.accent` (indigo fallback); none under reduced motion.
- `custom-launcher-styles` ignored in this mode.
- Bundle budget raised 95500 -> 96500 (documented).
- Open follow-ups: use accent for the send button and honour host theme override; focus/phone/live-session testing; Conversations channel filter lacks `center`; developer docs; x-init localStorage bug in the console Widget tab.

## Findings from reading the repos
- Tools in eka-mcp-sdk: appointments (book, cancel, reschedule, VIDEO mode with video link), patients, vitals, records, prescriptions (by ID only), doctors/clinics, ABHA, assessments, CRM lead.
- Doctor search already exists in echo (`search_doctors`, facility/service search, city/specialization lists), loaded by matrix for agents with a doctor dataset.
- Reminder scheduler exists in echo (jugaad, WhatsApp templates), used for checkup reminders.
- Prepaid vs postpaid: no code reads it; booking has no payment step; payments API only has "get transaction status". Pay-in-chat needs a payment-link service (gateway unknown).
- Skills (dev-console `Skill` model): prompt packs attached to agents with tool/KB/dataset dependencies, activated by the LLM at runtime.
- Knowledge bases: dataset KBs complete (CSV import). Document KBs (FAQ): console stores only name + provider + provider id; the file-upload UI is stale (fields missing from the model); nothing in dev-console, matrix or echo indexes documents into Bedrock/Weaviate. Ingestion service unknown.

## Open questions / blocked
1. Where do clinic documents get indexed (Weaviate/Bedrock)? Needed for FAQ knowledge sources.
2. Payment gateway for prepaid online consults.
3. Sandbox credentials (`EKA_CLIENT_ID` / `EKA_CLIENT_SECRET`, host `api.dev.eka.care`) to test whether `get_doctor_services` exposes prepaid.
4. Is there a list-prescriptions endpoint? (needed for the prescription explainer)
5. Centered PR: confirm "Centered only" and give the go-ahead to push.

## Ideas queue (not started)
Teleconsult booking, prescription explainer, vitals tracking, default skills (book/reschedule/cancel; find doctor/facility/service; clinic FAQ), knowledge-sources UI, onboarding checklist, new Home, videos, WhatsApp flow.

## Automation candidates (propose when noticed)
1. Patch-packaging skill: apply patch to latest main, tsc/vitest/lint/build, regenerate patches + readable `code/` + notes + zip. (Repeated ~6 times.)
2. "Does this already exist?" skill: search echo/matrix/eka-mcp-sdk/developer docs before building anything.
3. Browser check skill for widget visuals (Playwright harness for the bar, nudge, glow).
4. Watch PR #214 for CI and review comments (PR subscription).
5. Weekly loop: check open patches/branches against upstream `main` drift.

## 2026-10-28: matrix read
Read matrix routes, auth contract, session/WebSocket flow doc, agent run, config loading, KB loading, nudge service. Written into `docs/ecosystem-map.md`. Biggest finding: matrix only turns doctor/facility/service dataset KBs into tools; medication/lab/symptom/diagnosis datasets stored in the console are dropped at runtime. Next: echo.

## 2026-10-28: echo read
Read echo's guide, tools, services, doctor-search design doc, Weaviate retriever, triage, vitals, pharmacy flow, agent_memory README. Framework repo `echo-sdk` is not connected (skills runtime, prompt provider, tool contract live there). Findings: vitals and triage tools exist in echo but matrix only auto-attaches `elicit_selection`; Jugaad scheduler is generic; the pharmacy tool is a working template for multi-step card flows (could be a pattern for booking/payment cards). Open: Doot vs Scribesnap naming for WhatsApp relay. Next: doot.

## 2026-10-28: echo-sdk read
Cloned `eka-care/echo-sdk` read-only (public repo, not attached). Skills fully understood: prompt-backed (Langfuse), LLM loads them via `load_skill`, tool visibility = base tools + active skills' tools. Weaviate connector confirms ingestion is a separate pipeline and gives the record schema it must write. Next: doot.

## 2026-10-28: full read of the remaining repos
Read doot, dev-console, matrix (leftovers), eka-remote-mcp, eka-mcp-sdk, synapse-sdk (rest), echo, echo-sdk. Wrote `docs/repos/*`, `docs/how-it-fits.md`, `docs/build-recipes.md`. Corrections: formulary datasets (drugs, labs, symptoms, diagnoses) are EMR partner-search data, not chat tools (earlier note was wrong); doot and scribesnap are the same service; Moolchand's booking returns a payment step from the hospital system. Still unfound: document indexing pipeline, prepaid flag, list-prescriptions.


## Process change after a wrong claim
The "matrix drops medication/lab datasets" gap was stated after reading only the consumer. Added rules 2a to 2d to `CLAUDE.md` (two-ended check, confidence labels, re-check on each read, claims-to-confirm list) and created `docs/claims-to-confirm.md`.

## 2026-10-28: freshness system
Added `docs/repo-versions.tsv` (commit each note was read at), `docs/repo-areas.tsv` (path to note-section map), `scripts/check-freshness.sh` (FRESH/STALE per repo, changed files grouped by affected note, `--bump`), `.claude/skills/refresh-map/SKILL.md`, and rule 2e in `CLAUDE.md`. Tested: all 8 repos fresh; an old commit shows STALE with mapped files; unreachable commit reports STALE; release-only changes are treated as fresh.

## 2026-10-29: Interakt agent integration, no inbound events (support case)
Customer moves only the agent to us, keeps Interakt. Symptom: console + Interakt webhook set, no events. Read doot (`app/api/webhooks.py`, `src/apis/views/whatsapp.py`, `src/services/events.py`, Interakt provider) and dev-console (`integration/`, `agents/views/integrations.py`). Doot answers 200 to Interakt in every drop case (unknown account, unbound or paused binding, agent not found, signature mismatch), so a drop is silent. Checked live with the user: URL matched, binding Active, "Message received" ticked, toggle on, no chat in Conversations. Interakt's webhook form has a mandatory secret that it always signs with. Result: a second integration with the same API key and an EMPTY webhook secret worked at once, so the first integration's stored secret did not verify (doot skips the check when the secret is empty). Not yet known: stored wrongly, or doot's check differs from Interakt's signing. Console cannot show or edit the stored secret ("stores no readable details"). Side effect: without a secret, anyone holding the webhook URL can post fake messages (the URL's uuid is the only guard).

Correction (same day): a third integration with Interakt's secret pasted via the Copy button worked, with signature checking on. So doot's Interakt signature check matches what Interakt sends (claim 9 now verified by a live test); the first integration's stored secret was simply wrong. Fix for the customer: create the integration fresh, paste the secret with Interakt's Copy button, bind the agent, paste the console's URL into Interakt. Console cannot show or edit a saved secret, so a wrong one needs a new integration (claim 10 still open).

## 2026-10-29: Interakt customer call (Reliance Foundation Hospital), still no inbound events
Own test account: works (secret copied from Interakt's Edit Configuration window, or left empty). Customer account: nothing reaches doot (developer found no inbound log lines for the integration, so Interakt never called us; credit banner "Service suspended" also showed on the customer workspace, unproven link). Customer facts from the call: Interakt account on "Haptik_Bot_Plan" (not Advanced/Enterprise), no Inbox available, number 91 8169630357, a second account 91 8355889059 under the same login, webhook toggle on, "Message received" ticked, old menu bot replies on the same number. Lessons: (1) Interakt's Developer Settings box labelled "Secret Key" is the API key; the webhook secret is only inside Edit Configuration. (2) Check the plan name first; incoming-message webhooks are documented for Advanced/Enterprise (docs conflict). (3) Unknown: whether a Haptik bot plan sends webhooks at all, and whether it fires while the Haptik agent handles the chat. Interakt/Haptik hosts were not reachable from the session, so public docs not read yet. Customer does not want Interakt support contacted.

Public-docs research (Interakt/Haptik, via the user's own chat, links in their message; confidence: stated in docs unless marked): "Haptik_Bot_Plan" is on no public page. Public plans: Starter, Growth, Advanced, Enterprise. Incoming-message webhook: Advanced/Enterprise per pricing and main webhook page (older pages say Growth/Advanced; docs conflict). Interakt's own AI agents live under Automation > WhatsApp AI Agents and run only when no existing automation matches. Not found: whether "Message received" fires while an agent answers, whether a webhook and an agent can share a number, per-number pause, any webhook delivery log, any message export API. Failure rule: 5 failures in 10 min disables the webhook, no retries. Next check (no outside contact): customer's Interakt "Change Plan" page, to see whether the plan lists webhooks.

## 2026-10-29: explain-codebase skill added
Copied unchanged from abinash811/agentic-setup (branch claude/affectionate-bell-qiftj0, commit 12d09bc, skills/explain-codebase: SKILL.md and template.html) into `.claude/skills/explain-codebase/`. Not yet run or rendered here. Suggested adaptations, not applied: map its confirmed/guess/unknown labels to our verified/partial/inference; start from `docs/` notes before reading code; treat the 8 connected repos as pre-approved; record the commit read.

## 2026-10-29: voice agent read (explain-codebase skill, first run)
Goal: inbound voice assistant, Indian languages, existing tools, handover to a human (phone, chat). Read matrix voice (router, ws, pipeline, providers, agent processor, config), dev-console voice schemas/models/integration stubs, synapse-sdk VoiceAgent (skimmed), echo-sdk transcription (skimmed), doot voice notes (skimmed), and searched all repos for handover. Result page: `docs/explainers/explain-voice-agent.html`. Exists: browser (WebRTC) and phone (Vobiz) calls, ElevenLabs STT/TTS, ten Indian-language codes, Haiku 4.5 pinned, tools/KBs/custom tools without cards, transcript saved. Missing: handover, caller-ID identity, Sarvam/Deepgram in matrix, per-agent voice prompt use. Corrections: matrix `voice_telephony_flow.md` describes mulaw 8 kHz; code asks Vobiz for L16 16 kHz (guide stale). Claim 6 upgraded to verified; claims 11 to 14 added. `check-freshness.sh` flagged dev-console stale (ABDM files only, not voice); note not re-read.

## 2026-10-29: voice agent decisions
Scope: inbound phone calls only, built on existing functionality, delivered as patches (no pushes to company repos). Proposal (not final): number-to-agent binding via dev-console's integration API (telephony channel is a stub today), secured matrix `/answer`, caller ID into the session and tool identity, `transfer_to_human` tool (Vobiz supports transfer per search summaries, pages not opened), call list in console. Console prototype approved by the user ("fine, design can be tweaked later"): `docs/prototypes/prototype-phone-agent.html`. Open: Vobiz forwarding/caller-ID behaviour and India number rules; whether live calls are in production. Everything behind a per-agent switch, default off; PR must list "not tested live".

## 2026-10-29: voice patch 1 (matrix) built
Authenticate the Vobiz answer webhook and audio socket: shared secret + signed per-session token, default off until `VOICE_TELEPHONY_SECRET` is set. 22 tests, 0 new failures vs clean main (14 failed + 4 errors already there). Patch in `patches/voice/matrix/`, based on matrix 2569ee4. Not pushed anywhere; not tested with real Vobiz. Setup note: matrix venv built with `uv sync --frozen --group dev`; run tests with `python -m pytest med_assist/tests` (async tests need `@pytest.mark.asyncio`, `pytest.ini` header is `[tool:pytest]`).

## 2026-10-29: voice patch 2 built (console + matrix)
dev-console: telephony channel + Vobiz provider (E.164 number as identity, migration 0004 choices only, matrix answer URL shown, 9 new tests, 17 pass). matrix (after patch 1): `POST /voice/answer/{integration_uuid}` resolves the bound agent from `integrations`/`product_integrations` (404 for unknown/unbound/paused/foreign), caller ID given to the agent as an unverified hint and never as tool identity, 50 new tests in total, 0 new failures vs clean main. Found while testing: the repo's own `test_api_telemetry` requires success/failure logs per endpoint (helper registered in `_OUTCOME_IN_HELPER`); the product-binding API does not check agent/workspace ownership (noted for reviewers). dev-console venv: `uv sync --frozen --no-install-package mysqlclient`, tests with `CURR_ENV=dev SECRETS='{}' python manage.py test integration`. Nothing pushed to company repos.

## 2026-10-29: voice patch 3 built (handover to a person)
Console: agent binding `config.handover` (staff number, hours, ring seconds). Matrix: `transfer_to_human` tool, `HandoverProcessor` (transfers after the agent has finished speaking), `/voice/transfer` and `/voice/transfer-result` routes, Vobiz Transfer API client; off unless the shared secret and Vobiz credentials are set. Read Vobiz's real docs this time: **the shell (curl) reaches www.vobiz.ai and `.md` versions of its pages even though the WebFetch tool cannot** (use `curl https://www.vobiz.ai/docs/<page>.md`, keep files in their own folder, read as text). Corrections to earlier notes: Vobiz transfer is now verified from its docs (was "partial, search summaries"); Vobiz documents a rejecting `<Hangup reason="rejected"/>` so patch 2b uses it instead of a 404; claim 16 resolved. Patch 1 now signs tokens with a purpose. Matrix: 730 passed, same 14 failed + 4 errors as clean main. Not run on a real call.

## 2026-10-29: voice patch 4 built (console pages for a phone number)
Dev-console: provider tile + create form for a phone number, number page with Answer URL, agent-only connect, "Hand over to a person" form (stored in the binding config), keep/remove rules so a WhatsApp-style save never wipes it. Found while building: patch 3a's new `handover` field would have shown as a bogus "Handover callback" box and been wiped on save because the binding form lists every config field; fixed in 3a (`_slots`) with tests. 49 integration tests pass without a database; real templates rendered with a bare base layout; pages looked at in a browser via a harness that renders the real templates (Tailwind runtime build, since the compiled stylesheet is a tracked build file the Docker build regenerates). Screenshots saved under `patches/voice/dev-console/screenshots/`. Test call button and Calls tab not included. Nothing pushed to company repos.

## 2026-10-29: voice patch 5 built (Calls tab)
Matrix 0004: calls are recorded as conversations with a masked-caller summary (duration, how it ended, handover outcome, tools). Console 0004: Setup | Calls tabs, table with outcome pills and totals, `console_index` always promotes `call` and `integration_uuid`. Matrix 747 passed (same 14 failed + 4 errors as clean main); console 59 pass without a database. Database tests (`list_calls`, ingest) are written but could not run in the sandbox (no MySQL/Postgres). Presenter bug caught by looking at the render: a call with no summary was labelled "Answered by agent"; now "Not recorded". Both series verified with `git am --3way` on clean main. Nothing pushed to company repos.

## 2026-10-29: voice patch 6 built (Test this number card)
Console only. Chose a readiness card with a tap-to-call link over a button that places a call (outbound calling and the browser voice path were both out of scope or a different path). 62 integration tests pass without a database; two breakages caught; rendered and looked at. Nothing pushed to company repos.

## 2026-10-30: corrections (WhatsApp richer messages)
Earlier note said carousel and Flow answers were "not found". After reading more: doot `src/services/send.py` already builds template carousels, and `interakt_tp_provider.parse_webhook` already parses Flow replies (`nfm_reply`). Bridge still has no caller for the Flow, link and location senders (partial). Doc `docs/whatsapp-richer-messages.md` updated. Claim 21 reworded below.

## 2026-10-30: carousel patch built (doot)
Cards the agent marks horizontal, with images, now go out as Meta's interactive media carousel on `interakt_tp` numbers; everything else and any 4xx falls back to the list. 121 doot tests pass (19 new), six breakages caught. Read Meta's carousel page via curl (WebFetch/search could not): format confirmed, so claim 23 is now verified for Meta; Interakt pass-through still unconfirmed. Not sent on a real number. Nothing pushed to the company repo.
