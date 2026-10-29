"""
Where a phone call can be handed to a person, and when.

The console stores this as ``handover`` in the agent binding's ``config`` (the
``product_integrations`` row for the number); ``telephony_binding`` reads it
here. Shape, as validated by the console:

    {"number": "+919999911111",
     "hours": {"start": "09:00", "end": "18:00", "timezone": "Asia/Kolkata"},
     "ring_seconds": 30}

``hours`` is optional (absent = always available); ``start`` after ``end``
means overnight.
"""

import re
from datetime import datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import orjson
from pydantic import BaseModel, Field, ValidationError, field_validator

from common.utils import get_logger

logger = get_logger("med_assist.service.voice.handover_settings")

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class HandoverHours(BaseModel):
    start: str
    end: str
    timezone: str = "Asia/Kolkata"

    # The console validates these, but they come from a shared database and end
    # up in a live call, so a bad value must fail here, not mid-call.
    @field_validator("start", "end")
    @classmethod
    def _clock_time(cls, value: str) -> str:
        time.fromisoformat(value)
        return value

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r}") from None
        return value


class HandoverSettings(BaseModel):
    number: str
    hours: Optional[HandoverHours] = None
    ring_seconds: int = Field(default=30, ge=10, le=60)

    @field_validator("number")
    @classmethod
    def _phone_number(cls, value: str) -> str:
        # It is written into call-control XML, so only a plain E.164 number is accepted.
        if not _E164.match(value):
            raise ValueError("number must be E.164, like +918000012345")
        return value

    def is_open(self, now: Optional[datetime] = None) -> bool:
        """True when staff can take a call at ``now`` (default: the current time)."""
        if self.hours is None:
            return True
        local = (now or datetime.now(ZoneInfo(self.hours.timezone))).astimezone(
            ZoneInfo(self.hours.timezone)
        )
        start, end = time.fromisoformat(self.hours.start), time.fromisoformat(self.hours.end)
        at = local.time().replace(second=0, microsecond=0)
        if start < end:
            return start <= at < end
        return at >= start or at < end  # overnight

    def hours_text(self) -> str:
        if self.hours is None:
            return "any time"
        return f"{self.hours.start} to {self.hours.end} ({self.hours.timezone})"


def from_binding_config(config: Any) -> Optional[HandoverSettings]:
    """Handover settings from a binding's ``config`` JSON, or None if absent or unusable.

    A bad value must not break the call: the agent just is not offered handover.
    """
    if isinstance(config, (str, bytes)):
        try:
            config = orjson.loads(config)
        except orjson.JSONDecodeError:
            logger.warning(
                "Binding config is not JSON", fn="from_binding_config", error="invalid json"
            )
            return None
    handover = (config or {}).get("handover") if isinstance(config, dict) else None
    if not handover:
        return None
    try:
        return HandoverSettings.model_validate(handover)
    except ValidationError as e:
        # Fields and reasons only: the input would put a phone number in the logs.
        logger.warning(
            "Handover settings unusable — not offering handover",
            fn="from_binding_config",
            error=str(e.errors(include_input=False, include_url=False, include_context=False)),
        )
        return None
