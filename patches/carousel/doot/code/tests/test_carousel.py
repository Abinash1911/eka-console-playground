"""Cards shown as a WhatsApp interactive media carousel, and the fallbacks to a list."""
import httpx
import pytest

from app.bridge import choices as ch
from app.bridge.medassist import presenter
from app.bridge.medassist.bridge import MedassistBridge
from app.bridge.medassist.elicitation import (
    PendingCard,
    PendingElicitation,
    pending_from_dict,
    pending_to_dict,
)
from app.services.clients.medassist_client import MedassistResponse, _parse_elicitation_data
from app.services.whatsapp.providers.base_provider import WhatsAppProviderBase
from app.services.whatsapp.providers.interakt_tp_provider import InteraktTPWhatsAppProvider
from tests.fakes import AGENT_ID, FakeProvider, tap, text
from tests.test_bridge_phase2 import doctor_card
from tests.test_provider_flows import recording

IMG = "https://cdn.example/{}.jpg"


def raw_cards(n=3, **over):
    return [
        {
            "card_id": f"c{i}", "title": f"Package {i}", "img": IMG.format(i),
            "description": f"Detail {i}", "primary_cta": {"cta_id": "pick", "title": "Book now", "tool_result": {"pick": i}},
            **over,
        }
        for i in range(n)
    ]


def pending(cards=None, orientation="horizontal"):
    cards = raw_cards() if cards is None else cards
    return PendingElicitation(
        message_id="m1", tool_id="t1", tool_name="pick_package", component="card", status="progress",
        cards=[PendingCard(c["card_id"], c["title"], (c.get("primary_cta") or {}).get("tool_result")) for c in cards],
        input_data={"text": "Choose a package", "cards": cards}, schema_fields=["pick"], orientation=orientation,
    )


class CarouselProvider(FakeProvider):
    supports_carousel = True

    def __init__(self, error: Exception | None = None):
        super().__init__()
        self.error = error

    async def send_carousel(self, to, body_text, cards):
        if self.error:
            raise self.error
        self.sent.append(("carousel", {"to": to, "body": body_text, "cards": cards}))


def refusal(status):
    request = httpx.Request("POST", "https://amped.test/p/messages")
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(status, text="bad", request=request))


def bridge_for(provider, session_manager, client):
    return MedassistBridge(
        whatsapp=provider, session_manager=session_manager, bot_key="medassist",
        medassist_client=client, agent_id=AGENT_ID,
    )


# -- building the message ----------------------------------------------------

def test_card_text_is_bold_title_then_detail_within_160():
    assert ch.card_text(ch.Slide("https://i/1.jpg", "Full body check", "Blood, urine, ECG")) == "*Full body check*\nBlood, urine, ECG"
    assert ch.card_text(ch.Slide("https://i/1.jpg", "Only title")) == "*Only title*"
    long = ch.card_text(ch.Slide("https://i/1.jpg", "T" * 300, "D" * 300))
    assert ch._width(long) <= ch.CARD_TEXT_MAX


def test_cards_follow_metas_shape_and_buttons_carry_the_list_row_ids():
    slides = [ch.Slide(IMG.format(i), f"P{i}", "d", "A very long button label here") for i in range(2)]
    cards = ch.carousel_cards(slides, "abc123")
    assert [c["card_index"] for c in cards] == [0, 1]
    assert cards[1]["header"] == {"type": "image", "image": {"link": IMG.format(1)}}
    button = cards[1]["action"]["buttons"][0]["quick_reply"]
    assert button["id"] == "abc123.1"
    assert ch.parse_row_id(button["id"]) == ch.Tap("abc123", "", 1)
    assert ch._width(button["title"]) <= ch.BUTTON_MAX


@pytest.mark.parametrize("count, ok", [(1, False), (2, True), (10, True), (11, False)])
def test_a_carousel_needs_two_to_ten_cards(count, ok):
    slides = [ch.Slide(IMG.format(i), f"P{i}") for i in range(count)]
    assert ch.fits_carousel(slides, "Pick") is ok


def test_a_carousel_needs_https_images_and_a_body_that_fits():
    good = [ch.Slide(IMG.format(i), f"P{i}") for i in range(2)]
    assert not ch.fits_carousel([ch.Slide("http://x/1.jpg", "P"), good[1]], "Pick")
    assert not ch.fits_carousel(good, "x" * (ch.CAROUSEL_BODY_MAX + 1))


