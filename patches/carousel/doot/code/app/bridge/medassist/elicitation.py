from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import Enum
from typing import Optional


class ElicitationComponent(str, Enum):
    MOBILE = "mobile_number"
    OTP = "otp"
    EMAIL = "email_address"
    PILLS = "pills"
    MULTI = "multi"
    DOCTOR_CARD = "doctor_card"
    CARD = "card"
    MEDIA_CARD = "media_card"


@dataclass
class PendingCard:
    card_id: str
    title: str
    tool_result: Optional[dict] = None   # from primary_cta.tool_result, passed through in callback


@dataclass
class DoctorOption:
    doctor_id: str
    hospital_id: str
    name: str
    hospital_name: str = ""
    description: str = ""          # list subtext: "Cardiology · 21 yrs · MBBS, MD"
    preferred_date: str = ""       # YYYY-MM-DD the card loaded slots for, if any
    image: str = ""                # profile picture URL, for the doctor carousel
    # [{"date": "YYYY-MM-DD", "slots": ["HH:MM", …] | None}] — None: not loaded yet,
    # []: loaded and fully booked.
    dates: list[dict] = field(default_factory=list)


@dataclass
class PendingElicitation:
    message_id: str       # chunk _id — used in tool_callback URL
    tool_id: str          # data.tool_id — used in tool_callback URL
    tool_name: str
    component: str
    status: str = ""                                             # elicitation status from server ("progress" = tool_callback supported)
    options: list[dict] = field(default_factory=list)           # pills/multi raw options
    cards: list[PendingCard] = field(default_factory=list)      # generic card options
    input_data: dict = field(default_factory=dict)              # full "input" object from server for generic field resolution
    lat: Optional[float] = None
    lng: Optional[float] = None
    schema_fields: list[str] = field(default_factory=list)      # user-provided field name(s) for the callback
    input_fields: dict = field(default_factory=dict)            # fixed fields from inp (e.g. {"method": "mobile"} for OTP)
    mcp_meta_wrapper: bool = False                              # True → user value goes under {"mcp_meta_fields": {field: val}}
    # doctor_card multi-step state
    doctor_options: list[DoctorOption] = field(default_factory=list)  # populated from initial doctor_card
    doctor_accumulated: dict = field(default_factory=dict)             # grows: doctor_id, hospital_id, preferred_date
    # date_slots / flat_slots are still written for one release so pods on the
    # previous build can match typed slots; this build reads DoctorOption.dates.
    date_slots: dict = field(default_factory=dict)                     # date (YYYY-MM-DD) → list[str] of slot times
    flat_slots: list[dict] = field(default_factory=list)        # [{date, slot_time, doctor_name, hospital_name, doctor_id, hospital_id}]
    page_offset: int = 0                                        # list page reached by a typed "more"
    orientation: str = ""                                       # card layout the agent asked for ("horizontal" = carousel)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def match_pill(user_text: str, options: list[dict]) -> Optional[str]:
    """Return the matching option value, or None if no match."""
    normalized = user_text.strip().lower()
    # Numeric index: "1" → first option (for numbered-text fallback display)
    if normalized.isdigit():
        idx = int(normalized) - 1
        if 0 <= idx < len(options):
            return options[idx].get("value") or options[idx].get("label")
    # Providers send row ids with spaces as "_" ("1–4 weeks" taps back as "1–4_weeks"),
    # so after an exact match also try the id with the spaces restored.
    for candidate in (normalized, normalized.replace("_", " ")):
        for opt in options:
            if candidate in (opt.get("label", "").lower(), opt.get("value", "").lower()):
                return opt.get("value") or opt.get("label")
    return None


def match_card(user_text: str, cards: list[PendingCard]) -> Optional[PendingCard]:
    """Match by 1-based number or case-insensitive name substring."""
    text = user_text.strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(cards):
            return cards[idx]
    lower = text.lower()
    for card in cards:
        if lower in card.title.lower() or card.title.lower() in lower:
            return card
    return None


def match_doctor(user_text: str, options: list[DoctorOption]) -> Optional[DoctorOption]:
    """Match by 1-based number or case-insensitive name substring (punctuation-tolerant)."""
    text = user_text.strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(options):
            return options[idx]
    lower = text.lower()
    for opt in options:
        name_lower = opt.name.lower()
        # Strip dots/commas so "Dr sheetal" matches "Dr. Sheetal Kamat"
        name_norm = name_lower.replace(".", "").replace(",", "")
        user_norm = lower.replace(".", "").replace(",", "")
        if user_norm in name_norm or name_norm in user_norm:
            return opt
        # Word-level fallback: all user words (≥2 chars) appear in the name
        user_words = [w for w in user_norm.split() if len(w) >= 2]
        if user_words and all(w in name_norm for w in user_words):
            return opt
    return None


