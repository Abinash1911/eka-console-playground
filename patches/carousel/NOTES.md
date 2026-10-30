# WhatsApp carousel (doot)

Patch: `patches/carousel/doot/0001-*.patch`, base doot `36e7eeb` (main, 2026-10-30). Readable copies in `doot/code/`.

## What it does
- An agent card list with `_meta.orientation = "horizontal"` and an `img` on every card is sent as Meta's interactive media carousel (2 to 10 cards, image, bold title + detail, one quick-reply button). Same layout switch the web widget uses. Meta format read from [Meta's page](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-media-carousel-messages) (fetched with curl).
- Card button ids are the list row ids (`{token}.{n}`), so a tap goes through the existing card path with no new state.
- Provider flag `supports_carousel` (true only for `interakt_tp`); other providers keep the list.
- Falls back to the list when: vertical layout, no https image on a card, fewer than 2 or more than 10 cards, provider cannot, or WhatsApp answers 4xx. A 5xx is raised, as for lists.
- Files: `choices.py`, `base.py`, `base_provider.py`, `interakt_tp_provider.py`, `presenter.py`, `medassist/bridge.py`, `medassist/elicitation.py` (stores `orientation`), `medassist_client.py`.

## Checked
- 121 tests pass (102 existing + 19 new in `tests/test_carousel.py`). Patch applies on clean `36e7eeb`.
- Six deliberate breakages (5xx swallowed, provider flag ignored, orientation ignored, one card allowed, button id not a row id, carry on after sending) each fail a test.

## Not tested
- A real send. Unknown: whether Interakt's proxy (amped-express) passes `interactive.type: carousel` through; the exact webhook shape of a carousel quick-reply tap (code handles both `interactive.button_reply` and `button` payloads); image links must be public https and fetchable by WhatsApp.
- Echo/matrix: whether any agent tool sets `_meta.orientation` and `img` on cards for WhatsApp (matrix suppresses card elicitation for `wa`/`whatsapp`, per `docs/repos/doot.md`, and doot renders its own). Needs a developer to confirm.
- The existing CTA-URL-only carousel (links instead of replies) is not built.

## For reviewers to decide
- Gate on `orientation == "horizontal"` (mirrors the web widget) vs. any card list with images.
- Card text is `*title*\n` + the first of description, tags, tags_text, banner_text, clipped to 160 characters.
- Button label is the card's `primary_cta.title`, else "Select" (20 characters).