async def test_interakt_tp_sends_the_carousel_as_an_interactive_message():
    provider = InteraktTPWhatsAppProvider(isv_token="t", waba_id="w", phone_number_id="p", amped_url="https://amped.test")
    bodies = recording(provider)
    cards = ch.carousel_cards([ch.Slide(IMG.format(i), f"P{i}") for i in range(2)], "abc123")
    await provider.send_carousel("+918218467229", "Choose a package", cards)
    body = bodies[-1]
    assert body["to"] == "918218467229" and body["type"] == "interactive"
    assert body["interactive"] == {"type": "carousel", "body": {"text": "Choose a package"}, "action": {"cards": cards}}
    assert provider.supports_carousel and not WhatsAppProviderBase.supports_carousel


# -- what the agent asked for ------------------------------------------------

def test_the_agent_layout_choice_is_read_and_survives_the_session_store():
    data = {
        "tool_id": "t1", "tool_name": "pick_package",
        "details": {"component": "card", "status": "progress", "input": {"cards": raw_cards()}, "_meta": {"orientation": "horizontal"}},
    }
    parsed = _parse_elicitation_data("m1", data).pending_elicitation
    assert parsed.orientation == "horizontal"
    assert pending_from_dict(pending_to_dict(parsed)).orientation == "horizontal"
    assert pending_from_dict({k: v for k, v in pending_to_dict(parsed).items() if k != "orientation"}).orientation == ""


@pytest.mark.parametrize("name, p", [
    ("vertical layout", pending(orientation="")),
    ("a card without an image", pending(raw_cards(3, img="") )),
])
def test_cards_stay_a_list_unless_horizontal_with_images(name, p):
    assert presenter.current_list(p).slides == ()


def test_horizontal_cards_with_images_become_slides():
    slides = presenter.current_list(pending()).slides
    assert [(s.title, s.detail, s.button) for s in slides] == [(f"Package {i}", f"Detail {i}", "Book now") for i in range(3)]


# -- the bridge --------------------------------------------------------------

async def reply_with(bridge, client, seed, p):
    await seed()
    client.chat_responses.append(MedassistResponse(text="Choose a package", pending_elicitation=p))
    await bridge.run(text("packages"))


async def test_horizontal_cards_go_out_as_a_carousel_and_a_tap_picks_the_card(session_manager, client, seed):
    provider = CarouselProvider()
    bridge = bridge_for(provider, session_manager, client)
    await reply_with(bridge, client, seed, pending())
    assert [k for k, _ in provider.sent] == ["carousel"]
    sent = provider.of("carousel")[0]
    assert sent["body"] == "Choose a package"
    button_id = sent["cards"][1]["action"]["buttons"][0]["quick_reply"]["id"]

    client.callback_responses.append(MedassistResponse(text="Booked"))
    await bridge.run(tap(button_id, "Book now"))
    assert client.callback_params == [{"tool_result": {"pick": 1}}]


@pytest.mark.parametrize("name, make_provider, p", [
    ("provider cannot send one", lambda: FakeProvider(), pending()),
    ("vertical layout", lambda: CarouselProvider(), pending(orientation="")),
    ("only one card", lambda: CarouselProvider(), pending(raw_cards(1))),
    ("more than ten cards", lambda: CarouselProvider(), pending(raw_cards(11))),
    ("WhatsApp rejects it", lambda: CarouselProvider(error=refusal(400)), pending()),
])
async def test_otherwise_the_cards_go_out_as_the_list_they_were_before(name, make_provider, p, session_manager, client, seed):
    provider = make_provider()
    await reply_with(bridge_for(provider, session_manager, client), client, seed, p)
    assert provider.of("carousel") == []
    assert len(provider.of("list")) == 1


async def test_a_server_error_is_not_swallowed(session_manager, client, seed):
    provider = CarouselProvider(error=refusal(503))
    with pytest.raises(httpx.HTTPStatusError):
        await reply_with(bridge_for(provider, session_manager, client), client, seed, pending())
    assert provider.of("list") == []


# -- link carousel -----------------------------------------------------------

def test_a_link_carousel_has_one_url_button_per_card():
    slides = [ch.Slide(IMG.format(i), f"P{i}", "d", "Know more", url=f"https://clinic.example/p{i}") for i in range(2)]
    assert ch.is_link_carousel(slides)
    card = ch.carousel_cards(slides, "abc123")[1]
    assert card["type"] == "cta_url" and card["header"]["image"]["link"] == IMG.format(1)
    assert card["action"] == {"name": "cta_url", "parameters": {"display_text": "Know more", "url": "https://clinic.example/p1"}}


