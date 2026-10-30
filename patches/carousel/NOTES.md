# WhatsApp carousel (doot)

Patches: `patches/carousel/doot/0001-*.patch` (carousel) and `0002-*.patch` (link carousel, doctors), apply in order on base doot `36e7eeb` (main, 2026-10-30). Readable copies in `doot/code/`.

## What it does
- An agent card list with `_meta.orientation = "horizontal"` and an `img` on every card is sent as Meta's interactive media carousel (2 to 10 cards, image, bold title + detail, one quick-reply button). Same layout switch the web widget uses. Meta format read from [Meta's page](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-media-carousel-messages) (fetched with curl).
- Card button ids are the list row ids (`{token}.{n}`), so a tap goes through the existing card path with no new state.
- Provider flag `supports_carousel` (true only for `interakt_tp`); other providers keep the list.
- Falls back to the list when: vertical layout, no https image on a card, fewer than 2 or more than 10 cards, provider cannot, or WhatsApp answers 4xx. A 5xx is raised, as for lists.
- Files: `choices.py`, `base.py`, `base_provider.py`, `interakt_tp_provider.py`, `presenter.py`, `medassist/bridge.py`, `medassist/elicitation.py` (stores `orientation`), `medassist_client.py`.

## Checked
- 128 tests pass (102 existing + 26 new in `tests/test_carousel.py`; 0001 alone has 121). Both patches apply on clean `36e7eeb`.
- Twelve deliberate breakages each fail a test (5xx swallowed, provider flag ignored, orientation ignored, one card allowed, button id not a row id, carry on after sending, doctor switch ignored, http links allowed, mixed links allowed, a link beating a tool pick, picture not read). Removing the doctor-picture check changes nothing, because the send step already refuses a card without an image.

## Not tested
- A real send. Unknown: whether Interakt's proxy (amped-express) passes `interactive.type: carousel` through; the exact webhook shape of a carousel quick-reply tap (code handles both `interactive.button_reply` and `button` payloads); image links must be public https and fetchable by WhatsApp.
- Echo/matrix: whether any agent tool sets `_meta.orientation` and `img` on cards for WhatsApp (matrix suppresses card elicitation for `wa`/`whatsapp`, per `docs/repos/doot.md`, and doot renders its own). Needs a developer to confirm.

## For reviewers to decide
- Gate on `orientation == "horizontal"` (mirrors the web widget) vs. any card list with images.
- Card text is `*title*\n` + the first of description, tags, tags_text, banner_text, clipped to 160 characters.
- Button label is the card's `primary_cta.title`, else "Select" (20 characters).

## Patch 0002: link carousel and doctors
- **Link carousel:** if every card's primary CTA has an `https` `link` and no `tool_result`, each card gets a URL button (opens the page, nothing returns to the agent). Meta needs one button type on all cards, so a single card without a link makes the whole carousel quick-reply.
- **Doctors:** the doctor step of a `doctor_card` goes out as a carousel (picture from `profile_pic`, bold name, specialty · experience · qualification · fee, button "Select"). A tap selects the doctor like a list tap; dates and slots stay lists. Behind `DOCTOR_CAROUSEL_ENABLED` (default off), only when every doctor has a picture, 2 to 10 doctors, and the provider can; otherwise today's list.
- A doctor card cannot also carry a profile link: Meta allows either one URL button or quick replies per card, not both. The link could go in the card text instead (not done).
- Not tested: a real send; whether echo/matrix doctor details carry `profile_pic` (the web widget's type has it as optional); how a real doctor photo crops in the card.
- Decision for reviewers: the flag is a global env switch; per-agent control would need a console setting.
