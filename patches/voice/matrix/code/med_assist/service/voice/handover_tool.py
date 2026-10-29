"""
``transfer_to_human``: the agent's way to pass a phone call to a person.

The tool does not move the call itself. It checks the staff are available, marks
the call as wanting a transfer (``HandoverState``), and tells the agent to say
one short sentence. ``HandoverProcessor`` then starts the transfer once that
sentence has been spoken, so the caller is never cut off mid-word.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from echo.tools.core import BaseTool

from common.utils import get_logger
from med_assist.service.voice.handover_settings import HandoverSettings

logger = get_logger("med_assist.service.voice.handover_tool")

REASONS = ["caller_asked", "not_understood", "emergency", "other"]


@dataclass
class HandoverState:
    """Shared by the tool and the processor for one call."""

    requested: bool = False
    reason: Optional[str] = None
    # For the call record: requested (not finished), transferred, failed or declined.
    outcome: Optional[str] = None


class TransferToHumanTool(BaseTool):
    name = "transfer_to_human"
    description = (
        "Pass this phone call to a person on our team. Use it when the caller asks for a "
        "person, receptionist or doctor; when you still cannot understand them after trying "
        "twice; or in an emergency. Do not use it for anything you can answer or do yourself. "
        "After calling it, say ONE short sentence in the caller's language saying you are "
        "connecting them to our team, then stop speaking."
    )

    def __init__(
        self,
        settings: HandoverSettings,
        state: HandoverState,
        session_id: str,
        now: Optional[datetime] = None,
    ):
        self._settings = settings
        self._state = state
        self._session_id = session_id
        self._now = now  # tests pin the clock; None means the real time

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": REASONS,
                    "description": "Why the call is being passed on.",
                }
            },
            "required": ["reason"],
        }

    async def run(self, reason: str = "other", **_: Any) -> str:
        reason = reason if reason in REASONS else "other"
        if self._state.requested:
            return "A transfer is already in progress. Do not say anything more."
        if not self._settings.is_open(self._now):
            self._state.outcome = "declined"
            logger.info(
                "Handover declined — outside staff hours",
                fn="run",
                sid=self._session_id,
                reason=reason,
            )
            return (
                "Our team is not available to take calls right now; they are available "
                f"{self._settings.hours_text()}. Do not transfer. Tell the caller this in their "
                "language and offer to help them yourself or to try again in those hours."
            )
        self._state.requested = True
        self._state.reason = reason
        self._state.outcome = "requested"
        logger.info("Handover requested", fn="run", sid=self._session_id, reason=reason)
        return (
            "The transfer is starting. Say ONE short sentence in the caller's language telling "
            "them you are connecting them to our team. Do not ask anything and do not say anything else."
        )
