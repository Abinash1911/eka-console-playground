from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.bridge import choices as ch
from app.models.whatsapp import IncomingMessage
from app.services.whatsapp.providers.base_provider import WhatsAppProviderBase
from app.services.session_manager import SessionManager
from app.core.logging import get_logger


class BaseWhatsAppApp(ABC):
    """
    Base interface for WhatsApp-facing "apps" that sit behind
    the common webhook / provider layer.

    This keeps WhatsApp provider usage and session handling consistent
    across different bots (e.g. scribe, medassist).
    """

    def __init__(
        self,
        whatsapp: WhatsAppProviderBase,
        session_manager: SessionManager,
        bot_key: str,
    ) -> None:
        self.whatsapp = whatsapp
        self.session_manager = session_manager
        self.bot_key = bot_key
        self.logger = get_logger(self.__class__.__name__)

    def _session_id_for(self, incoming: IncomingMessage) -> str:
        """
        Build a session identifier for this bot.

        Key format:
          - With agent_id: "{bot_key}:{agent_id}:{from_number}"
            Isolates sessions per business tenant — two hospitals using the
            same bot but different agent_ids never share state, even if the
            same user phones both.
          - Without agent_id: "{bot_key}:{from_number}"
            Used by bots that have no tenant concept (e.g. scribe).
        """
        if incoming.agent_id:
            return f"{self.bot_key}:{incoming.agent_id}:{incoming.from_number}"
        return f"{self.bot_key}:{incoming.from_number}"

    async def get_or_create_session(self, incoming: IncomingMessage) -> Any:
        """
        Helper for bots that want a per-conversation session without
        duplicating the boilerplate.
        """
        session_id = self._session_id_for(incoming)
        session = await self.session_manager.get_session(session_id)
        is_new = session is None

        if not session:
            session = await self.session_manager.create_session(session_id)

        return session, is_new

    async def send_text(self, to: str, text: str) -> None:
        """Send plain text via the underlying WhatsApp provider."""
        await self.whatsapp.send_text(to, text)

    async def _try_carousel(self, to: str, body: str, slides: list[ch.Slide], token: str) -> bool:
        """Send the slides as a carousel. False if WhatsApp refused it, so the list goes out instead."""
        try:
            await self.whatsapp.send_carousel(to, body, ch.carousel_cards(slides, token))
        except httpx.HTTPStatusError as e:
            if not 400 <= e.response.status_code < 500:
                raise
            self.logger.warning(
                "carousel_send_fallback_list",
                status=e.response.status_code,
                response_body=e.response.text[:200],
            )
            return False
        self.logger.info("carousel_sent", cards=len(slides))
        return True

    async def send_choices(
        self,
        to: str,
        body: str,
        choices: list[ch.Choice],
        *,
        token: str,
        button: str,
        offset: int = 0,
        extra_rows: tuple = (),
        slides: tuple = (),
    ) -> None:
        """Send choices as a carousel (cards with images, where the provider can), else as
        reply buttons when they fit, else one page of a list.

        Row ids carry ``token`` and the option's index in the full list, so a tap on
        any page resolves without stored state (see ``app.bridge.choices``). If the
        provider rejects the message, the full list goes out as numbered text instead.
        """
        body = body or "Please choose an option:"
        if len(body) > ch.LIST_BODY_MAX:
            await self.send_text(to, body)
            body = "Please choose an option:"

        if (
            slides
            and not offset
            and not extra_rows
            and getattr(self.whatsapp, "supports_carousel", False)
            and ch.fits_carousel(list(slides), body)
            and await self._try_carousel(to, body, list(slides), token)
        ):
            return

        as_buttons = not offset and not extra_rows and ch.fits_buttons(choices, body)
        try:
            if as_buttons:
                buttons = [{"id": f"{token}.{i}", "title": c.title} for i, c in enumerate(choices)]
                await self.whatsapp.send_button_message(to, body, buttons)
            else:
                await self.whatsapp.send_list_message(
                    to=to,
                    body_text=body,
                    button_text=ch.clip(button, ch.BUTTON_MAX),
                    sections=ch.list_sections(choices, token, button, offset, extra_rows),
                )
        except httpx.HTTPStatusError as e:
            if not 400 <= e.response.status_code < 500:
                raise
            self.logger.warning(
                "choice_send_fallback_text",
                status=e.response.status_code,
                response_body=e.response.text[:200],
            )
            await self.send_text(to, f"{body}\n\n{ch.numbered(choices)}")
            return

        self.logger.info(
            "choice_list_sent",
            total=len(choices),
            offset=offset,
            as_buttons=as_buttons,
            with_subtext=sum(1 for c in choices if c.description),
        )

    async def send_buttons(
        self,
        to: str,
        body_text: str,
        options: list[str],
        header: Any = None,
        footer: str | None = None,
        button: str = "View options",
    ) -> None:
        """
        Send bridge-made options (consent, session choice, suggestions) as buttons or a list.

        <=3 short options -> WhatsApp quick-reply buttons
        up to 10 options  -> list (a long label keeps its detail in the row subtext)
        >10 options       -> plain numbered text fallback

        Row ids are the option's position ("0", "1", …) — ``_match_choice`` relies on it.
        ``header`` (a text string or a media-header dict such as
        ``{"type": "document", "document": {...}}``) and ``footer`` only ride the
        quick-reply branch — WhatsApp lists take text headers only and the plain-text
        fallback has nowhere to put either. They are dropped with a log otherwise.
        """
        if not options:
            await self.send_text(to, body_text)
            return

        fits_button = all(len(opt) <= ch.BUTTON_MAX for opt in options)

        if len(options) <= 3 and fits_button:
            # All labels fit in a quick-reply button — no truncation needed
            buttons = [{"id": str(i), "title": opt} for i, opt in enumerate(options)]
            await self.whatsapp.send_button_message(
                to, body_text, buttons, header=header, footer_text=footer
            )
            return

        if header or footer:
            # Too many/too long options for quick replies — the attachment or footer
            # can't travel with a list or numbered text, so say so loudly.
            self.logger.warning(
                "send_buttons_header_dropped",
                option_count=len(options),
                had_header=bool(header),
                had_footer=bool(footer),
            )

        if len(options) <= ch.LIST_ROWS:
            rows = [ch.row(ch.from_label(opt), str(i)) for i, opt in enumerate(options)]
            await self.whatsapp.send_list_message(
                to=to,
                body_text=body_text,
                button_text=ch.clip(button, ch.BUTTON_MAX),
                sections=[{"title": ch.clip(button, ch.TITLE_MAX), "rows": rows}],
            )

        else:
            # Too many for one list and no paging state here — show them numbered so
            # the user can reply with a number.
            numbered = "\n".join(f"{i + 1}. {opt}" for i, opt in enumerate(options))
            await self.send_text(to, f"{body_text}\n\n{numbered}")

    @abstractmethod
    async def run(self, incoming: IncomingMessage) -> None:
        """
        Main entrypoint for handling an incoming WhatsApp message that
        has already been normalised into IncomingMessage.
        """

        raise NotImplementedError

