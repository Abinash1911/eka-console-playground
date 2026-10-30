"""WhatsApp choice lists: pages of rows the bridge can resolve back to the option tapped.

Row ids are "{token}.{n}" (option n of the full list), "{token}.m{offset}" ("Show more")
and "{token}.d" ("Other dates"). The token is a short hash of the list's content, so
nothing is stored to resolve a tap and a list from an earlier step has a different one.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

LIST_ROWS = 10          # per list message, across all sections
TITLE_MAX = 24          # row and section title
DESCRIPTION_MAX = 72
BUTTON_MAX = 20         # list button label and reply-button title
REPLY_BUTTONS = 3
BUTTONS_BODY_MAX = 1024
LIST_BODY_MAX = 4096

# Interactive media carousel (Meta): 2 to 10 cards, each with an image, a short text and one button.
CAROUSEL_MIN = 2
CAROUSEL_MAX = 10
CAROUSEL_BODY_MAX = 1024
CARD_TEXT_MAX = 160

MORE = "m"
DATES = "d"

_ROW_ID = re.compile(r"^(?P<token>[0-9a-f]{6})\.(?P<kind>[md])?(?P<n>\d*)$")
# A label that's too long for a row splits here into title + subtext; spaces are
# required so ranges like "1–4 weeks" stay whole.
_SEPARATORS = (" — ", " – ", " | ", " - ")
# Dropped from the end of a title when a long label wraps at a space ("Apollo Hospitals,").
_WRAP_TRIM = " ,;:-–—|"


@dataclass(frozen=True)
class Choice:
    title: str
    description: str = ""
    section: str = ""


@dataclass(frozen=True)
class Slide:
    """One carousel card: an image, its text and the label of its one button."""

    image: str
    title: str
    detail: str = ""
    button: str = "Select"


@dataclass(frozen=True)
class Tap:
    token: str
    kind: str  # "" option, MORE, DATES
    n: int     # option index, or the offset a "Show more" opens


def _width(text: str) -> int:
    """Length as WhatsApp counts it (UTF-16 units, so an emoji is 2)."""
    return len(text.encode("utf-16-le")) // 2


def clip(text: str, limit: int) -> str:
    """One line of at most ``limit`` units, ending in "…" when cut."""
    text = " ".join(str(text or "").split())
    if _width(text) <= limit:
        return text
    kept, used = [], 0
    for ch in text:
        used += _width(ch)
        if used > limit - 1:
            break
        kept.append(ch)
    return "".join(kept).rstrip() + "…"


def from_label(label: str, description: str = "") -> Choice:
    """A choice from an option label; a label too long for a row moves its detail below.

    WhatsApp shows the row title and subtext in the user's own reply bubble too, so
    the split must read naturally there and never repeat text:
      "Dr. Sanjay Pai — 38 years' experience" → "Dr. Sanjay Pai" / "38 years' experience"
      "Yes, Sheshadripuram works"             → "Yes, Sheshadripuram" / "works"
    Only a single word longer than a row is clipped with "…" (full label below).
    """
    label = " ".join(str(label or "").split())
    if description or _width(label) <= TITLE_MAX:
        return Choice(label, description)
    for separator in _SEPARATORS:
        head, found, rest = label.partition(separator)
        if found and head and rest:
            return Choice(head, rest)
    cut = label.rfind(" ", 0, TITLE_MAX + 1)
    head = label[:cut].rstrip(_WRAP_TRIM) if cut > 0 else ""
    if head:
        return Choice(head, label[cut + 1:])
    return Choice(label, label)


def list_token(*parts) -> str:
    """Six hex chars, the same for the same list content and different otherwise."""
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.blake2b(raw.encode(), digest_size=3).hexdigest()


def parse_row_id(raw: str) -> Optional[Tap]:
    match = _ROW_ID.match(raw or "")
    if not match:
        return None
    kind = match["kind"] or ""
    if kind == DATES:
        return Tap(match["token"], kind, 0)
    if not match["n"]:
        return None
    return Tap(match["token"], kind, int(match["n"]))


def is_choice_id(raw: str) -> bool:
    """True for a row id minted here (opaque — never shown to the agent)."""
    return parse_row_id(raw) is not None


def reply_text(reply: dict) -> str:
    """The tapped option's text; a clipped title's full label rides in its description."""
    title = reply.get("title", "")
    description = reply.get("description", "")
    if title.endswith("…") and description.startswith(title[:-1]):
        return description
    return title


def row(choice: Choice, row_id: str) -> dict:
    out = {"id": row_id, "title": clip(choice.title, TITLE_MAX)}
    if choice.description:
        out["description"] = clip(choice.description, DESCRIPTION_MAX)
    return out


def dates_row(token: str) -> dict:
    return {"id": f"{token}.{DATES}", "title": "Other dates"}


def page_bounds(total: int, offset: int, reserved: int = 0) -> tuple[int, int, bool]:
    """(start, end, has_more) of the page at ``offset``; ``reserved`` rows are fixed extras."""
    capacity = LIST_ROWS - reserved
    start = offset if 0 <= offset < total else 0
    if total - start <= capacity:
        return start, total, False
    return start, start + capacity - 1, True


def list_sections(
    choices: list[Choice],
    token: str,
    title: str,
    offset: int = 0,
    extra_rows: tuple = (),
) -> list[dict]:
    """One page of ``choices`` as list sections, with "Show more" and ``extra_rows`` last.

    Rows are grouped by ``Choice.section`` (``title`` when unset), so every section
    has a non-empty title as WhatsApp requires.
    """
    start, end, has_more = page_bounds(len(choices), offset, len(extra_rows))
    sections: list[dict] = []
    for i in range(start, end):
        name = clip(choices[i].section or title, TITLE_MAX)
        if not sections or sections[-1]["title"] != name:
            sections.append({"title": name, "rows": []})
        sections[-1]["rows"].append(row(choices[i], f"{token}.{i}"))

    tail = list(extra_rows)
    if has_more:
        more = {"id": f"{token}.{MORE}{end}", "title": "Show more", "description": f"{len(choices) - end} more"}
        tail.insert(0, more)
    if tail:
        if not sections:
            sections.append({"title": clip(title, TITLE_MAX), "rows": []})
        sections[-1]["rows"].extend(tail)
    return sections


def fits_buttons(choices: list[Choice], body: str) -> bool:
    """Reply buttons: up to 3 unique short titles, no subtext, and a short enough body."""
    titles = [c.title.lower() for c in choices]
    return (
        len(choices) <= REPLY_BUTTONS
        and all(not c.description and _width(c.title) <= BUTTON_MAX for c in choices)
        and len(set(titles)) == len(titles)
        and _width(body) <= BUTTONS_BODY_MAX
    )


def numbered(choices: list[Choice]) -> str:
    """Plain-text fallback, numbered 1..n over the full list (typed digits resolve against it)."""
    lines = []
    for i, c in enumerate(choices, 1):
        detail = f" — {c.description}" if c.description and c.description != c.title else ""
        lines.append(f"{i}. {c.title}{detail}")
    return "\n".join(lines)


def fits_carousel(slides: list[Slide], body: str) -> bool:
    """A carousel needs 2 to 10 cards that each have an image, and a body short enough."""
    return (
        CAROUSEL_MIN <= len(slides) <= CAROUSEL_MAX
        and all(s.image.startswith("https://") and s.title for s in slides)
        and _width(body) <= CAROUSEL_BODY_MAX
    )


def card_text(slide: Slide) -> str:
    """Bold title, then the detail on the next line, within WhatsApp's 160 characters."""
    title = clip(slide.title, CARD_TEXT_MAX - 2)
    head = f"*{title}*"
    room = CARD_TEXT_MAX - _width(head) - 1
    detail = clip(slide.detail, room) if slide.detail and room > 1 else ""
    return f"{head}\n{detail}" if detail else head


def carousel_cards(slides: list[Slide], token: str) -> list[dict]:
    """Slides as Meta carousel cards; each button's id is ``{token}.{n}``, like a list row."""
    return [
        {
            "card_index": i,
            "type": "cta_url",
            "header": {"type": "image", "image": {"link": slide.image}},
            "body": {"text": card_text(slide)},
            "action": {
                "buttons": [
                    {
                        "type": "quick_reply",
                        "quick_reply": {
                            "id": f"{token}.{i}",
                            "title": clip(slide.button, BUTTON_MAX),
                        },
                    }
                ]
            },
        }
        for i, slide in enumerate(slides)
    ]