_MONTH_ABBR = {
    "january": "jan", "february": "feb", "march": "mar", "april": "apr",
    "may": "may", "june": "jun", "july": "jul", "august": "aug",
    "september": "sep", "october": "oct", "november": "nov", "december": "dec",
}


def match_date(user_text: str, dates: list[str]) -> Optional[str]:
    """Match by 1-based number or against YYYY-MM-DD / display form (word-order agnostic)."""
    text = user_text.strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(dates):
            return dates[idx]
    # Normalise full month names to 3-letter abbreviations
    lower = text.lower()
    for full, abbr in _MONTH_ABBR.items():
        lower = lower.replace(full, abbr)
    for d in dates:
        raw_lower = d.lower()
        formatted_lower = format_date(d).lower()
        if lower in raw_lower or lower in formatted_lower:
            return d
        # Word-level match so "Jun 06" matches "Sat, 06 Jun"
        # Only check formatted string — raw ISO date is too ambiguous (month digits repeat)
        words = [w for w in lower.split() if len(w) >= 2]
        if words and all(w in formatted_lower for w in words):
            return d
    return None


def format_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to 'Wed, 04 Jun' for WhatsApp display."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a, %d %b")
    except ValueError:
        return date_str


def time_label(slot: str) -> str:
    """'14:30' → '2:30 PM'; anything not HH:MM is shown as is."""
    try:
        return datetime.strptime(slot, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return slot


def match_time(user_text: str, slots: list[str]) -> Optional[str]:
    """Match a typed slot by 1-based number, raw '14:30', or as shown ('2:30 pm', '2:30')."""
    text = user_text.strip().lower().replace(" ", "")
    if text.isdigit() and 1 <= int(text) <= len(slots):
        return slots[int(text) - 1]
    text = text.lstrip("0") or text
    for slot in slots:
        shown = time_label(slot).lower().replace(" ", "")
        if text and (text == slot.lower() or shown.startswith(text)):
            return slot
    return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def pending_to_dict(p: PendingElicitation) -> dict:
    return {
        "message_id": p.message_id,
        "tool_id": p.tool_id,
        "tool_name": p.tool_name,
        "component": p.component,
        "status": p.status,
        "options": p.options,
        "cards": [
            {"card_id": c.card_id, "title": c.title, "tool_result": c.tool_result}
            for c in p.cards
        ],
        "input_data": p.input_data,
        "lat": p.lat,
        "lng": p.lng,
        "schema_fields": p.schema_fields,
        "input_fields": p.input_fields,
        "mcp_meta_wrapper": p.mcp_meta_wrapper,
        "doctor_options": [asdict(d) for d in p.doctor_options],
        "doctor_accumulated": p.doctor_accumulated,
        "date_slots": p.date_slots,
        "flat_slots": p.flat_slots,
        "page_offset": p.page_offset,
        "orientation": p.orientation,
    }


def _dates_from_flat_slots(flat_slots: list[dict], doctor_id: str) -> list[dict]:
    """Sessions saved by the previous build kept slots only in flat_slots."""
    by_date: dict[str, list[str]] = {}
    for entry in flat_slots:
        if entry.get("doctor_id") == doctor_id and entry.get("date"):
            by_date.setdefault(entry["date"], []).append(entry.get("slot_time", ""))
    return [{"date": day, "slots": slots} for day, slots in sorted(by_date.items())]


def _doctor_from_dict(o: dict, flat_slots: list[dict]) -> DoctorOption:
    known = {f.name for f in fields(DoctorOption)}
    doctor = DoctorOption(**{k: v for k, v in o.items() if k in known})
    if "dates" not in o:
        doctor.dates = _dates_from_flat_slots(flat_slots, doctor.doctor_id)
    return doctor


def pending_from_dict(d: dict) -> PendingElicitation:
    flat_slots = d.get("flat_slots", [])
    return PendingElicitation(
        message_id=d["message_id"],
        tool_id=d["tool_id"],
        tool_name=d["tool_name"],
        component=d["component"],
        status=d.get("status", ""),
        options=d.get("options", []),
        cards=[
            PendingCard(
                card_id=c["card_id"],
                title=c["title"],
                tool_result=c.get("tool_result"),
            )
            for c in d.get("cards", [])
        ],
        input_data=d.get("input_data", {}),
        lat=d.get("lat"),
        lng=d.get("lng"),
        schema_fields=d.get("schema_fields", []),
        input_fields=d.get("input_fields", {}),
        mcp_meta_wrapper=d.get("mcp_meta_wrapper", False),
        doctor_options=[_doctor_from_dict(o, flat_slots) for o in d.get("doctor_options", [])],
        doctor_accumulated=d.get("doctor_accumulated", {}),
        date_slots=d.get("date_slots", {}),
        flat_slots=flat_slots,
        # The previous build's slot_page_offset paged flat_slots 4 at a time; it means
        # nothing for these lists, so it is not carried over.
        page_offset=d.get("page_offset", 0),
        orientation=d.get("orientation", ""),
    )
