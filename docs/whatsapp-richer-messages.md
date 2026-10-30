# Richer WhatsApp messages: what exists, what is missing, effort

Read at doot `36e7eeb` (fresh at 2026-10-30). Labels: **verified** (code read), **partial** (search only), **inference** (reasoned). Effort is a developer-days guess, **inference**, for one developer who knows the repos; it excludes review and Meta/BSP approvals.

## What the code does today
Files read: doot `app/services/whatsapp/providers/base_provider.py`, `meta_provider.py`, `app/bridge/medassist/presenter.py`; file list of `bridge/medassist/` and `providers/`.

| Capability | Provider layer (doot) | Used by the bridge | Label |
|---|---|---|---|
| Text, reply buttons (max 3), lists (max 10 rows), documents, templates | all providers | yes (pills, cards, doctor picker use lists) | verified |
| Typing indicator, mark as read | base no-op; overridden in at least one provider | search found no call in the bridge besides the "thinking" acknowledgement | partial |
| Image, video, sticker, link button (CTA URL), location request, **WhatsApp Flow (form)** | defined in `base_provider.py`; only `interakt_tp` overrides them; every other provider falls back to plain text (logged) | **no caller found** (search for `send_flow`, `send_cta_url`, `send_location_request`, `send_image` hits only the two provider files) | partial: code search only, the bridge file `bridge.py` (73 KB) was not read in full |
| Carousel, address message, order/payment message, reactions, product catalog | not found | not found | partial (search only) |
| Reading a Flow's submitted answers (`nfm_reply`) | not found | not found | partial |

So: forms, link buttons and location requests are **built at the sending layer but not wired**: the agent has no way to ask for them, and nothing reads a form's answers back. They work only on `interakt_tp` accounts.

Matrix/synapse side: the elicitation types the agent can use are pills, multi, card, doctor_card, mobile_number, otp, email_address, media_card (from `docs/repos/doot.md` and synapse-sdk `CLAUDE.md`). No form or carousel type. **verified** for doot, **partial** for matrix/echo.

## What WhatsApp offers (not checked against Meta today)
Third-party docs only ([360dialog interactive messages](https://docs.360dialog.com/partner/messaging/message-types/interactive-messages), [payments India](https://docs.360dialog.com/partner/commerce-and-payments/payments-india-only/receive-whatsapp-payments-via-payments-gateway)); no Meta changelog found. Confirm at developers.facebook.com.
- **Flows (forms):** multi-screen forms inside WhatsApp. Interakt describes them but the page lists webhook delivery of answers as "coming soon" ([Interakt explainer](https://interakt.shop/?p=50032)). Biggest risk for us.
- **Media carousel:** 2 to 10 cards, same button type on every card. Sent as a template. Interakt support unconfirmed.
- **Address message:** India and Singapore only.
- **Order details + payment status (India):** pay inside chat, two messages plus a webhook.
- **Link button, location request, reactions, product catalog messages.**

## Where to add it (follows doot's own table in `docs/repos/doot.md`)
1. New elicitation type: `app/bridge/medassist/elicitation.py` + `presenter.py`, plus a matching component in matrix/echo (the tool that asks) and `SYNAPSE_COMPONENTS` in synapse-sdk if the web widget should show it too.
2. Provider method: already defined for flows, link, location, image; carousel, address, order are new methods in `base_provider.py` with text fallback, overridden per provider.
3. Inbound: read the reply type (`nfm_reply` for Flows, location, order status) in each provider's `parse_webhook`.
4. Console: usually nothing, except Flow ids/template names in the integration config.

## Effort (inference)
| Item | Days | Notes |
|---|---|---|
| Link button + location request wired to a tool | 2 to 3 | methods exist; add tool + elicitation type + inbound location (location inbound already handled for payloads) |
| Flow (form) end to end | 6 to 10 | wire send, parse answers, tool, tests; blocked on whether the BSP delivers answers by webhook |
| Carousel (template) | 4 to 6 | new provider method, template config, Interakt support check |
| Payment link/order message | 8 to 15 | gateway, webhooks, compliance; no payment code found in connected repos (`capability-index.md` line 47) |
| Typing indicator / read receipts everywhere | 1 | small |

## Questions for a developer (go to `claims-to-confirm.md`)
- Are the unused provider methods used anywhere outside doot (matrix notifications)?
- Does Interakt (not `interakt_tp`) support Flows and carousels at all, and deliver Flow answers by webhook?
- Which accounts use `interakt_tp` today?
