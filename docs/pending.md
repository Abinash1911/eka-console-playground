# Pending to-do

Open work, newest decisions first. Move an item to `docs/build-log.md` when done.

## Voice agent (inbound phone)
- [ ] **Text-the-clinic fallback:** when nobody answers a handover, the agent takes name, number and reason, and sends them to the clinic by text/WhatsApp. Needs a sending route (check what doot/matrix can send first). Not started.
- [ ] Reviewer summary of all voice patches (one page, for developers).
- [ ] One real test call on Vobiz (claims 17, 19 in `docs/claims-to-confirm.md`).
- [ ] Record browser (WebRTC) voice sessions in Conversations (same gap as phone calls had).
- [ ] Hindi/regional recorded hand-off apology (Vobiz Speak has no Hindi).
- [ ] Run database tests (`python manage.py test console_index`) where MySQL/Postgres exist.

## Harness
- [ ] Weekly refresh of the map (`refresh-map` skill): blocked on GitHub access for scheduled runs.
- [ ] Skills proposed, not built: patch packaging, browser check, PR watcher.

## Reliance (WhatsApp on Interakt)
- [ ] Waiting on the customer: Interakt plan and Haptik details; their Interakt still sends no webhook.

## WhatsApp richer messages
- [ ] Decide which to build first (see `docs/whatsapp-richer-messages.md`): link button + location (small), Flows (forms), carousel, payments. Needs answer on claims 21 and 22.

## Care Loop prototype (Healthcare OS brainstorm)
- [ ] **On hold (paused 2026-11-04), per user request.** HTML click-through prototypes, not committed, saved under `docs/prototypes/`: `care-loop-prototype.html` (console: Meena's journey — one continuous 20-step patient story, Workflows tile grid, Today's queue, Patient record, Scribe consult, Clinic operations; onecare-inspired safety-check/bill cards and EMR pills added to the WhatsApp phone) and `care-loop-flows.html` (simpler two-flow onecare-style hub, superseded by the journey view but kept). Open asks when we resume: (1) 2-column layout — user asked, got interrupted, scope not yet defined; (2) wording/order review of the 20-step journey; (3) this sits alongside, not in place of, the WhatsApp agent + Eka Scribe discussion below — the two haven't been reconciled.

## Agent and Messenger (same WhatsApp number, both products)
- [ ] **On hold (paused 2026-11-05), per user request.** Goal: let one WhatsApp number run the Agent (live chat) and Messenger (notifications) at once — today the console forces either/or. Full design confirmed **verified**, both ends read, across two repos:
  - dev-console `integration/models.py`: `ProductIntegration` unique constraint is `fields=["integration"]` (one product per number, by design, "so inbound routing is unambiguous"). Widen to `(integration, product)` — safe, no backfill.
  - dev-console `integration/api/resolve.py`: `_binding_of` returns one binding (`.first() is exact`); doot calls this. Needs to return a list.
  - dev-console `integration/views.py`: `bind_product`/`toggle_product`/`unbind_product` all `.filter(integration=integ).first()` — becomes per-product filtering.
  - dev-console `templates/integrations/detail.html`: one radio-style product picker, locked once bound ("disconnect first to switch") — becomes two independent cards (Agent, Messenger), each with its own Connect/Pause/Disconnect.
  - doot `src/apis/views/whatsapp.py::inbound()`: already fans out non-agent products via `dispatch.spawn`; needs to loop a list of bindings instead of one — mechanism exists, just needs to stop assuming exactly one.
  - Logged as claim #26 in `docs/claims-to-confirm.md`.
  - Not started. Resume by building the patch (dev-console + doot, private copies under `patches/`, not pushed) once the user says go.

## WhatsApp agent + Eka Scribe (new project)
- [ ] **Discussion pending (paused 2026-11-04).** Context is in `projects/agents-scribe/`. Resume with: (1) the patient scenario (Meena) and the gaps mapped to it, steps 6 and 7 being the biggest; (2) the six open questions in `gap-map.md`, starting with where WhatsApp-collected readings and intake live in Scribe; (3) read the Scribe repos before any build. Extra use-case ideas not in the deck (missed dose, high-reading alert, refill, meal photo, family booking, yearly eye/foot checks, dose-change check-in) are chat-only so far.
