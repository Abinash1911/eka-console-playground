"""Point a number's inbound webhook at doot.

The URL is keyed on ``Integration.uuid``, so it's stable for the number's life.
Never raises: a failure must not undo the row or binding just saved.
"""

from django.conf import settings

from agents.services.interakt_tp import configure_interakt_webhook
from core.logging import get_logger
from integration import constants

logger = get_logger(__name__)

# Only Interakt tech-partner exposes a per-number override; others are set in the provider dashboard.
PROGRAMMABLE_PROVIDERS = ("interakt_tp",)


def inbound_url(integ) -> str:
    """Where the provider should send this account's inbound traffic.

    WhatsApp goes to doot. A telephony number goes to matrix, whose voice
    answer route looks the agent up from the integration uuid.
    """
    channel = integ.channel or integ.integration_type or ""
    if channel == constants.CHANNEL_TELEPHONY:
        base = getattr(settings, "MATRIX_VOICE_BASE_URL", "").rstrip("/")
        return f"{base}/reloaded/med-assist/voice/answer/{integ.uuid}"
    base = getattr(settings, "DOOT_WEBHOOK_BASE_URL", "").rstrip("/")
    return f"{base}/integration/v1/channel/{channel}/messages/inbound/{integ.uuid}"


def register(integ) -> tuple[bool, str]:
    """Register the inbound URL with the provider. Returns ``(accepted, detail)``."""
    if integ.provider not in PROGRAMMABLE_PROVIDERS:
        return False, f"{integ.provider} has no per-number override to call"

    try:
        credentials = integ.get_credentials()
    except Exception as exc:
        logger.error(
            "integration_webhook_credentials_unreadable",
            integration_id=integ.pk,
            error=str(exc),
        )
        return False, "credentials unreadable"

    phone_number_id = credentials.get("phone_number_id") or ""
    if not phone_number_id:
        # WABA_ONBOARDED sometimes omits it, and the override API is keyed on it.
        logger.warning(
            "integration_webhook_no_phone_number_id", integration_id=integ.pk
        )
        return False, "no phone_number_id on this integration yet"

    url = inbound_url(integ)
    try:
        accepted, detail = configure_interakt_webhook(
            phone_number_id=phone_number_id,
            waba_id=credentials.get("waba_id", ""),
            callback_uri=url,
            verify_token=settings.WHATSAPP_VERIFY_TOKEN,
        )
    except Exception as exc:
        # Webhook not moved: this number's inbound traffic won't reach us.
        logger.error(
            "integration_webhook_register_failed",
            integration_id=integ.pk,
            url=url,
            error=str(exc),
        )
        return False, f"could not reach Interakt: {exc}"

    if not accepted:
        logger.warning(
            "integration_webhook_rejected", integration_id=integ.pk, url=url
        )
        return False, detail

    logger.info(
        "integration_webhook_registered", integration_id=integ.pk, url=url
    )
    return True, ""
