"""What a pending elicitation shows as a WhatsApp list, and what a tap on it picks.

pills/multi and card are a single list. A doctor_card is up to three steps — doctor,
date, slot — and the current one follows from what ``doctor_accumulated`` holds. The
earlier steps' lists stay answerable, so a tap on an older doctor or date list goes back.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Optional

from app.bridge.choices import Choice, Slide, dates_row, from_label, list_token
from app.bridge.medassist.elicitation import (
    DoctorOption,
    PendingElicitation,
    format_date,
    time_label,
)
from app.core.config import get_settings

OPTION, DOCTOR, DATE, SLOT = "option", "doctor", "date", "slot"


@dataclass(frozen=True)
class ChoiceList:
    step: str
    choices: list[Choice]
    items: list[Any]  # what each choice stands for: option dict, card, doctor, date, slot time
    token: str
    button: str
    body: str  # used when the bridge moves to this list on its own
    extra_rows: tuple = ()
    slides: tuple = ()  # cards with an image, for a provider that can show them as a carousel


# ---------------------------------------------------------------------------
# doctor_card state
# ---------------------------------------------------------------------------

def selected_doctor(p: PendingElicitation) -> Optional[DoctorOption]:
    doctor_id = p.doctor_accumulated.get("doctor_id")
    if doctor_id:
        return next((d for d in p.doctor_options if d.doctor_id == doctor_id), None)
    return p.doctor_options[0] if len(p.doctor_options) == 1 else None


def open_dates(doctor: DoctorOption) -> list[dict]:
    """Dates worth offering: not loaded yet, or loaded with free slots."""
    return [d for d in doctor.dates if d["slots"] is None or d["slots"]]


def slots_on(doctor: DoctorOption, date: Optional[str]) -> list[str]:
    return next((d["slots"] or [] for d in doctor.dates if d["date"] == date), [])


def pick_doctor(p: PendingElicitation, doctor: DoctorOption) -> PendingElicitation:
    """Select ``doctor``, landing on the date their card already loaded slots for."""
    acc = {"doctor_id": doctor.doctor_id, "hospital_id": doctor.hospital_id}
    loaded = [d["date"] for d in doctor.dates if d["slots"]]
    if slots_on(doctor, doctor.preferred_date):
        acc["preferred_date"] = doctor.preferred_date
    elif len(open_dates(doctor)) == 1 and loaded:
        acc["preferred_date"] = loaded[0]
    return replace(p, doctor_accumulated=acc, page_offset=0)


def pick_date(p: PendingElicitation, date: str) -> PendingElicitation:
    return replace(p, doctor_accumulated={**p.doctor_accumulated, "preferred_date": date}, page_offset=0)


def back_to_dates(p: PendingElicitation) -> PendingElicitation:
    acc = {k: v for k, v in p.doctor_accumulated.items() if k != "preferred_date"}
    return replace(p, doctor_accumulated=acc, page_offset=0)


def normalize(p: PendingElicitation) -> PendingElicitation:
    """Pre-pick what a fresh doctor_card already settled: its only doctor, and the date
    it loaded slots for — so a card fetched for a tapped date opens on that date's slots."""
    if p.component != "doctor_card" or p.doctor_accumulated:
        return p
    doctor = selected_doctor(p)
    return pick_doctor(p, doctor) if doctor else p


def doctor_step(p: PendingElicitation) -> Optional[str]:
    doctor = selected_doctor(p)
    if doctor is None:
        return DOCTOR if p.doctor_options else None
    if slots_on(doctor, p.doctor_accumulated.get("preferred_date")):
        return SLOT
    return DATE if open_dates(doctor) else None


def ask_date_text(p: PendingElicitation) -> str:
    """For a doctor with nothing to pick from: ask for a date to check."""
    doctor = selected_doctor(p)
    if doctor is None:
        return "Please share your preferred date (e.g. 12 Oct) and I'll check available slots."
    return (
        f"There are no open slots for {doctor.name} in the next few days. "
        "Type a date (e.g. 12 Oct) and I'll check."
    )


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def choice_lists(p: PendingElicitation) -> list[ChoiceList]:
    """Every list this pending can answer, earliest step first."""
    if p.component in ("pills", "multi") and p.options:
        return [_options_list(p)]
    if p.component == "card" and p.cards:
        return [_cards_list(p)]
    if p.component != "doctor_card":
        return []

    lists = [_doctors_list(p)] if len(p.doctor_options) > 1 else []
    doctor = selected_doctor(p)
    if doctor and open_dates(doctor):
        lists.append(_dates_list(p, doctor))
    date = p.doctor_accumulated.get("preferred_date")
    if doctor and slots_on(doctor, date):
        lists.append(_slots_list(p, doctor, date))
    return lists


def current_list(p: PendingElicitation) -> Optional[ChoiceList]:
    """The list to show now, or None when there is nothing to pick from."""
    lists = choice_lists(p)
    if p.component != "doctor_card":
        return lists[-1] if lists else None
    step = doctor_step(p)
    return next((lst for lst in lists if lst.step == step), None)


