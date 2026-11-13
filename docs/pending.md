# Pending to-do

Open work, newest decisions first. Move an item to `docs/build-log.md` when done.

## Header banner (was "ribbon") (P0)
- [ ] **P0: get the dev-console PR up.** Branch `feat/ribbon-settings` (one commit, "Banner text in the agent's General tab", rebased on main `862976e`, 5 tests pass) is ready locally, but the push got HTTP 403. Either an org admin installs the Claude GitHub App on `eka-care/dev-console` (https://github.com/apps/claude/installations/select_target), or someone with access applies `patches/header-banner/dev-console/*.patch` and pushes. PR text: `patches/header-banner/PR-DESCRIPTIONS.md`. Ask who reviews dev-console agents (`dotdotcare`, `moon_garg` touched them last).
- [ ] P0: re-request review on synapse-sdk PR https://github.com/eka-care/synapse-sdk/pull/218 (simplified to `theme.banner` per Geethanjali's review; her "changes requested" is still on record until she re-reviews). I did not reply on GitHub.
- [ ] Open the Eka Console Prototype artifact and check the Banner box and the live banner (edits were not opened in a browser). Old unused ribbon helper code is still inside the artifact (harmless, unused).
- [ ] Welcome card patch (`patches/welcome-card/`) is built, not raised: decide whether and when. It applies together with the banner patches (`--3way`).
- [ ] Product follow-ups that Geethanjali's review dropped on purpose: dismissable, icon (upload), colours. If wanted again, they need a backend-friendly design first.
- [ ] Open questions for developers: claims 26 and 27 in `docs/claims-to-confirm.md`. The reward (counting messages, paying out) needs a backend; nothing built.

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
