"""Vobiz telephony: a number patients dial, which answers with an agent.

The number is the account's identity. Nothing here is secret: Vobiz is pointed
at the answer URL (see ``integration/webhooks.py``), whose uuid is the access
control, so there is no key to store.
"""

import re
from typing import ClassVar, Optional, Tuple

from pydantic import Field, field_validator

from integration.schemas.base import (
    ChannelCredentials,
    ChannelPublic,
    ChannelUpdate,
    ProviderSchemas,
)

PROVIDER = "vobiz"

# E.164: "+" and up to 15 digits, first digit non-zero.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _normalise(value: str) -> str:
    """Drop the spaces, dashes and brackets people type; keep a leading +."""
    return re.sub(r"[\s\-().]", "", value or "")


class VobizCredentials(ChannelCredentials):
    # Identity: the number callers dial (the one provisioned in Vobiz). Create-only.
    phone_number: str = Field(..., min_length=1)
    # The clinic's own public number when it forwards to the one above. Display only.
    public_number: str = ""

    IDENTITY: ClassVar[Tuple[str, ...]] = ("phone_number",)

    @field_validator("phone_number", "public_number")
    @classmethod
    def _e164(cls, value: str) -> str:
        if value == "":
            return value
        value = _normalise(value)
        if not _E164.match(value):
            raise ValueError("must be a phone number with country code, like +918000012345")
        return value

    def uid(self) -> Optional[str]:
        return self.phone_number


class VobizUpdate(ChannelUpdate):
    """Display fields only; changing the dialled number means registering a new one."""

    public_number: Optional[str] = None


class VobizPublic(ChannelPublic):
    phone_number: str = ""
    public_number: str = ""


SCHEMA = ProviderSchemas(
    credentials=VobizCredentials, update=VobizUpdate, public=VobizPublic
)
