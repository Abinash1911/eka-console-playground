"""
Authentication for the Vobiz telephony entry points.

Two doors, both reachable from the open internet:

- the answer webhook (``POST /voice/answer``), which creates a session, and
- the audio WebSocket (``/voice/session/{session_id}/``), which runs the call.

Vobiz cannot do an interactive login, so neither can carry a ``sess_token``.
Instead, one shared secret (``VOICE_TELEPHONY_SECRET`` in the MATRIX config)
guards both:

- the answer URL configured in Vobiz carries the secret as ``?key=``, and
- ``/answer`` hands Vobiz a WebSocket URL with a short-lived ``token`` that is
  an HMAC of the session id, so only a session this server just minted can be
  attached to.

When the secret is not configured nothing is enforced and behaviour is exactly
what it was before, so deploying this changes nothing until the secret is set
and the Vobiz answer URL is updated. A logged warning says so.
"""

import hashlib
import hmac
import time
from typing import Optional

from common.config import get_config_value
from common.utils import get_logger

logger = get_logger("med_assist.service.voice.telephony_auth")

# Matches MAX_CALL_DURATION_SECS in pipeline.py: a reconnect inside a maximum
# length call still works, and the token is useless for a different session.
WS_TOKEN_TTL_SECS = 600

# What a token opens. "ws" is the audio socket; other doors name themselves.
WS_PURPOSE = "ws"


def _secret() -> Optional[bytes]:
    secret = get_config_value("VOICE_TELEPHONY_SECRET")
    return secret.encode() if secret else None


def is_enforced() -> bool:
    return _secret() is not None


def warn_if_open() -> None:
    """Say, once per call, that the telephony entry points are unauthenticated."""
    if not is_enforced():
        logger.warning(
            "VOICE_TELEPHONY_SECRET not set — telephony answer and audio socket are unauthenticated",
            fn="warn_if_open",
        )


def answer_key_ok(key: Optional[str]) -> bool:
    """True when the ``key`` on the answer URL is the shared secret (or none is configured)."""
    secret = _secret()
    if secret is None:
        return True
    return bool(key) and hmac.compare_digest(key.encode(), secret)


def _mac(secret: bytes, purpose: str, session_id: str, expires_at: int) -> str:
    return hmac.new(
        secret, f"{purpose}.{session_id}.{expires_at}".encode(), hashlib.sha256
    ).hexdigest()


def sign_ws_token(session_id: str, purpose: str = WS_PURPOSE, now: Optional[float] = None) -> str:
    """``<expiry>.<mac>`` for this session and purpose, or "" when no secret is configured.

    The purpose is part of what is signed, so a token made for one door never opens another.
    """
    secret = _secret()
    if secret is None:
        return ""
    expires_at = int((time.time() if now is None else now) + WS_TOKEN_TTL_SECS)
    return f"{expires_at}.{_mac(secret, purpose, session_id, expires_at)}"


def verify_ws_token(
    session_id: str,
    token: Optional[str],
    purpose: str = WS_PURPOSE,
    now: Optional[float] = None,
) -> bool:
    """True for a valid, unexpired token for this session and purpose (or when none is configured)."""
    secret = _secret()
    if secret is None:
        return True
    try:
        expiry_part, mac = (token or "").split(".", 1)
        expires_at = int(expiry_part)
    except ValueError:
        return False
    if expires_at < (time.time() if now is None else now):
        return False
    # Bytes, not str: compare_digest raises on non-ASCII text, and the token is attacker-supplied.
    return hmac.compare_digest(mac.encode(), _mac(secret, purpose, session_id, expires_at).encode())