def find_list(p: PendingElicitation, token: str) -> Optional[ChoiceList]:
    return next((lst for lst in choice_lists(p) if lst.token == token), None)


def _options_list(p: PendingElicitation) -> ChoiceList:
    return ChoiceList(
        step=OPTION,
        choices=[
            from_label(o.get("label") or o.get("value", ""), o.get("description", ""))
            for o in p.options
        ],
        items=p.options,
        token=list_token(p.component, p.message_id, p.tool_id, *(o.get("value", "") for o in p.options)),
        button=p.input_data.get("button") or "View options",
        body=p.input_data.get("text", ""),
    )


def _cards_list(p: PendingElicitation) -> ChoiceList:
    raw = {c.get("card_id"): c for c in p.input_data.get("cards", [])}

    def subtext(card_id: str) -> str:
        card = raw.get(card_id) or {}
        return str(card.get("description") or card.get("tags_text") or card.get("banner_text") or "")

    return ChoiceList(
        step=OPTION,
        slides=_slides(p, raw),
        choices=[from_label(c.title, subtext(c.card_id)) for c in p.cards],
        items=p.cards,
        token=list_token(p.component, p.message_id, p.tool_id, *(c.card_id for c in p.cards)),
        button=p.input_data.get("button") or "View options",
        body=p.input_data.get("text", ""),
    )


def _slides(p: PendingElicitation, raw: dict) -> tuple:
    """The cards as carousel slides, when the agent asked for a horizontal layout and
    every card has an image (the same ``img`` the web widget draws)."""
    if p.orientation != "horizontal":
        return ()
    slides = []
    for card in p.cards:
        data = raw.get(card.card_id) or {}
        cta = data.get("primary_cta") or {}
        slides.append(
            Slide(
                image=str(data.get("img") or ""),
                title=card.title,
                detail=str(data.get("description") or data.get("tags") or data.get("tags_text") or data.get("banner_text") or ""),
                button=str(cta.get("title") or "Select"),
                # A link-only CTA (no tool to run) opens the page; picking needs a quick reply.
                url=str(cta.get("link") or "") if not cta.get("tool_result") else "",
            )
        )
    return tuple(slides) if all(s.image for s in slides) else ()


def _doctor_slides(p: PendingElicitation) -> tuple:
    """The doctors as carousel slides, when the switch is on and every doctor has a picture."""
    if not get_settings().DOCTOR_CAROUSEL_ENABLED:
        return ()
    slides = tuple(Slide(image=d.image, title=d.name, detail=d.description, button="Book appointment") for d in p.doctor_options)
    return slides if all(s.image for s in slides) else ()


def _doctors_list(p: PendingElicitation) -> ChoiceList:
    return ChoiceList(
        step=DOCTOR,
        slides=_doctor_slides(p),
        choices=[from_label(d.name, d.description) for d in p.doctor_options],
        items=p.doctor_options,
        token=list_token(DOCTOR, p.message_id, p.tool_id, *(d.doctor_id for d in p.doctor_options)),
        button=p.input_data.get("button") or "View doctors",
        body="Choose a doctor:",
    )


def _dates_list(p: PendingElicitation, doctor: DoctorOption) -> ChoiceList:
    dates = open_dates(doctor)
    booked_out = any(d["date"] == doctor.preferred_date and d["slots"] == [] for d in doctor.dates)
    body = (
        f"{doctor.name} has no open slots on {format_date(doctor.preferred_date)}. Pick another date:"
        if booked_out
        else f"Pick a date for {doctor.name}:"
    )
    return ChoiceList(
        step=DATE,
        choices=[Choice(format_date(d["date"]), _slot_count(d["slots"])) for d in dates],
        items=[d["date"] for d in dates],
        token=list_token(DATE, p.message_id, p.tool_id, doctor.doctor_id, *(d["date"] for d in dates)),
        button="View dates",
        body=body,
    )


def _slots_list(p: PendingElicitation, doctor: DoctorOption, date: str) -> ChoiceList:
    slots = slots_on(doctor, date)
    token = list_token(SLOT, p.message_id, p.tool_id, doctor.doctor_id, date, *slots)
    return ChoiceList(
        step=SLOT,
        choices=[Choice(time_label(s), section=_part_of_day(s)) for s in slots],
        items=slots,
        token=token,
        button="View slots",
        body=f"Available times for {doctor.name} on {format_date(date)}:",
        extra_rows=(dates_row(token),) if len(open_dates(doctor)) > 1 else (),
    )


def _slot_count(slots: Optional[list]) -> str:
    if not slots:
        return ""
    return f"{len(slots)} slot{'s' if len(slots) != 1 else ''}"


def _part_of_day(slot: str) -> str:
    try:
        hour = datetime.strptime(slot, "%H:%M").hour
    except ValueError:
        return ""
    return "Morning" if hour < 12 else "Afternoon" if hour < 17 else "Evening"
