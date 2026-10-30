"""Interakt Tech-Partner (ISV) WhatsApp Provider.

Unlike the classic :class:`InteraktWhatsAppProvider` (which uses per-account
API keys against ``api.interakt.ai/v1/public/message/``), the tech-partner model
routes every onboarded WABA through Interakt's **amped-express** endpoint, which
is a Meta-Graph-compatible proxy:

    POST {AMPED}/{phone_number_id}/messages
    headers: x-access-token=<shared ISV token>, x-waba-id=<per-WABA id>

Sends are billed against our Interakt credit line and are not rate-limited.

Incoming webhooks come straight from Meta (via Interakt's ``override_callback_uri``)
in Meta Graph format; see ``parse_webhook`` and ``verify_signature``.
"""
import json
import httpx
from typing import List, Dict, Any, Mapping, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from .base_provider import WhatsAppProviderBase, delivery_lag, sent_at_stamp

logger = get_logger(__name__)


class InteraktTPWhatsAppProvider(WhatsAppProviderBase):
    """Interakt tech-partner provider (Meta-Graph payloads via amped-express)."""

    supports_carousel = True

    def __init__(
        self,
        isv_token: str,
        waba_id: str,
        phone_number_id: str,
        app_secret: str = "",
        amped_url: str | None = None,
    ):
        self.settings = get_settings()
        self.isv_token = isv_token or self.settings.INTERAKT_ISV_TOKEN
        self.waba_id = waba_id
        self.phone_number_id = phone_number_id
        # Meta app secret is used to validate X-Hub-Signature-256 on forwarded webhooks.
        self.app_secret = app_secret or self.settings.META_APP_SECRET
        amped_base = (amped_url or self.settings.INTERAKT_AMPED_URL).rstrip("/")
        self.base_url = f"{amped_base}/{phone_number_id}"
        self.amped_base = amped_base

        self.headers = {
            "x-access-token": self.isv_token,
            "x-waba-id": self.waba_id,
            "Content-Type": "application/json",
        }

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )

        logger.info(
            "interakt_tp_provider_initialized",
            waba_id=self.waba_id,
            phone_number_id=self.phone_number_id,
            amped_url=self.base_url,
        )

    # ------------------------------------------------------------------ #
    # Webhook signature verification
    # ------------------------------------------------------------------ #
    async def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        """Skipped: Meta signs with Interakt's app secret (the subscribing app), not ours.

        The unguessable uuid in the webhook URL is the guard; any new route needs one too.
        """
        return

    # ------------------------------------------------------------------ #
    # Outbound messages (Meta-Graph payloads, billed via credit line)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_to(to: str) -> str:
        """Meta expects the recipient as a plain digit string (no '+')."""
        return "".join(filter(str.isdigit, to or ""))

    @staticmethod
    def _build_header(header: Any) -> Optional[Dict[str, Any]]:
        """Build a Meta ``interactive.header`` object.

        Accepts either:
          * a ``str`` → ``{"type": "text", "text": <truncated to 60>}`` (legacy behaviour), or
          * a ``dict`` media header ``{"type": "image"|"video"|"document",
            "<type>": {"link": ...} | {"id": ...}}`` → passed through as-is.

        Returns ``None`` for falsy input so callers can conditionally attach it.
        Note: list messages support text headers only (Meta constraint) — callers
        for lists should pass text.
        """
        if not header:
            return None
        if isinstance(header, str):
            return {"type": "text", "text": header[:60]}
        if isinstance(header, dict):
            return header
        logger.warning("interakt_tp_invalid_header", header_type=type(header).__name__)
        return None

    @staticmethod
    def _media_ref(link_or_id: str) -> Dict[str, str]:
        """Return a Meta media reference. HTTP(S) values → ``link``; otherwise → ``id``.

        Lets a single caller pass either a public URL or a pre-uploaded media id
        (see :meth:`upload_media`). Meta prefers ``id`` (avoids link-fetch rate limits).
        """
        value = link_or_id or ""
        if value.startswith("http://") or value.startswith("https://"):
            return {"link": value}
        return {"id": value}

    async def _post_message(
        self,
        payload: Dict[str, Any],
        context: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST a message payload. ``context`` is a log label only.

        ``reply_to`` (a prior inbound ``wamid``) threads this send as a reply via
        Meta's ``context.message_id`` — the recipient sees a quoted bubble. Ignored
        by Meta if the referenced message is >30 days old or unknown.

        ``biz_opaque_callback_data`` carries our send time; Meta echoes it on status
        webhooks, which is how ``interakt_tp_delivery_status`` reports ``lag_s``.
        """
        payload = {**payload, "biz_opaque_callback_data": sent_at_stamp()}
        if reply_to:
            payload = {**payload, "context": {"message_id": reply_to}}
        try:
            response = await self._client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(
                "interakt_tp_message_sent",
                context=context,
                message_id=(result.get("messages", [{}]) or [{}])[0].get("id", "unknown"),
            )
            return result
        except httpx.HTTPStatusError as e:
            logger.error(
                "interakt_tp_message_failed",
                context=context,
                status_code=e.response.status_code,
                response_body=e.response.text,
            )
            raise
        except httpx.HTTPError as e:
            logger.error("interakt_tp_message_network_error", context=context, error=str(e))
            raise

    async def send_text(
        self,
        to: str,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "text",
            "text": {"body": text},
        }
        return await self._post_message(payload, "text", reply_to=reply_to_message_id)

    async def _post_status(self, payload: Dict[str, Any], context: str) -> None:
        """POST a status payload (read receipt / typing) to /messages. Best-effort.

        Read receipts and typing are non-critical, so a failure is logged and
        swallowed rather than propagated to the caller.
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            logger.info("interakt_tp_status_sent", context=context)
        except httpx.HTTPError as e:
            logger.warning("interakt_tp_status_failed", context=context, error=str(e))

    async def mark_as_read(self, message_id: str) -> None:
        """Mark an inbound message as read (blue ticks). Marks earlier messages read too."""
        if not message_id:
            return
        await self._post_status(
            {"messaging_product": "whatsapp", "status": "read", "message_id": message_id},
            "read",
        )

    async def send_typing_indicator(self, to: str, message_id: str) -> None:
        """Show the typing indicator. On Meta Cloud API this rides the read-status call
        (``typing_indicator`` on a ``status: read`` payload) and auto-dismisses after
        ~25s or when the next message is sent."""
        if not message_id:
            return
        await self._post_status(
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
                "typing_indicator": {"type": "text"},
            },
            "typing",
        )

    async def send_button_message(
        self,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        header: Any = None,
        footer_text: str = None,
    ) -> Dict[str, Any]:
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": str(btn.get("id", btn.get("title", ""))).replace(" ", "_"),
                            "title": str(btn.get("title", ""))[:20],
                        },
                    }
                    for btn in buttons[:3]
                ]
            },
        }
        # ``header`` accepts a str (text) or a media-header dict (image/video/document).
        built_header = self._build_header(header)
        if built_header:
            interactive["header"] = built_header
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": interactive,
        }
        return await self._post_message(payload, "button")

    async def send_list_message(
        self,
        to: str,
        body_text: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        header_text: str = None,
        footer_text: str = None,
    ) -> Dict[str, Any]:
        formatted_sections = []
        for section in self.cap_list_sections(sections):
            rows = [self.list_row(row) for row in section["rows"]]
            if rows:
                formatted_sections.append(
                    {"title": str(section.get("title", "Options"))[:24], "rows": rows}
                )

        interactive: Dict[str, Any] = {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": button_text[:20], "sections": formatted_sections},
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": interactive,
        }
        return await self._post_message(payload, "list")

    async def send_document(
        self,
        to: str,
        document_url: str,
        filename: str,
        caption: Optional[str] = None,
        media_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a document by public URL (``document_url``) or a pre-uploaded
        ``media_id`` (preferred — see :meth:`upload_media`). If both are given,
        ``media_id`` wins.
        """
        ref = {"id": media_id} if media_id else self._media_ref(document_url)
        ref["filename"] = filename
        ref["caption"] = caption or filename
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "document",
            "document": ref,
        }
        return await self._post_message(payload, "document")

    async def send_audio(
        self,
        to: str,
        audio_url: str = "",
        media_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send audio by public URL (``audio_url``) or a pre-uploaded ``media_id``.

        For a voice-note-style bubble (waveform), upload a mono OGG/Opus clip
        ≤512 KB via :meth:`upload_media` and pass its ``media_id``.
        """
        ref = {"id": media_id} if media_id else self._media_ref(audio_url)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "audio",
            "audio": ref,
        }
        return await self._post_message(payload, "audio")

    async def _send_simple_media(
        self,
        to: str,
        kind: str,
        media: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Shared image/video/sticker send; ``media`` is a URL or media id."""
        ref = self._media_ref(media)
        # Stickers take no caption (Meta constraint).
        if caption and kind != "sticker":
            ref["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": kind,
            kind: ref,
        }
        return await self._post_message(payload, kind)

    async def send_image(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an image (jpeg/png, <= 5 MB) by URL or media id."""
        return await self._send_simple_media(to, "image", media, caption)

    async def send_video(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a video (mp4/3gpp, H.264 + AAC, <= 16 MB) by URL or media id."""
        return await self._send_simple_media(to, "video", media, caption)

    async def send_sticker(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a static webp sticker (<= 100 KB). ``caption`` is ignored by Meta."""
        return await self._send_simple_media(to, "sticker", media, caption)

    # ------------------------------------------------------------------ #
    # Media upload (Meta-Graph: bytes -> media id, reusable for 30 days)
    # ------------------------------------------------------------------ #
    async def upload_media(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str = "",
    ) -> str:
        """Upload media to WhatsApp and return its ``media_id``.

        ``POST {amped}/{phone_number_id}/media`` as multipart/form-data. The
        returned id persists ~30 days and can be reused across many sends,
        avoiding Meta's link-fetch rate limits. Content-Type header is dropped
        here so httpx sets the correct multipart boundary.
        """
        upload_headers = {k: v for k, v in self.headers.items() if k.lower() != "content-type"}
        files = {"file": (filename or "upload", file_bytes, mime_type)}
        data = {"messaging_product": "whatsapp", "type": mime_type}
        try:
            response = await self._client.post(
                f"{self.base_url}/media",
                data=data,
                files=files,
                headers=upload_headers,
            )
            response.raise_for_status()
            media_id = response.json().get("id", "")
            if not media_id:
                raise ValueError("no media id returned from upload")
            logger.info("interakt_tp_media_uploaded", media_id=media_id, size_bytes=len(file_bytes))
            return media_id
        except httpx.HTTPStatusError as e:
            logger.error(
                "interakt_tp_media_upload_failed",
                status_code=e.response.status_code,
                response_body=e.response.text,
            )
            raise
        except httpx.HTTPError as e:
            logger.error("interakt_tp_media_upload_network_error", error=str(e))
            raise

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        template: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "template",
            "template": template,
        }
        return await self._post_message(payload, "template")

    # ------------------------------------------------------------------ #
    # Rich interactive messages (free-form within the 24h session window)
    # ------------------------------------------------------------------ #
    async def send_cta_url(
        self,
        to: str,
        body_text: str,
        display_text: str,
        url: str,
        header: Any = None,
        footer_text: str = None,
    ) -> Dict[str, Any]:
        """Send an interactive Call-To-Action URL button (``interactive.type=cta_url``).

        Renders a tappable button that opens ``url``. Single URL button only.
        ``display_text`` ≤ 20 chars, ``url`` ≤ 2000.
        """
        interactive: Dict[str, Any] = {
            "type": "cta_url",
            "body": {"text": body_text},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": display_text[:20], "url": url},
            },
        }
        built_header = self._build_header(header)
        if built_header:
            interactive["header"] = built_header
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": interactive,
        }
        return await self._post_message(payload, "cta_url")

    async def send_carousel(
        self, to: str, body_text: str, cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Send an interactive media carousel (``interactive.type=carousel``).

        2 to 10 ``cards``, each with an image header, text and one button; every card
        needs the same button type and count. Free-form, so only inside the 24h window.
        The main message takes no header or footer.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": {
                "type": "carousel",
                "body": {"text": body_text},
                "action": {"cards": cards},
            },
        }
        return await self._post_message(payload, "carousel")

    async def send_location_request(self, to: str, body_text: str) -> Dict[str, Any]:
        """Ask the user to share their location (``interactive.type=location_request_message``).

        The reply arrives as an inbound ``location`` message (already parsed).
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": {
                "type": "location_request_message",
                "body": {"text": body_text},
                "action": {"name": "send_location"},
            },
        }
        return await self._post_message(payload, "location_request")

    async def send_flow(
        self,
        to: str,
        body_text: str,
        flow_id: str,
        flow_token: str,
        flow_cta: str,
        flow_action: str = "navigate",
        screen: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        mode: str = "published",
        header: Any = None,
        footer_text: str = None,
    ) -> Dict[str, Any]:
        """Send a WhatsApp Flow (``interactive.type=flow``) — a native multi-screen form.

        ``flow_action="navigate"`` (static, no backend) is the default; for the
        first ``navigate`` screen pass ``screen`` (and optional ``data``). Use
        ``flow_action="data_exchange"`` only with a hosted encrypted endpoint
        (out of scope here). ``flow_token`` correlates the completion webhook
        (``nfm_reply``) back to the originating session. ``mode`` is ``"draft"``
        while testing an unpublished flow, else ``"published"``.
        """
        parameters: Dict[str, Any] = {
            "flow_message_version": "3",
            "flow_token": flow_token,
            "flow_id": flow_id,
            "flow_cta": flow_cta[:20],
            "flow_action": flow_action,
        }
        if mode:
            parameters["mode"] = mode
        if flow_action == "navigate":
            action_payload: Dict[str, Any] = {}
            if screen:
                action_payload["screen"] = screen
            if data:
                action_payload["data"] = data
            if action_payload:
                parameters["flow_action_payload"] = action_payload

        interactive: Dict[str, Any] = {
            "type": "flow",
            "body": {"text": body_text},
            "action": {"name": "flow", "parameters": parameters},
        }
        built_header = self._build_header(header)
        if built_header:
            interactive["header"] = built_header
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_to(to),
            "type": "interactive",
            "interactive": interactive,
        }
        return await self._post_message(payload, "flow")

    # ------------------------------------------------------------------ #
    # Media download (Meta-Graph: resolve media id -> url -> bytes)
    # ------------------------------------------------------------------ #
    async def download_media(self, media_id: str) -> bytes:
        try:
            if media_id.startswith("http"):
                response = await self._client.get(media_id, timeout=60.0)
                response.raise_for_status()
                return response.content

            # amped-express proxies GET /{media_id} -> {"url": "..."}
            meta = await self._client.get(
                f"{self.amped_base}/{media_id}",
                headers=self.headers,
                timeout=60.0,
            )
            meta.raise_for_status()
            media_url = meta.json().get("url", "")
            if not media_url:
                raise ValueError("no media url returned")
            # The url is Meta's CDN, which only takes the WABA's own Bearer token (Interakt's).
            # amped's "Get media from media URL" fetches it with that token and returns the bytes.
            binary = await self._client.get(
                f"{self.base_url}/media",
                params={"url": media_url},
                headers=self.headers,
                timeout=60.0,
            )
            binary.raise_for_status()
            logger.info("interakt_tp_media_downloaded", size_bytes=len(binary.content))
            return binary.content
        except httpx.HTTPError as e:
            logger.error("interakt_tp_media_download_failed", error=str(e))
            raise

    @staticmethod
    def _log_delivery(status: Dict[str, Any]) -> None:
        """One Meta status (sent/delivered/read/failed) and seconds since our send."""
        fields = {
            "wamid": status.get("id"),
            "status": status.get("status"),
            "event_at": status.get("timestamp"),
            "lag_s": delivery_lag(status.get("biz_opaque_callback_data"), status.get("timestamp")),
        }
        if status.get("status") == "failed":
            error = (status.get("errors") or [{}])[0]
            logger.warning(
                "interakt_tp_delivery_failed",
                error_code=error.get("code"),
                error_title=error.get("title"),
                error_details=(error.get("error_data") or {}).get("details"),
                **fields,
            )
        else:
            logger.info("interakt_tp_delivery_status", **fields)

    async def close(self):
        await self._client.aclose()
        logger.info("interakt_tp_provider_closed")

    # ------------------------------------------------------------------ #
    # Webhook parsing: Meta Graph Cloud API format -> normalized dict
    # ------------------------------------------------------------------ #
    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalise a Meta-Graph webhook into the shared internal message shape.

        Returns ``None`` for status/delivery events and any payload without a
        parseable inbound message.
        """
        try:
            entry = (payload.get("entry") or [{}])[0]
            change = (entry.get("changes") or [{}])[0]
            value = change.get("value", {}) or {}

            # Status webhooks aren't messages; log each with its timing (and Meta's
            # reason when a send failed after Interakt accepted it).
            if value.get("statuses"):
                for status in value["statuses"]:
                    self._log_delivery(status)
                return None

            messages = value.get("messages") or []
            if not messages:
                logger.debug("interakt_tp_no_messages_in_payload")
                return None

            message = messages[0]
            from_number = message.get("from", "")
            if not from_number:
                logger.warning("interakt_tp_payload_missing_from")
                return None
            if not from_number.startswith("+"):
                from_number = f"+{from_number}"

            msg_type = message.get("type", "text")
            parsed: Dict[str, Any] = {
                "from_number": from_number,
                "phone_number": from_number,
                "message_id": message.get("id", ""),
                "timestamp": str(message.get("timestamp", "")),
                "type": "text",
                "raw_payload": payload,
            }

            if msg_type == "text":
                parsed["text_body"] = message.get("text", {}).get("body", "")

            elif msg_type == "audio":
                audio = message.get("audio", {}) or {}
                parsed["type"] = "audio"
                media_id = audio.get("id", "")
                parsed["audio_id"] = media_id
                parsed["media_id"] = media_id
                # ``voice`` distinguishes a recorded voice note (PTT) from an
                # attached audio file; ``mime_type`` lets STT use the real format.
                parsed["voice"] = bool(audio.get("voice", False))
                parsed["mime_type"] = audio.get("mime_type", "")

            elif msg_type in ["image", "video", "document"]:
                media_obj = message.get(msg_type, {}) or {}
                parsed["type"] = msg_type
                media_id = media_obj.get("id", "")
                parsed["media_id"] = media_id
                parsed["media_url"] = media_id
                parsed["mime_type"] = media_obj.get("mime_type", "")
                parsed["caption"] = media_obj.get("caption", "")
                if msg_type == "document":
                    parsed["filename"] = media_obj.get("filename", "")

            elif msg_type == "reaction":
                reaction = message.get("reaction", {}) or {}
                parsed["type"] = "reaction"
                parsed["reaction_emoji"] = reaction.get("emoji", "")
                parsed["reaction_message_id"] = reaction.get("message_id", "")

            elif msg_type == "location":
                loc = message.get("location", {}) or {}
                parsed["type"] = "location"
                parsed["location_lat"] = loc.get("latitude")
                parsed["location_lng"] = loc.get("longitude")
                parsed["location_name"] = loc.get("name") or loc.get("address", "")

            elif msg_type == "interactive":
                interactive = message.get("interactive", {}) or {}
                interactive_type = interactive.get("type", "")

                if interactive_type == "nfm_reply":
                    # WhatsApp Flow completion (and address messages). The
                    # submitted field values live in ``response_json`` as a JSON
                    # *string*; ``flow_token`` (echoed back inside it) correlates
                    # to the originating session.
                    nfm = interactive.get("nfm_reply", {}) or {}
                    parsed["type"] = "flow_reply"
                    parsed["flow_name"] = nfm.get("name", "")
                    raw_response = nfm.get("response_json", "")
                    flow_response: Dict[str, Any] = {}
                    if raw_response:
                        try:
                            flow_response = json.loads(raw_response)
                        except (ValueError, TypeError):
                            logger.warning("interakt_tp_nfm_reply_bad_json")
                            flow_response = {"_raw": raw_response}
                    parsed["flow_response"] = flow_response
                    parsed["flow_token"] = flow_response.get("flow_token", "")
                else:
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    parsed["type"] = "interactive"
                    parsed["interactive_reply"] = {
                        "id": reply.get("id", ""),
                        "title": reply.get("title", ""),
                        "description": reply.get("description", ""),
                    }

            elif msg_type == "button":
                # Template quick-reply button → treated as an interactive reply
                button = message.get("button", {}) or {}
                parsed["type"] = "interactive"
                parsed["interactive_reply"] = {
                    "id": button.get("payload", ""),
                    "title": button.get("text", ""),
                }

            else:
                logger.warning("interakt_tp_unknown_message_type", message_type=msg_type)

            logger.info("interakt_tp_webhook_parsed", type=parsed["type"], phone_number=from_number)
            return parsed

        except Exception as e:
            logger.error("interakt_tp_parse_error", error=str(e), exc_info=True)
            return None
