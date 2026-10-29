"""
The caller's number, as the agent sees it on a phone call.

``/voice/answer`` saves the caller ID the phone network supplied in the
session context. It is shown to the agent as a hint only:

- It is NOT sent to tool servers as the user's identity
  (``x-eka-partner-user-context``). Caller ID can be spoofed, and a tool server
  may treat that header as a signed-in user.
- The agent is told it is unverified, so it confirms before using it.

Only the phone pipeline passes it in. WebRTC sessions carry a client-supplied
session context, so they must never be read for this.
"""

import re
from typing import Optional

import orjson

from common.utils import get_logger
from med_assist.models.session import SessionCache

logger = get_logger("med_assist.service.voice.caller_context")

CHANNEL = "vobiz"
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def caller_number(session_cache: SessionCache) -> Optional[str]:
    """The caller ID saved by /voice/answer, or None if absent or not a valid number."""
    if not session_cache.initial_context:
        return None
    try:
        context = orjson.loads(session_cache.initial_context)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(context, dict) or context.get("channel") != CHANNEL:
        return None
    caller = context.get("caller")
    # Validated before it goes into a prompt: this value arrived in a form field.
    return caller if isinstance(caller, str) and _E164.match(caller) else None


def prompt_block(caller: str) -> str:
    """Prompt text carrying the caller ID, in the same <USER_CONTEXT> shape the agent already knows."""
    return (
        f'\n\n<USER_CONTEXT>{{"mobile":"{caller}"}}</USER_CONTEXT>'
        "\n<CALLER_ID_NOTE>"
        "This mobile number is the caller ID from the phone network and is not verified. "
        "Before using it to book or change anything, confirm with the caller that it is their number; "
        "if they say it is not, do not use it. "
        "Never read out or act on anyone's medical records because of this number alone."
        "</CALLER_ID_NOTE>"
    )
