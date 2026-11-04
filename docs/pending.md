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

## WhatsApp agent + Eka Scribe (new project)
- [ ] **Discussion pending (paused 2026-11-04).** Context is in `projects/agents-scribe/`. Resume with: (1) the patient scenario (Meena) and the gaps mapped to it, steps 6 and 7 being the biggest; (2) the six open questions in `gap-map.md`, starting with where WhatsApp-collected readings and intake live in Scribe; (3) read the Scribe repos before any build. Extra use-case ideas not in the deck (missed dose, high-reading alert, refill, meal photo, family booking, yearly eye/foot checks, dose-change check-in) are chat-only so far.
