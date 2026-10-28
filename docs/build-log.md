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
