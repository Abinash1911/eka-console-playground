"""
The Calls page of a phone number: how each call went, in words.

Matrix saves a summary of every call in the session context (``call``, see
``med_assist/service/voice/call_record.py``); the console index promotes it into
``ConsoleSession.context_promoted``. Nothing here reads a transcript.
"""

from typing import Iterable, Optional

from conversations.views import _humanize_date

ENDED_BY = {
    "caller_hung_up": "Caller hung up",
    "silence": "No response (silence)",
    "time_limit": "Time limit reached",
    "transferred": "Passed to staff",
    "error": "Error",
}

HANDOVER = {
    "none": "Not asked for",
    "requested": "Asked for, not connected",
    "transferred": "Connected to staff",
    "failed": "Staff did not pick up",
    "declined": "Outside staff hours",
}


def _outcome(call: dict) -> tuple:
    """(label, tone) for the pill on a row; tone is one of ok, warn, bad, muted."""
    handover = call.get("handover")
    if not call:
        return "Not recorded", "muted"
    if call.get("user_turns") == 0:
        return "No conversation", "muted"
    if call.get("ended_by") == "error":
        return "Error", "bad"
    if handover == "transferred":
        return "Handed over", "ok"
    if handover == "failed":
        return "Handover failed", "bad"
    if handover == "declined":
        return "Outside staff hours", "warn"
    return "Answered by agent", "ok"


def _clock(seconds) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "—"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def present(session) -> dict:
    """One ConsoleSession as a row of the Calls table."""
    call = (session.context_promoted or {}).get("call")
    call = call if isinstance(call, dict) else {}
    label, tone = _outcome(call)
    return {
        "session_id": str(session.session_id),
        "when": _humanize_date(session.created_at.isoformat()),
        "caller": call.get("caller") or "Unknown",
        "duration": _clock(call.get("duration_s")),
        "duration_s": call.get("duration_s"),
        "outcome": label,
        "tone": tone,
        "ended": ENDED_BY.get(call.get("ended_by"), "—"),
        "handover": HANDOVER.get(call.get("handover"), "—"),
        "handed_over": call.get("handover") == "transferred",
        "tools": call.get("tools") or [],
        "recorded": bool(call),
    }


def stats(rows: Iterable[dict]) -> Optional[dict]:
    """Totals over the rows on screen, or None when there are none."""
    rows = list(rows)
    if not rows:
        return None
    timed = [r["duration_s"] for r in rows if isinstance(r["duration_s"], (int, float))]
    return {
        "calls": len(rows),
        "handed_over_pct": round(100 * sum(r["handed_over"] for r in rows) / len(rows)),
        "avg_length": _clock(sum(timed) / len(timed)) if timed else "—",
    }
