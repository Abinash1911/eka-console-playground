"""
Handing a phone call to a person.

How it works on Vobiz (https://www.vobiz.ai/docs/call/transfer-call and
/docs/xml/dial):

1. The agent calls the ``transfer_to_human`` tool; after it has told the caller
   it is connecting them (see ``handover_processor``) we POST Vobiz's Transfer
   API for the live call, pointing the caller's leg at our ``/voice/transfer``
   URL.
2. Vobiz interrupts the audio stream and fetches that URL, which returns a
   ``<Dial>`` to the staff number (``transfer_xml``). The audio WebSocket closes
   and the call is saved as usual.
3. When the Dial ends, Vobiz asks ``/voice/transfer-result``; ``completed``
   hangs up, anything else (busy, no answer) gets a short apology.

Both URLs carry a signed, short-lived token (``telephony_auth``), and the
feature is off unless ``VOICE_TELEPHONY_SECRET`` is set, because the transfer
URL returns the staff number.

Config: ``VOBIZ_AUTH_ID`` and ``VOBIZ_AUTH_TOKEN`` (already used by the voice
pipeline) and optionally ``VOBIZ_API_BASE_URL``.
"""

import os
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
from xml.sax.saxutils import escape, quoteattr

import httpx
import orjson

from common.config import get_config
from common.utils import get_logger
from med_assist.models.session import SessionCache
from med_assist.service.voice import telephony_auth, telephony_binding
from med_assist.service.voice.handover_settings import HandoverSettings

logger = get_logger("med_assist.service.voice.handover")

TRANSFER_PURPOSE = "transfer"
VOBIZ_API_BASE_URL = "https://api.vobiz.ai/api/v1"
TRANSFER_TIMEOUT_SECS = 8

# Said by Vobiz's own text-to-speech when the Dial fails after the AI has gone.
# Vobiz's voices are listed in its docs without Hindi, so this is English.
UNAVAILABLE_MESSAGE = (
    "Sorry, our team could not take your call right now. Please call again later. Goodbye."
)

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass
class HandoverOffer:
    """Handover is available on this call: who to ring, and how to start the transfer."""

    settings: HandoverSettings
    transfer: Callable[[], Awaitable[bool]]


def _http_base() -> str:
    return (get_config().get("HOST") or "").rstrip("/")


def _signed_url(path: str, session_id: str) -> str:
    token = telephony_auth.sign_ws_token(session_id, purpose=TRANSFER_PURPOSE)
    return f"{_http_base()}/reloaded/med-assist/voice/{path}/{session_id}?token={token}"


def transfer_url(session_id: str) -> str:
    return _signed_url("transfer", session_id)


def result_url(session_id: str) -> str:
    return _signed_url("transfer-result", session_id)


def transfer_xml(settings: HandoverSettings, session_id: str, caller_id: Optional[str]) -> str:
    """The XML Vobiz runs when the caller's leg lands on the transfer URL: ring the staff phone.

    ``caller_id`` must be a Vobiz number the account owns, so it is the number
    the patient dialled; omitted (Vobiz then uses the caller's) when unknown.
    """
    caller_attr = (
        f" callerId={quoteattr(caller_id)}" if caller_id and _E164.match(caller_id) else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"    <Dial{caller_attr} timeout={quoteattr(str(settings.ring_seconds))}"
        f' action={quoteattr(result_url(session_id))} method="POST" redirect="true"'
        f" sipHeaders={quoteattr('Reference=' + session_id)}>\n"
        f"        <Number>{escape(settings.number)}</Number>\n"
        "    </Dial>\n"
        "</Response>"
    )


def result_xml(dial_status: Optional[str]) -> str:
    """What to do when the Dial ends: hang up if staff spoke to the caller, else apologise."""
    if (dial_status or "").lower() == "completed":
        body = "    <Hangup/>\n"
    else:
        body = f"    <Speak>{escape(UNAVAILABLE_MESSAGE)}</Speak>\n    <Hangup/>\n"
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n{body}</Response>'


def context_of(session_cache: SessionCache) -> dict:
    """The session context /voice/answer saved (server-built for phone sessions)."""
    try:
        context = orjson.loads(session_cache.initial_context or "{}")
    except orjson.JSONDecodeError:
        return {}
    return context if isinstance(context, dict) else {}


async def settings_for_session(session_cache: SessionCache) -> Optional[HandoverSettings]:
    """The staff number and hours for this call's number, or None."""
    number_uuid = context_of(session_cache).get("integration_uuid")
    if not number_uuid:
        return None
    return await telephony_binding.handover_for_number(number_uuid)


async def request_transfer(call_uuid: str, aleg_url: str) -> bool:
    """Ask Vobiz to send the caller's leg of a live call to ``aleg_url``. True if Vobiz accepted it."""
    auth_id = os.environ.get("VOBIZ_AUTH_ID", "")
    auth_token = os.environ.get("VOBIZ_AUTH_TOKEN", "")
    base = os.environ.get("VOBIZ_API_BASE_URL", VOBIZ_API_BASE_URL).rstrip("/")
    url = f"{base}/Account/{auth_id}/Call/{call_uuid}/"
    try:
        async with httpx.AsyncClient(timeout=TRANSFER_TIMEOUT_SECS) as client:
            response = await client.post(
                url,
                headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token},
                json={"legs": "aleg", "aleg_url": aleg_url, "aleg_method": "POST"},
            )
    except httpx.HTTPError as e:
        logger.error("Vobiz transfer request failed", fn="request_transfer", error=type(e).__name__)
        return False
    if response.status_code // 100 != 2:
        # Status only: the URL carries a token and the body is Vobiz's.
        logger.error(
            "Vobiz refused the transfer",
            fn="request_transfer",
            error=f"HTTP {response.status_code}",
        )
        return False
    logger.info(
        "Vobiz accepted the transfer", fn="request_transfer", resp_code=response.status_code
    )
    return True


async def offer_for_call(
    session_cache: SessionCache, call_id: Optional[str]
) -> Optional[HandoverOffer]:
    """Handover for this call, or None when any prerequisite is missing (logged)."""
    session_id = session_cache.session_id
    if not telephony_auth.is_enforced():
        return _not_offered(session_id, "VOICE_TELEPHONY_SECRET is not set")
    if not (os.environ.get("VOBIZ_AUTH_ID") and os.environ.get("VOBIZ_AUTH_TOKEN")):
        return _not_offered(session_id, "VOBIZ_AUTH_ID / VOBIZ_AUTH_TOKEN are not set")
    if not _http_base():
        return _not_offered(session_id, "HOST is not set")
    call_uuid = call_id or context_of(session_cache).get("call_uuid")
    if not call_uuid:
        return _not_offered(session_id, "no call id")
    settings = await settings_for_session(session_cache)
    if settings is None:
        return _not_offered(session_id, "no handover configured for this number")

    async def transfer() -> bool:
        return await request_transfer(call_uuid, transfer_url(session_id))

    return HandoverOffer(settings=settings, transfer=transfer)


def _not_offered(session_id: str, why: str) -> None:
    logger.info(
        "Handover not offered on this call", fn="offer_for_call", sid=session_id, reason=why
    )
    return None
