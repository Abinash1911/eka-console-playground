"""
What the "Test this number" card on a phone number's page shows.

A real test is a phone call, so the card does not place one: it says whether
the console side is ready, and which number to ring. It cannot see Vobiz (is
the Answer URL pasted there?) or the platform's phone secrets; the card says so.
"""

from typing import Optional


def checks(binding, agent) -> list:
    """(label, ok, hint) for what the console can see. ``ok`` of None means optional and not set."""
    connected = binding is not None and agent is not None
    return [
        ("An agent is connected", connected, "" if connected else "Pick an agent under Answer calls with an agent."),
        (
            "The connection is on",
            bool(connected and binding.is_active),
            "" if connected and binding.is_active else "Resume it, or callers are hung up on.",
        ),
        (
            "Calls can be handed to a person",
            True if connected and (binding.config or {}).get("handover") else None,
            "Optional. Without it the agent cannot pass a caller to staff.",
        ),
    ]


def ready(rows: list) -> bool:
    return all(ok for _, ok, _ in rows if ok is not None)


def number_to_ring(credentials: dict) -> Optional[str]:
    """The clinic's public number when it forwards here (tests the whole path), else the dialled number."""
    return credentials.get("public_number") or credentials.get("phone_number") or None