def test_one_card_without_a_link_makes_every_card_a_quick_reply():
    slides = [ch.Slide(IMG.format(0), "P0", url="https://clinic.example/p0"), ch.Slide(IMG.format(1), "P1")]
    assert not ch.is_link_carousel(slides)
    assert [c["action"]["buttons"][0]["quick_reply"]["id"] for c in ch.carousel_cards(slides, "abc123")] == ["abc123.0", "abc123.1"]
    http = [ch.Slide(IMG.format(i), f"P{i}", url="http://clinic.example") for i in range(2)]
    assert not ch.is_link_carousel(http)


def test_cards_with_only_a_link_become_a_link_carousel_and_a_tool_cta_stays_a_pick():
    links = [{**c, "primary_cta": {"cta_id": "l", "title": "Know more", "link": f"https://clinic.example/{c['card_id']}"}} for c in raw_cards()]
    assert all(s.url for s in presenter.current_list(pending(links)).slides)
    both = [{**c, "primary_cta": {**c["primary_cta"], "link": "https://clinic.example/x"}} for c in raw_cards()]
    assert not any(s.url for s in presenter.current_list(pending(both)).slides)


# -- doctors as a carousel ---------------------------------------------------

def doctors(images=True, n=2):
    ids = [f"d{i}" for i in range(n)]
    details = {
        d: {"name": f"Dr. {d}", "specialty": "Cardiology", "experience": f"{i + 9} yrs",
            "hospitals": [{"hospital_id": f"h{i}", "name": "Moolchand"}],
            **({"profile_pic": f"https://cdn.example/{d}.jpg"} if images else {})}
        for i, d in enumerate(ids)
    }
    return doctor_card([{"doctor_id": d, "availability": []} for d in ids], details, "Cardiologists:")


@pytest.fixture
def doctor_carousel_on(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DOCTOR_CAROUSEL_ENABLED", "true")
    get_settings.cache_clear()


async def test_doctors_go_out_as_a_carousel_and_a_tap_selects_the_doctor(doctor_carousel_on, session_manager, client, seed):
    provider = CarouselProvider()
    bridge = bridge_for(provider, session_manager, client)
    await seed()
    client.chat_responses.append(doctors())
    await bridge.run(text("cardiologist"))
    sent = provider.of("carousel")[0]
    assert provider.of("list") == []
    assert sent["body"] == "Cardiologists:"
    assert sent["cards"][1]["body"]["text"] == "*Dr. d1*\nCardiology · 10 yrs"
    assert sent["cards"][1]["header"]["image"]["link"] == "https://cdn.example/d1.jpg"
    assert sent["cards"][1]["action"]["buttons"][0]["quick_reply"]["title"] == "Book appointment"

    await bridge.run(tap(sent["cards"][1]["action"]["buttons"][0]["quick_reply"]["id"], "Select", message_id="w2"))
    assert client.chat_texts[-1] == "[DOCTOR SELECTED: Dr. d1, doctor_id=d1, hospital_id=h1]"


async def test_doctors_stay_a_list_when_the_switch_is_off(session_manager, client, seed):
    provider = CarouselProvider()
    await seed()
    client.chat_responses.append(doctors())
    await bridge_for(provider, session_manager, client).run(text("cardiologist"))
    assert provider.of("carousel") == [] and len(provider.of("list")) == 1


async def test_doctors_stay_a_list_when_any_doctor_has_no_picture(doctor_carousel_on, session_manager, client, seed):
    provider = CarouselProvider()
    response = doctors()
    response.pending_elicitation.doctor_options[1].image = ""
    await seed()
    client.chat_responses.append(response)
    await bridge_for(provider, session_manager, client).run(text("cardiologist"))
    assert provider.of("carousel") == [] and len(provider.of("list")) == 1


def test_a_doctors_profile_picture_is_kept_and_survives_the_session_store():
    option = doctors().pending_elicitation.doctor_options[0]
    assert option.image == "https://cdn.example/d0.jpg"
    stored = pending_from_dict(pending_to_dict(doctors().pending_elicitation))
    assert stored.doctor_options[0].image == "https://cdn.example/d0.jpg"
