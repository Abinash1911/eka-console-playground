"""Eka Agents: messages are handled in-process, so only an optional status callback.

``handover`` is for phone numbers: where the agent can pass a call to a person.
Other channels ignore it.
"""

from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.constants import Product
from integration.schemas.phone import normalise_e164
from integration.schemas.products.utils import Callback

PRODUCT = Product.AGENT.value

_HH_MM = r"^([01]\d|2[0-3]):[0-5]\d$"


class HandoverHours(BaseModel):
    """When staff can take a call. ``start`` after ``end`` means overnight (22:00 to 06:00)."""

    model_config = ConfigDict(extra="forbid")

    start: str = Field(pattern=_HH_MM)
    end: str = Field(pattern=_HH_MM)
    timezone: str = "Asia/Kolkata"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"unknown timezone {value!r}; use an IANA name like Asia/Kolkata"
            ) from None
        return value

    @model_validator(mode="after")
    def _a_real_window(self):
        if self.start == self.end:
            raise ValueError("start and end are the same time")
        return self


class Handover(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Staff phone the call is passed to; not the clinic's public number.
    number: str
    # Absent = always available.
    hours: Optional[HandoverHours] = None
    # How long to ring before giving up.
    ring_seconds: int = Field(default=30, ge=10, le=60)

    @field_validator("number")
    @classmethod
    def _e164(cls, value: str) -> str:
        return normalise_e164(value)


class AgentProductConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[Callback] = None
    handover: Optional[Handover] = None


CONFIG = AgentProductConfig
