import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Mapping, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

_SENT_AT = "sent_at="


def sent_at_stamp() -> str:
    """Our send time, for the field the provider echoes on delivery events
    (Netcore ``x-apiheader``, Meta ``biz_opaque_callback_data``)."""
    return f"{_SENT_AT}{time.time():.3f}"


def delivery_lag(stamp: Any, event_ts: Any) -> Optional[float]:
    """Seconds from our send to a delivery event, when the event echoes our stamp."""
    stamp = str(stamp or "")
    if not stamp.startswith(_SENT_AT):
        return None
    try:
        return round(float(event_ts) - float(stamp[len(_SENT_AT):]), 1)
    except (TypeError, ValueError):
        return None


class WhatsAppProviderBase(ABC):
    """Base class for all WhatsApp providers"""

    # WhatsApp list limits; MAX_LIST_ROWS is a total across ALL sections.
    MAX_LIST_SECTIONS = 10
    MAX_LIST_ROWS = 10

    # True where ``send_carousel`` really sends one. Unlike the other rich sends there is
    # no text fallback here: the caller shows the same choices as a list instead.
    supports_carousel = False

    @staticmethod
    def cap_list_sections(
        sections: List[Dict[str, Any]],
        max_sections: int = MAX_LIST_SECTIONS,
        max_rows: int = MAX_LIST_ROWS,
    ) -> List[Dict[str, Any]]:
        """Trim to WhatsApp's section limit and TOTAL row limit (over it, Meta rejects the message).

        Empty sections are dropped; row dicts pass through unformatted.
        """
        capped: List[Dict[str, Any]] = []
        budget = max_rows

        for section in (sections or [])[:max_sections]:
            if budget <= 0:
                break
            rows = (section.get("rows") or [])[:budget]
            if not rows:
                continue
            budget -= len(rows)
            capped.append({**section, "rows": rows})

        supplied = sum(len(s.get("rows") or []) for s in (sections or []))
        kept = sum(len(s["rows"]) for s in capped)
        if supplied > kept:
            logger.warning(
                "list_rows_truncated", supplied=supplied, kept=kept, dropped=supplied - kept
            )

        return capped

    @staticmethod
    def list_row(row: Dict[str, Any]) -> Dict[str, str]:
        """One list row clipped to WhatsApp limits; ``description`` only when there is one."""
        formatted = {
            "id": str(row.get("id", row.get("title", ""))).replace(" ", "_"),
            "title": str(row.get("title", ""))[:24],
        }
        description = str(row.get("description") or "")[:72]
        if description:
            formatted["description"] = description
        return formatted

    @abstractmethod
    async def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        """Verify the provider-specific webhook HMAC signature.

        Raise HTTPException(401) on failure.
        Return silently if the signature is valid or if no secret is configured.
        """
        pass

    @abstractmethod
    async def send_text(self, to: str, text: str) -> Dict[str, Any]:
        """Send text message"""
        pass
     
    @abstractmethod
    async def send_button_message(
        self,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        header: Any = None,
        footer_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send interactive button message.

        ``header`` accepts a plain string (text header) or a Meta media-header dict
        such as ``{"type": "document", "document": {"link": ..., "filename": ...}}``.
        Providers that cannot carry a header must accept and ignore it.
        """
        pass
    
    @abstractmethod
    async def send_list_message(
        self, 
        to: str, 
        body_text: str,
        button_text: str,
        sections: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Send interactive list message"""
        pass
    
    @abstractmethod
    async def download_media(self, media_id: str) -> bytes:
        """Download media file"""
        pass
    
    @abstractmethod
    async def send_document(
        self, 
        to: str, 
        document_url: str, 
        filename: str,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send document/PDF"""
        pass

    async def send_document_bytes(
        self,
        to: str,
        file_bytes: bytes,
        filename: str,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Optional: send document by uploading raw bytes to provider.

        Default implementation raises NotImplementedError so providers can
        implement optimized upload paths when available.
        """
        raise NotImplementedError("send_document_bytes not implemented for this provider")
    
    @abstractmethod
    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse webhook payload"""
        pass

    @abstractmethod
    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send template message"""
        pass

    async def send_typing_indicator(self, to: str, message_id: str) -> None:
        """Signal to the user that the bot is processing. No-op by default."""
        pass

    async def mark_as_read(self, message_id: str) -> None:
        """Mark an inbound message as read (blue ticks). No-op by default."""
        pass

    # ------------------------------------------------------------------ #
    # Optional rich capabilities. Meta-Graph providers (e.g. interakt_tp)
    # override these with native interactive payloads. The defaults below
    # GRACEFULLY DEGRADE to a plain text message via ``self.send_text`` so a
    # provider whose API can't represent the rich type never drops the turn.
    # Degradation is logged (``*_degraded_to_text``) so it's observable.
    # ------------------------------------------------------------------ #
    async def upload_media(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str = "",
    ) -> str:
        """Optional: upload media bytes to the provider and return a media id.

        No text fallback exists for an upload; callers of ``send_document`` /
        ``send_audio`` should fall back to sending by public ``link=`` instead.
        """
        raise NotImplementedError("upload_media not implemented for this provider")

    async def send_image(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an image by URL or media id. Default degrades to text."""
        logger.warning("send_image_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(to, "\n\n".join(p for p in (caption, media) if p))

    async def send_video(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a video by public URL or media id. Default degrades to text."""
        logger.warning("send_video_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(to, "\n\n".join(p for p in (caption, media) if p))

    async def send_sticker(
        self, to: str, media: str, caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a webp sticker by URL or media id. ``caption`` is ignored (WhatsApp disallows it)."""
        logger.warning("send_sticker_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(to, media)

    async def send_cta_url(
        self,
        to: str,
        body_text: str,
        display_text: str,
        url: str,
        header: Any = None,
        footer_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Interactive CTA-URL button. Default degrades to text with the link inline."""
        logger.warning("send_cta_url_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(to, f"{body_text}\n\n{display_text}: {url}")

    async def send_location_request(self, to: str, body_text: str) -> Dict[str, Any]:
        """Ask the user to share their location. Default degrades to a text prompt."""
        logger.warning("send_location_request_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(
            to, f"{body_text}\n\n📍 Share your location via the 📎 attachment menu."
        )

    async def send_carousel(
        self, to: str, body_text: str, cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Send an interactive media carousel of Meta ``cards`` (see ``choices.carousel_cards``)."""
        raise NotImplementedError("send_carousel not implemented for this provider")

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
        footer_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a WhatsApp Flow. Default degrades to the body text so the turn is not lost.

        A multi-screen form has no text equivalent; providers without Flow support
        should ideally have the caller send an alternative (e.g. a link or list).
        """
        logger.warning("send_flow_degraded_to_text", provider=type(self).__name__)
        return await self.send_text(to, body_text)

