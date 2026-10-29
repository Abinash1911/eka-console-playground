"""
What the console shows about a finished phone call.

A phone call is a conversation like any other, so it needs a session row in
DynamoDB (``mark_conversation_initiated``, called when the call connects) for the
console's Conversations page to project and list it. At the end of the call the
facts only the pipeline knows are merged into the session's ``initial_context``
under ``call``, where the console reads them:

    {"call": {"v": 1, "duration_s": 131, "ended_by": "caller_hung_up",
              "user_turns": 4, "handover": "transferred",
              "tools": ["book_appointment"], "caller": "+91xxxxxx3210"}}

``ended_by``: caller_hung_up, silence, time_limit, transferred, error.
``handover``: none; requested (the caller left before it started); transferred;
failed; declined (outside staff hours).
"""

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from common.utils import get_logger
from echo.models.user_conversation import MessageRole
from med_assist.models.session import SessionCache
from med_assist.service.voice import handover
from med_assist.utils.region import session_region
from med_assist.utils.session_utils import update_session_context

logger = get_logger("med_assist.service.voice.call_record")

SCHEMA_VERSION = 1


@dataclass
class CallFacts:
    """Gathered while the call runs; ``end`` is called by whatever ends it first."""

    started: float = field(default_factory=time.monotonic)
    ended_by: Optional[str] = None
    user_turns: int = 0
    handover: str = "none"
    tools_used: List[str] = field(default_factory=list)

    def end(self, reason: str) -> None:
        """Record how the call ended. The first reason wins: later ones are consequences of it."""
        if self.ended_by is None:
            self.ended_by = reason


def mask_number(number: Optional[str]) -> Optional[str]:
    """``+919876543210`` -> ``+91xxxxxx3210``: country prefix and last four digits only."""
    if not number or not re.match(r"^\+\d{8,15}$", number):
        return None
    return number[:3] + "x" * (len(number) - 7) + number[-4:]


def to_context(facts: CallFacts, caller: Optional[str]) -> dict:
    call = {
        "v": SCHEMA_VERSION,
        "duration_s": max(0, round(time.monotonic() - facts.started)),
        "ended_by": facts.ended_by or "caller_hung_up",
        "user_turns": facts.user_turns,
        "handover": facts.handover,
        "tools": list(dict.fromkeys(facts.tools_used)),
    }
    masked = mask_number(caller)
    if masked:
        call["caller"] = masked
    return {"call": call}


async def finish(
    session_cache: SessionCache,
    facts: CallFacts,
    history: list,
    tools_used: List[str],
    handover_outcome: Optional[str],
) -> None:
    """Fill in what the pipeline knows at the end of the call, then save it."""
    facts.user_turns = sum(1 for message in history if message.role == MessageRole.USER)
    facts.tools_used = tools_used
    facts.handover = handover_outcome or "none"
    await save(session_cache, facts)


async def save(session_cache: SessionCache, facts: CallFacts) -> None:
    """Merge the call facts into the session. Best effort: a failure is logged, never raised."""
    try:
        caller = handover.context_of(session_cache).get("caller")
        await update_session_context(
            session_cache.session_id,
            to_context(facts, caller),
            await session_region(session_cache),
        )
        logger.info(
            "Call record saved", fn="save", sid=session_cache.session_id, ended_by=facts.ended_by
        )
    except Exception as e:
        logger.error(
            "Failed to save call record",
            fn="save",
            sid=session_cache.session_id,
            error=str(e),
        )
