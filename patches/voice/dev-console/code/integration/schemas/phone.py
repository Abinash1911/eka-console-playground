"""Phone-number rules shared by the telephony schemas."""

import re

# E.164: "+" and up to 15 digits, first digit non-zero.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalise_e164(value: str) -> str:
    """Drop the spaces, dashes and brackets people type; require a country code.

    Raises ``ValueError`` (which pydantic reports as a validation error).
    """
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not _E164.match(cleaned):
        raise ValueError("must be a phone number with country code, like +918000012345")
    return cleaned
