import asyncio
import uuid
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Optional

import pytz

from app.bridge.base import BaseWhatsAppApp
from app.bridge.choices import DATES, MORE, Tap, is_choice_id, page_bounds, parse_row_id, reply_text
from app.bridge.medassist import presenter
from app.bridge.medassist.elicitation import (
    DoctorOption,
    match_card,
    match_date,
    match_doctor,
    match_pill,
    match_time,
    pending_from_dict,
    pending_to_dict,
    PendingCard,
    PendingElicitation,
)
from app.bridge.medassist.exceptions import (
    MedassistFileUploadError,
    MedassistSessionExpired,
    MedassistSessionNotFound,
)
from app.bridge.medassist import consent as cs
from app.bridge.medassist import template_session as ts
from app.models.whatsapp import IncomingMessage
from app.core.config import get_settings
from app.core.logging import bind_turn_context
from app.services import journey_state
from app.services.clients.medassist_client import (
    MedassistClient,
    MedassistResponse,
    MedassistSessionCreated,
)
from app.services.clients import dev_console_client


class MedassistBridge(BaseWhatsAppApp):
    """
    WhatsApp bridge for the Medassist bot.

    Forwards text and audio messages to the medassist HTTP streaming API,
    accumulates the streamed response, and replies via WhatsApp.
    Sessions are persisted per phone number in Redis.
    """

    def __init__(
        self,
        *args,
        medassist_client: MedassistClient,
        agent_id: str = "",
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
        consent_req: bool = False,
        consent_template: dict | None = None,
        consent_version: str = "",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._client = medassist_client
        self._agent_id = agent_id
        self._byoa_secret = byoa_secret
        self._byoa_kid = byoa_kid
        self._byoa_iss = byoa_iss
        self._consent_req = bool(consent_req)
        self._consent_template = consent_template or {}
        self._consent_version = consent_version or ""
        # Set on the turn consent is granted, to the user's ORIGINAL first message
        # (captured when the consent loop began). run() opens the new session on this
        # instead of the "I agree" tap. Per-message instance, so no reset needed.
        self._consent_opening: str | None = None

    _IGNORED_TYPES = {"message_api_failed", "message_delivered", "message_read", "message_sent"}
    _RESET_COMMANDS = {"reset", "/reset", "new session", "start over", "restart"}
    _DELETE_COMMAND = "delete me"
    # The confirm buttons carry the action in their ids, so no pending state is stored.
    _DELETE_CONFIRM_ID = "delete_me_confirm"
    _DELETE_CANCEL_ID = "delete_me_cancel"
    _MORE_WORDS = {"more", "show more"}
    # A second tap on the same row while the first is still being handled is ignored.
    _TAP_DEDUPE_TTL_S = 15
    # Providers retry undelivered webhooks; one wamid is handled once within this window.
    _INBOUND_DEDUPE_TTL_S = 600
    # What matrix's chat upload takes; anything else is answered here, not sent to the agent.
    _UPLOAD_TYPES = {"image/jpeg", "image/png", "application/pdf"}
    _MAX_UPLOAD_BYTES = 2 * 1024 * 1024
    _FILE_REJECTED_TEXT = (
        "I can read photos (JPEG or PNG) and PDFs up to 2 MB. "
        "Please send it in one of those formats."
    )
    # Leading bytes that identify an upload type when the provider sends no mime type.
    _FILE_SIGNATURES = (
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\x89PNG", "image/png"),
        (b"%PDF", "application/pdf"),
    )

    @staticmethod
    def _journey_triggers() -> set[str]:
        """Lowercased set of journey trigger words from JOURNEY_TRIGGER_WORDS.

        Must be kept in sync with the triggers configured in Turn.
        """
        raw = get_settings().JOURNEY_TRIGGER_WORDS or ""
        return {w.strip().lower() for w in raw.split(",") if w.strip()}

    @staticmethod
    def _journey_start_map() -> dict[str, str]:
        """Parse JOURNEY_START_MAP ("label:journey_name,...") → {label: journey_name}.

        Labels lowercased. Maps a pill/trigger label to a journey NAME, which is
        resolved to a uuid at runtime via the Stacks API (no hardcoded uuids). A
        raw uuid value is still accepted for backward compatibility.
        """
        raw = get_settings().JOURNEY_START_MAP or ""
        out: dict[str, str] = {}
        for pair in raw.split(","):
            if ":" not in pair:
                continue
            label, target = pair.split(":", 1)
            label, target = label.strip().lower(), target.strip()
            if label and target:
                out[label] = target
        return out

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        return len(value) == 36 and value.count("-") == 4

    @staticmethod
    def _trigger_candidates(incoming: IncomingMessage) -> set[str]:
        """Normalized strings on this message that could match a journey trigger:
        the typed text, and (for a tapped pill/quick-reply) the interactive
        reply's id and title.
        """
        candidates: set[str] = set()
        if incoming.type == "text" and incoming.text_body:
            candidates.add(incoming.text_body.strip().lower())
        reply = incoming.interactive_reply or {}
        for key in ("id", "title"):
            val = reply.get(key)
            if val:
                candidates.add(str(val).strip().lower())
        return candidates

    async def _maybe_start_journey_via_api(self, incoming, candidates: set[str]) -> None:
        """Start a pill-triggered journey via the Turn Stacks API.

        Maps the matched label to a journey NAME (JOURNEY_START_MAP), resolves the
        name to a uuid via the Stacks API, and starts it. No-op unless the provider
        supports start_journey and a mapping exists.
        """
        start_map = self._journey_start_map()
        if not start_map:
            return
        provider = getattr(self, "whatsapp", None)
        if provider is None or not hasattr(provider, "start_journey"):
            return
        target = next((start_map[c] for c in candidates if c in start_map), None)
        if not target:
            return
        uuid = target if self._looks_like_uuid(target) else await self._resolve_journey_uuid(target)
        if not uuid:
            self.logger.warning(
                "journey_uuid_unresolved", phone_number=incoming.from_number, journey=target,
            )
            return
        self.logger.info(
            "journey_api_start_requested",
            phone_number=incoming.from_number, journey=target, journey_uuid=uuid,
        )
        await provider.start_journey(uuid, incoming.from_number)

    async def _resolve_journey_uuid(self, journey_name: str) -> Optional[str]:
        """Resolve a journey NAME to its uuid via the Stacks API (GET /v1/stacks).

        Returns None if the provider can't list stacks or no journey matches the
        name (case-insensitive). Keeps uuids out of config.
        """
        lister = getattr(getattr(self, "whatsapp", None), "list_stacks", None)
        if lister is None:
            return None
        target = journey_name.strip().lower()
        for stack in await lister():
            if (stack.get("name") or "").strip().lower() == target and stack.get("uuid"):
                return stack["uuid"]
        return None

    async def run(self, incoming: IncomingMessage) -> None:
        # Status events (delivery/read receipts) first — never treat them as
        # journey traffic or fire an ack for them.
        if incoming.type in self._IGNORED_TYPES:
            self.logger.debug("medassist_ignoring_status_event", type=incoming.type)
            return

        if incoming.message_id and not await self._claim(
            f"wa:in:{self._agent_id}:{incoming.message_id}", self._INBOUND_DEDUPE_TTL_S
        ):
            self.logger.info("inbound_duplicate_skipped", type=incoming.type)
            return

        settings = get_settings()
        normalized_text = (
            incoming.text_body.strip().lower()
            if incoming.type == "text" and incoming.text_body
            else None
        )

        # Reset command is the escape hatch — always available, runs before the
        # mute guard so a user can break out of anything by typing "reset".
        if normalized_text in self._RESET_COMMANDS:
            await self._reset_session(incoming)
            return

        # "delete me" and its confirm taps — also ahead of the mute and consent gates.
        if await self._handle_delete_me(incoming, normalized_text):
            return

        # Journey mute: Turn stamps every inbound with its journey ownership. A
        # journey owns this turn iff author.journey_uuid is set AND the chat isn't
        # CLOSED. While owned we stay silent (no ack, no LLM, no send) so the user
        # doesn't get double replies, and accumulate the answer for later context.
        # When the journey ends, Turn drops journey_uuid or flips chat.state to
        # CLOSED on the very next inbound, so the agent takes over automatically —
        # no Redis flag, no TTL, no beacon.
        if settings.JOURNEY_MUTE_ENABLED:
            journey_owns = bool(incoming.journey_uuid) and incoming.chat_state != "CLOSED"
            if journey_owns:
                self.logger.info("journey_muted", phone_number=incoming.from_number, type=incoming.type)
                # Still mark the message read + show typing (logs turn_io_mark_read)
                # so journey answers get blue ticks like normal messages, even
                # though the agent stays silent and the journey does the replying.
                if incoming.message_id:
                    try:
                        await self.whatsapp.send_typing_indicator(
                            incoming.from_number, incoming.message_id
                        )
                    except Exception:
                        pass
                if settings.JOURNEY_CONTEXT_INJECTION_ENABLED:
                    await journey_state.append_turn(
                        self.session_manager, incoming.from_number, "in",
                        self._user_text(incoming), settings.JOURNEY_DATA_TTL_SECONDS,
                    )
                return

        # Trigger word starts a journey — this is message #1, which does not yet
        # carry journey_uuid (the journey isn't running until Turn/the API starts
        # it). Suppress the agent's reply to the trigger itself. Matches a typed
        # word OR a tapped pill/quick-reply (interactive reply id or title).
        if settings.JOURNEY_MUTE_ENABLED:
            candidates = self._trigger_candidates(incoming)
            matched = self._journey_triggers() & candidates
            if matched:
                self.logger.info(
                    "journey_trigger_word", phone_number=incoming.from_number, word=next(iter(matched)),
                )
                # For a PILL (interactive reply), Turn's native text trigger won't
                # fire, so start the journey via the Stacks API. Typed text is left
                # to Turn's native trigger (so the two never double-start).
                if incoming.type == "interactive":
                    await self._maybe_start_journey_via_api(incoming, candidates)
                return

        if settings.THINKING_ACK_ENABLED:
            asyncio.create_task(self._send_thinking_ack(incoming))

        session, _is_new = await self.get_or_create_session(incoming)
        ctx = session.context or {}
        session_id = ctx.get("medassist_session_id")
        # The resume path: this turn belongs to a matrix session that already
        # exists. Binding it here is what puts `sid` on every line of the turn,
        # which is the key the funnel joins on across matrix and scribesnap.
        # The creation paths bind in _create_and_store_session instead.
        bind_turn_context(sid=session_id)

        if not session_id:
            # Consent gate: an agent that requires consent gets no matrix session for
            # this user until they've explicitly accepted. Runs first — a user with no
            # session has nothing to resume anyway.
            proceed, ctx, known_sessions = await self._consent_gate(incoming, ctx)
            if not proceed:
                return

            # No active session. A prior template may have reset the cache, so the
            # user must first pick which session to resume (or start new).
            if ctx.get("session_choice_state") == "awaiting_choice":
                # This inbound is the button tap resolving the earlier prompt.
                await self._resolve_session_choice(incoming, ctx)
                return
            if await self._maybe_prompt_session_choice(incoming, ctx, sessions=known_sessions):
                return

            # Nothing to choose from (organic first message, or a returning user whose
            # session expired) — auto-create and route THIS message to the LLM.
            created = await self._create_and_store_session(incoming, ctx)
            session_id = created.session_id
            # Keep the local ctx in sync with what _create_and_store_session persisted,
            # so a later _update_pending()/update_session() with this ctx doesn't write
            # back a stale copy and wipe the just-stored session id (which would make
            # the very next message re-enter session selection).
            ctx = {**ctx, "medassist_session_id": session_id}

            # Do NOT send the canonical welcome here: WhatsApp users almost always open
            # with a real message (an expired-session return would otherwise lose it
            # behind a greeting). Fall through so this message goes to the LLM — a new
            # session with the user's message as its first turn. If the message carries
            # no usable content, _build_payload handles that below.

        # Check for a pending elicitation — try to handle without LLM first
        pending_data = ctx.get("pending_elicitation")
        if pending_data:
            pending = pending_from_dict(pending_data)
            if await self._handle_pending(incoming, ctx, session_id, pending):
                return

            # No match — clear pending and let LLM handle it with context
            self.logger.info(
                "medassist_elicitation_no_match",
                component=pending.component,
                user_text=self._user_text(incoming),
            )
            ctx = await self._clear_pending(incoming, ctx)
            declined_payload = self._build_declined_payload(incoming, pending)
            if declined_payload is not None:
                response = await self._chat_with_retry(incoming, session_id, declined_payload, ctx)
                await self._reply(incoming, ctx, session_id, response)
                return

        if self._consent_opening is not None:
            # First turn out of the consent loop: open on the user's captured first
            # message (empty → the LLM just greets), never the "I agree" tap.
            payload = self._build_chat_payload(self._consent_opening)
        else:
            payload = self._build_payload(incoming)
        if payload is None:
            await self.send_text(
                incoming.from_number,
                "I can only process text, voice, photos, and location messages.",
            )
            return

        # Journey context injection: this is the first agent turn after a journey
        # released (ownership dropped). Finalize the accumulated Q&A and prepend it
        # as plain context so the agent continues informed. Only for text turns.
        if settings.JOURNEY_CONTEXT_INJECTION_ENABLED and payload.get("ct") == "text":
            # Interruption = the journey closed for a reason OTHER than completion
            # (e.g. timeout). Clean completion closes carry "...completion" and are
            # NOT interruptions. The exact timeout reason string is unconfirmed, so
            # this stays off for every close we've observed and only trips on a
            # genuine non-completion reason.
            reason = (incoming.chat_state_reason or "").strip()
            interrupted = (
                bool(incoming.journey_uuid)
                and incoming.chat_state == "CLOSED"
                and bool(reason)
                and "completion" not in reason.lower()
            )
            ctx_str = await journey_state.take_context(self.session_manager, incoming.from_number)
            if ctx_str is None and (
                interrupted or await journey_state.has_buffer(self.session_manager, incoming.from_number)
            ):
                await journey_state.build_and_store_context(
                    self.session_manager, incoming.from_number,
                    settings.JOURNEY_DATA_TTL_SECONDS, interrupted=interrupted,
                )
                ctx_str = await journey_state.take_context(self.session_manager, incoming.from_number)
            if ctx_str:
                self.logger.info(
                    "journey_context_injected",
                    phone_number=incoming.from_number, interrupted=interrupted,
                )
                payload = {
                    **payload,
                    "data": {**payload["data"], "text": f"{ctx_str}\n\n{payload['data']['text']}"},
                }

            # Flow Results probe (log-only): best-effort, when the releasing inbound
            # still carries the journey/session ids (Pattern A). Never blocks the reply.
            if (
                settings.JOURNEY_FLOW_RESULTS_PROBE
                and incoming.journey_uuid
                and incoming.journey_session_id
            ):
                fetch = getattr(getattr(self, "whatsapp", None), "fetch_flow_results", None)
                if fetch:
                    asyncio.create_task(
                        fetch(incoming.journey_uuid, incoming.journey_session_id)
                    )

        response = await self._chat_with_retry(incoming, session_id, payload, ctx)
        await self._reply(incoming, ctx, session_id, response)

    # ------------------------------------------------------------------
    # Thinking acknowledgment
    # ------------------------------------------------------------------

    async def _send_thinking_ack(self, incoming: IncomingMessage) -> None:
        """Fire-and-forget: mark the message as read + show a typing indicator.

        Fires for every message except status events and reset commands. No filler
        text is sent — the typing indicator alone signals the bot is working.
        """
        if incoming.type in self._IGNORED_TYPES:
            return
        if incoming.type == "text" and incoming.text_body and incoming.text_body.strip().lower() in self._RESET_COMMANDS:
            return
        if not incoming.message_id:
            return

        try:
            await self.whatsapp.send_typing_indicator(incoming.from_number, incoming.message_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Elicitation helpers
    # ------------------------------------------------------------------

    def _user_text(self, incoming: IncomingMessage) -> str:
        if incoming.type == "text" and incoming.text_body:
            return incoming.text_body
        if incoming.type == "interactive" and incoming.interactive_reply:
            reply = incoming.interactive_reply
            reply_id = reply.get("id", "")
            # Non-numeric id means it's a semantic value set by _send_response (e.g. option value);
            # a choice-list row id is opaque, so the option's text stands in for it.
            if reply_id and not reply_id.isdigit() and not is_choice_id(reply_id):
                return reply_id
            return reply_text(reply)
        return ""

    def _resolve_elicitation_params(self, user_text: str, pending) -> Optional[dict]:
        """Map user text to tool_params for the pending elicitation, or None if no match."""
        if not user_text:
            return None

        if pending.component in ("pills", "multi"):
            value = match_pill(user_text, pending.options)
            if value:
                return self._pill_params(pending, value)

        elif pending.component == "card":
            card = match_card(user_text, pending.cards)
            if card:
                return self._card_params(pending, card)

        elif pending.component in ("mobile_number", "otp", "email_address"):
            value = user_text.strip()
            if not value:
                return None
            _defaults = {"mobile_number": "mobile_number", "otp": "otp", "email_address": "email_address"}
            user_field = pending.schema_fields[0] if pending.schema_fields else _defaults[pending.component]
            params = dict(pending.input_fields)  # fixed fields (e.g. {"method": "mobile"})
            if pending.mcp_meta_wrapper:
                # Synapse SDK convention: user value goes under mcp_meta_fields key
                # medassist maps this to the tool's `meta` param
                params["mcp_meta_fields"] = {user_field: value}
            else:
                params[user_field] = value
            return params

        return None

    @staticmethod
    def _pill_params(pending: PendingElicitation, value: str) -> dict:
        # MCP pills read the pick from the request _meta, the way the widget sends it.
        if pending.mcp_meta_wrapper:
            return {"mcp_meta_fields": {"value": value}}
        return {"value": value}

    @staticmethod
    def _card_params(pending: PendingElicitation, card: PendingCard) -> dict:
        if card.tool_result:
            return {"tool_result": card.tool_result}
        # Generic resolution: for each required field, check selected card first,
        # then fall back to the full input_data from the server.
        selected = {"card_id": card.card_id, "title": card.title}
        params: dict = {}
        for field_name in (pending.schema_fields or ["card_id"]):
            val = selected.get(field_name)
            if val is None:
                val = pending.input_data.get(field_name)
            if val is not None:
                params[field_name] = val
        return params or {"card_id": card.card_id}

    # ------------------------------------------------------------------
    # Choice lists: taps, paging and doctor_card steps
    # ------------------------------------------------------------------

    async def _handle_pending(
        self, incoming: IncomingMessage, ctx: dict, session_id: str, pending: PendingElicitation
    ) -> bool:
        """Answer a pending elicitation without the agent when the message picks something.

        A tap on one of our lists resolves by row id; typed "more" pages; other text is
        matched against the current list. False → the agent gets it as a declined tool.
        """
        reply = incoming.interactive_reply or {}
        tap = parse_row_id(reply.get("id", ""))
        if tap is not None:
            return await self._handle_tap(incoming, ctx, session_id, pending, tap, reply["id"])

        user_text = self._user_text(incoming)
        current = presenter.current_list(pending)
        if current is not None and user_text.strip().lower() in self._MORE_WORDS:
            _, end, has_more = page_bounds(len(current.choices), pending.page_offset, len(current.extra_rows))
            paged = replace(pending, page_offset=end if has_more else 0)
            await self._write_pending(incoming, ctx, paged)
            await self._send_list(incoming.from_number, current, offset=paged.page_offset)
            return True

        if pending.component == "doctor_card":
            return await self._handle_doctor_text(incoming, ctx, session_id, pending, user_text)

        tool_params = self._resolve_elicitation_params(user_text, pending)
        if tool_params is None:
            return False
        await self._submit(incoming, ctx, session_id, pending, tool_params)
        return True

    async def _handle_tap(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        session_id: str,
        pending: PendingElicitation,
        tap: Tap,
        row_id: str,
    ) -> bool:
        if not await self._claim(
            f"wa:tap:{self._session_id_for(incoming)}:{row_id}", self._TAP_DEDUPE_TTL_S
        ):
            self.logger.info("choice_tap_duplicate", row_id=row_id)
            return True

        tapped = presenter.find_list(pending, tap.token)
        if tapped is None:
            current = presenter.current_list(pending)
            if current is None:
                return False
            # A list from an earlier turn: re-show the live one rather than guess what it meant.
            self.logger.info("choice_tap_stale", component=pending.component)
            body = "That list is no longer active — please pick again."
            await self._send_list(incoming.from_number, current, body=f"{body}\n\n{current.body}".strip())
            return True

        if tap.kind == MORE:
            await self._send_list(incoming.from_number, tapped, offset=tap.n)
            return True
        if tap.kind == DATES:
            await self._show(incoming, ctx, presenter.back_to_dates(pending))
            return True
        if not 0 <= tap.n < len(tapped.items):
            return False
        self.logger.info("choice_tap_resolved", step=tapped.step, index=tap.n)
        await self._pick(incoming, ctx, session_id, pending, tapped.step, tapped.items[tap.n])
        return True

    async def _handle_doctor_text(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        session_id: str,
        pending: PendingElicitation,
        user_text: str,
    ) -> bool:
        """A typed answer on a doctor_card, matched against the current step."""
        if not user_text:
            return False
        current = presenter.current_list(pending)
        doctor = presenter.selected_doctor(pending)

        # Slot pills from the previous build read "Mon, 06 Oct at 10:30" (remove after a release).
        day, _, time = user_text.partition(" at ")
        if time and doctor:
            picked_date = match_date(day, [d["date"] for d in doctor.dates])
            slot = match_time(time, presenter.slots_on(doctor, picked_date)) if picked_date else None
            if slot:
                dated = presenter.pick_date(pending, picked_date)
                await self._pick(incoming, ctx, session_id, dated, presenter.SLOT, slot)
                return True

        if current is None or current.step == presenter.DATE:
            picked = match_date(user_text, current.items) if current else None
            if picked:
                await self._pick(incoming, ctx, session_id, pending, presenter.DATE, picked)
                return True
            # A date that isn't on the list (or no list at all): the agent checks it.
            typed_date = self._parse_free_date(user_text)
            if typed_date and doctor:
                await self._ask_agent(
                    incoming, ctx, session_id,
                    f"{self._doctor_marker(doctor)} [DATE SELECTED: preferred_date={typed_date}]",
                )
                return True
            return False

        if current.step == presenter.DOCTOR:
            picked = match_doctor(user_text, current.items)
        else:
            picked = match_time(user_text, current.items)
        if picked is None:
            return False
        await self._pick(incoming, ctx, session_id, pending, current.step, picked)
        return True

    async def _pick(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        session_id: str,
        pending: PendingElicitation,
        step: str,
        item: Any,
    ) -> None:
        """Act on a picked item: answer the tool, move to the next doctor_card step, or
        hand the agent what the bridge can't finish (unloaded dates, the booking itself)."""
        if step == presenter.OPTION:
            if pending.component == "card":
                params = self._card_params(pending, item)
            else:
                params = self._pill_params(pending, item.get("value") or item.get("label", ""))
            await self._submit(incoming, ctx, session_id, pending, params)

        elif step == presenter.DOCTOR:
            picked = presenter.pick_doctor(pending, item)
            if presenter.current_list(picked) is not None:
                await self._show(incoming, ctx, picked)
            else:
                # No availability on the card — the agent fetches it for this doctor.
                await self._ask_agent(incoming, ctx, session_id, self._doctor_marker(item))

        elif step == presenter.DATE:
            picked = presenter.pick_date(pending, item)
            if presenter.doctor_step(picked) == presenter.SLOT:
                await self._show(incoming, ctx, picked)
            else:
                # That date's slots aren't loaded — the agent fetches them.
                doctor = presenter.selected_doctor(pending)
                await self._ask_agent(
                    incoming, ctx, session_id,
                    f"{self._doctor_marker(doctor)} [DATE SELECTED: preferred_date={item}]",
                )

        else:
            doctor = presenter.selected_doctor(pending)
            preferred_date = pending.doctor_accumulated.get("preferred_date", "")
            self.logger.info("doctor_slot_selected", date=preferred_date, slot=item, doctor=doctor.name)
            await self._ask_agent(
                incoming, ctx, session_id,
                f"[SLOT SELECTED: {doctor.name} at {doctor.hospital_name}, "
                f"preferred_date={preferred_date}, preferred_slot_time={item}, "
                f"doctor_id={doctor.doctor_id}, hospital_id={doctor.hospital_id}]",
            )

    async def _submit(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        session_id: str,
        pending: PendingElicitation,
        tool_params: dict,
    ) -> None:
        """Answer the pending tool: by tool_callback when it supports one, else tell the agent."""
        if pending.status != "progress":
            value = tool_params.get("value") or (tool_params.get("mcp_meta_fields") or {}).get("value", "")
            await self._ask_agent(incoming, ctx, session_id, f"[SELECTION: {value}]")
            return
        response = await self._call_tool_callback_with_retry(incoming, ctx, session_id, pending, tool_params)
        if response.is_error:
            response = await self._recover_from_tool_error(incoming, session_id, response, ctx)
        await self._reply(incoming, ctx, session_id, response)

    async def _ask_agent(self, incoming: IncomingMessage, ctx: dict, session_id: str, text: str) -> None:
        """Send the agent a context marker for a pick; the pending it answered is done."""
        ctx = await self._clear_pending(incoming, ctx)
        response = await self._chat_with_retry(incoming, session_id, self._build_chat_payload(text), ctx)
        await self._reply(incoming, ctx, session_id, response)

    async def _show(self, incoming: IncomingMessage, ctx: dict, pending: PendingElicitation) -> None:
        """Persist a doctor_card step the bridge moved to, and show that step."""
        await self._write_pending(incoming, ctx, pending)
        current = presenter.current_list(pending)
        if current is not None:
            await self._send_list(incoming.from_number, current)
        else:
            await self.send_text(incoming.from_number, presenter.ask_date_text(pending))

    async def _send_list(
        self, to: str, lst: presenter.ChoiceList, offset: int = 0, body: Optional[str] = None
    ) -> None:
        await self.send_choices(
            to,
            body or lst.body,
            lst.choices,
            token=lst.token,
            button=lst.button,
            offset=offset,
            extra_rows=lst.extra_rows,
            slides=lst.slides,
        )

    async def _clear_pending(self, incoming: IncomingMessage, ctx: dict) -> dict:
        ctx = {k: v for k, v in ctx.items() if k != "pending_elicitation"}
        await self.session_manager.update_session(self._session_id_for(incoming), context=ctx)
        return ctx

    @staticmethod
    def _doctor_marker(doctor: DoctorOption) -> str:
        return (
            f"[DOCTOR SELECTED: {doctor.name}, "
            f"doctor_id={doctor.doctor_id}, hospital_id={doctor.hospital_id}]"
        )

    @staticmethod
    def _parse_free_date(user_text: str) -> Optional[str]:
        """Parse a free-form date string into YYYY-MM-DD.

        Tries common formats: DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, and
        natural forms like '5 June', 'June 5', '5th June 2026'.
        Returns None if the input cannot be parsed.
        """
        from datetime import datetime as dt
        text = user_text.strip()
        formats = [
            "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
            "%Y-%m-%d",
            "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y",
            "%d %B", "%B %d", "%d %b", "%b %d",
        ]
        # Normalise ordinal suffixes: "5th" → "5", "3rd" → "3"
        import re
        cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
        for fmt in formats:
            for candidate in (cleaned, text):
                try:
                    parsed = dt.strptime(candidate, fmt)
                    # If year is missing (short formats), use current year
                    if parsed.year == 1900:
                        parsed = parsed.replace(year=date.today().year)
                    return parsed.strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return None

    async def _write_pending(
        self, incoming: IncomingMessage, ctx: dict, pending: PendingElicitation
    ) -> None:
        """Save a pending directly without a MedassistResponse."""
        new_ctx = {**ctx, "pending_elicitation": pending_to_dict(pending)}
        await self.session_manager.update_session(self._session_id_for(incoming), context=new_ctx)

    async def _call_tool_callback_with_retry(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        session_id: str,
        pending: PendingElicitation,
        tool_params: dict,
    ) -> MedassistResponse:
        try:
            return await self._client.call_tool_callback(
                session_id, self._agent_id, incoming.from_number, pending, tool_params,
                self._byoa_secret, self._byoa_kid, self._byoa_iss,
            )
        except MedassistSessionExpired:
            self.logger.info("medassist_session_recreating_on_callback", phone_number=incoming.from_number)
            created = await self._create_and_store_session(
                incoming, {k: v for k, v in ctx.items() if k not in (
                    "medassist_session_id", "pending_elicitation"
                )}
            )
            # The elicitation's message/tool don't exist in a fresh session — open with
            # the agent's welcome instead of replaying the callback. Sync ctx to the new id.
            ctx["medassist_session_id"] = created.session_id
            ctx.pop("pending_elicitation", None)
            return self._welcome_response(created)

    async def _reply(
        self, incoming: IncomingMessage, ctx: dict, session_id: str, response: MedassistResponse
    ) -> None:
        """Persist the response's pending elicitation and send it to the user.

        A finished elicitation (``response.close``) is first handed back to the agent
        as a chat turn — how the web widget closes a "success" card — and the agent's
        reply to it is what the user sees.
        """
        if response.close:
            response = await self._chat_with_retry(
                incoming, session_id, self._build_chat_payload(**response.close), ctx
            )
        if response.pending_elicitation is not None:
            # Stored and shown from the same object, so the list tokens match on the next tap.
            response = replace(
                response, pending_elicitation=presenter.normalize(response.pending_elicitation)
            )
        await self._update_pending(incoming, ctx, response)
        await self._send_response(incoming.from_number, response)

    async def _claim(self, key: str, ttl_s: int) -> bool:
        """SET NX guard: True when this caller owns ``key``. Fails open if Redis is down."""
        try:
            redis = await self.session_manager.get_redis()
            return bool(await redis.set(key, "1", nx=True, ex=ttl_s))
        except Exception as e:
            self.logger.warning("claim_failed", key=key, error=str(e))
            return True

    async def _update_pending(self, incoming: IncomingMessage, ctx: dict, response: MedassistResponse) -> None:
        """Persist or clear pending_elicitation in session based on the response."""
        new_ctx = {**ctx}
        if response.pending_elicitation is not None:
            new_ctx["pending_elicitation"] = pending_to_dict(response.pending_elicitation)
        else:
            new_ctx.pop("pending_elicitation", None)
        await self.session_manager.update_session(self._session_id_for(incoming), context=new_ctx)

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send_response(self, to: str, response: MedassistResponse) -> None:
        pending = response.pending_elicitation
        if pending is not None:
            current = presenter.current_list(pending)
            if current is not None:
                await self._send_list(to, current, body=response.text or current.body)
                return
            if pending.component == "doctor_card":
                # A doctor with nothing to pick: say so and ask for a date to check.
                ask = presenter.ask_date_text(pending)
                await self.send_text(to, f"{response.text}\n\n{ask}" if response.text else ask)
                return

        if response.options:
            await self.send_buttons(to, response.text, response.options)
        elif response.text:
            await self.send_text(to, response.text)
        else:
            await self.send_text(to, "I didn't get a response. Please try again.")

    def _build_chat_payload(self, text: str, **extra) -> dict:
        """A chat turn; ``extra`` rides in ``data`` (e.g. tool_id/tool_result to close a tool)."""
        return {
            "_id": str(uuid.uuid4()), "ev": "chat", "ct": "text", "data": {"text": text, **extra},
        }

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    async def _send_initial_message(self, to: str, initial_message: dict) -> None:
        text = initial_message.get("text", "")
        suggestions = initial_message.get("suggestions") or []
        options = [s.get("label") or s.get("value", "") for s in suggestions if isinstance(s, dict)]
        options = [o for o in options if o]
        if options:
            await self.send_buttons(to, text, options)
        elif text:
            await self.send_text(to, text)

    async def _reset_session(self, incoming: IncomingMessage) -> None:
        session_key = self._session_id_for(incoming)
        await self.session_manager.delete_session(session_key)
        await self._client.clear_cached_tokens(self._agent_id, incoming.from_number)
        self.logger.info("medassist_session_reset", phone_number=incoming.from_number)
        await self.send_text(
            incoming.from_number,
            "Your session has been reset. Send a message to start a new conversation.",
        )

    async def _handle_delete_me(self, incoming: IncomingMessage, normalized_text: str | None) -> bool:
        """'delete me' asks to confirm; only the confirm tap archives. True when handled."""
        tap_id = (incoming.interactive_reply or {}).get("id")
        if normalized_text == self._DELETE_COMMAND:
            await self.whatsapp.send_button_message(
                incoming.from_number,
                "This will delete your profile and all data (chats and related events) stored "
                "with us. This is an irreversible action. Are you sure you want to delete your profile?",
                [
                    # Reply-button titles are capped at 20 characters.
                    {"id": self._DELETE_CONFIRM_ID, "title": "Yes, delete my data"},
                    {"id": self._DELETE_CANCEL_ID, "title": "No, keep chatting"},
                ],
            )
        elif tap_id == self._DELETE_CONFIRM_ID:
            await self._delete_user(incoming)
        elif tap_id == self._DELETE_CANCEL_ID:
            await self.send_text(incoming.from_number, "Okay, your profile has not been deleted.")
        else:
            return False
        return True

    async def _delete_user(self, incoming: IncomingMessage) -> None:
        """Have dev-console delete the user, then drop everything held for it here.

        dev-console archives the number's Trinity profiles and queues archiving their
        sessions. The next message re-runs the token exchange, which finds no profile and
        mints a fresh oid, so past sessions no longer show up.
        """
        phone = incoming.from_number
        try:
            oids = await dev_console_client.delete_user(
                self._agent_id, self._client.mobile_for(phone, self._agent_id)
            )
        except Exception as e:
            self.logger.error("delete_me_failed", phone_number=phone, error=str(e))
            await self.send_text(
                phone, "Sorry, we couldn't delete your profile right now. Please try again in a few minutes."
            )
            return

        redis = await self.session_manager.get_redis()
        await self.session_manager.delete_session(self._session_id_for(incoming))
        await self._client.clear_cached_tokens(self._agent_id, phone)
        await ts.clear_t_cache(redis, self._agent_id, phone)
        await cs.clear_consent(redis, self._agent_id, phone)
        self.logger.info("medassist_user_deleted", phone_number=phone, oid_count=len(oids))
        await self.send_text(phone, "Your profile has been deleted. Continue messaging to start a fresh chat.")

    # ------------------------------------------------------------------
    # First-time consent gate
    # ------------------------------------------------------------------

    async def _consent_gate(
        self, incoming: IncomingMessage, ctx: dict
    ) -> tuple[bool, dict, list | None]:
        """Block session creation until the user has accepted the agent's consent.

        Returns ``(proceed, ctx, sessions)``:
          * ``proceed`` False → the consent message was (re-)sent; caller must return
            without touching matrix.
          * ``ctx`` is the caller's context, with the consent state stripped once the
            gate is passed.
          * ``sessions`` is the /sessions list when this call happened to fetch it, so
            the caller can reuse it for the session-choice prompt.
        """
        if not self._consent_req:
            return True, ctx, None

        phone = incoming.from_number
        redis = await self.session_manager.get_redis()

        if await cs.has_consent(redis, self._agent_id, phone, self._consent_version):
            return True, ctx, None

        options = cs.consent_options(self._consent_template)

        # Awaiting the user's answer to the one-time template we already sent.
        if ctx.get("consent_state") == cs.AWAITING_CONSENT:
            if self._is_consent_accept(incoming, options):
                # Open the session on the captured first message, not the "I agree" tap
                # ("" → the LLM just greets). Read before _grant_consent strips it.
                self._consent_opening = ctx.get("consent_first_msg") or ""
                ctx = await self._grant_consent(incoming, ctx, source="whatsapp")
                return True, ctx, None
            # Explicit "I disagree" (tap or typed) always gets the empathetic message.
            # Only other/random replies fall back to the cheap Yes/No reminder — never
            # re-sending the (paid) template.
            if self._is_consent_decline(incoming, options):
                self.logger.info(
                    "consent_declined", phone_number=phone, agent_id=self._agent_id,
                )
                await self._send_consent_decline(phone)
                return False, ctx, None
            self.logger.info(
                "consent_not_granted",
                phone_number=phone,
                agent_id=self._agent_id,
            )
            await self._send_consent_reminder(phone, options)
            return False, ctx, None

        # First contact for this agent. An existing medassist session means the user
        # predates the consent requirement — grandfather them rather than interrupt.
        sessions = await self._client.get_sessions(
            phone, self._agent_id,
            byoa_secret=self._byoa_secret, byoa_kid=self._byoa_kid, byoa_iss=self._byoa_iss,
        )
        if sessions:
            ctx = await self._grant_consent(incoming, ctx, source="grandfathered")
            return True, ctx, sessions

        # No sessions, or /sessions failed (None). Fail closed and ask — a transient
        # failure costs an existing user one extra tap; the alternative silently skips
        # consent altogether. The one-time approved template goes out here.
        new_ctx = {
            **ctx,
            "consent_state": cs.AWAITING_CONSENT,
            "consent_choice": {"options": options},
            # Remember the message that opened the loop (text/quick-reply only) so the
            # session opens on it once consent is granted. Set once — never overwritten
            # by the no/disagree/random replies that follow.
            "consent_first_msg": self._user_text(incoming),
        }
        await self.session_manager.update_session(
            self._session_id_for(incoming), context=new_ctx
        )
        await self._send_consent_prompt(phone, options)
        self.logger.info(
            "consent_prompted",
            phone_number=phone,
            agent_id=self._agent_id,
            version=self._consent_version,
            sessions_lookup_failed=sessions is None,
        )
        return False, new_ctx, None

    async def _grant_consent(
        self, incoming: IncomingMessage, ctx: dict, source: str
    ) -> dict:
        """Record the grant (Redis now, dev-console best-effort) and clear the state."""
        phone = incoming.from_number
        redis = await self.session_manager.get_redis()
        await cs.set_consent(redis, self._agent_id, phone, self._consent_version, source)
        asyncio.create_task(
            cs.record_consent_remote(self._agent_id, phone, self._consent_version, source)
        )

        new_ctx = {k: v for k, v in ctx.items() if k not in cs.CONSENT_CONTEXT_KEYS}
        if new_ctx != ctx:
            await self.session_manager.update_session(
                self._session_id_for(incoming), context=new_ctx
            )
        self.logger.info(
            "consent_granted",
            phone_number=phone,
            agent_id=self._agent_id,
            version=self._consent_version,
            source=source,
        )
        return new_ctx

    def _is_consent_accept(self, incoming: IncomingMessage, options: list[dict]) -> bool:
        """True when this inbound accepts consent — a tap on the accept pill/button, or
        a typed/tapped affirmative (``yes``/``agree``/the "I'm 18+ & I agree" button)."""
        # A reminder pill maps cleanly to an accept/decline option — honour its action.
        picked = self._match_choice(incoming, options)
        if picked is not None:
            return picked.get("action") == cs.ACTION_ACCEPT
        # Approved-template button tap (title/payload) or free text — match affirmatives.
        reply = incoming.interactive_reply or {}
        candidate = reply.get("title") or reply.get("id") or self._user_text(incoming)
        return cs.is_accept_text(candidate, self._consent_template)

    def _is_consent_decline(self, incoming: IncomingMessage, options: list[dict]) -> bool:
        """True when this inbound explicitly declines — a tap on the decline pill, or a
        typed/tapped 'no'/'I disagree'."""
        picked = self._match_choice(incoming, options)
        if picked is not None:
            return picked.get("action") == cs.ACTION_DECLINE
        reply = incoming.interactive_reply or {}
        candidate = reply.get("title") or reply.get("id") or self._user_text(incoming)
        return cs.is_decline_text(candidate, self._consent_template)

    async def _send_consent_decline(self, to: str) -> None:
        """One-time empathetic message when the user declines — plain text, no pills."""
        await self.send_text(to, cs.consent_decline_message(self._consent_template))

    async def _send_consent_prompt(self, to: str, options: list[dict]) -> None:
        """First-time prompt: the approved WhatsApp template (PDF header + Agree button).

        Falls back to a self-built interactive message when no template name is
        configured, so a mis-configured agent still asks rather than silently passing.
        """
        template_name = cs.consent_template_name(self._consent_template)
        if not template_name:
            self.logger.warning(
                "consent_template_name_missing", agent_id=self._agent_id,
            )
            await self._send_consent_reminder(to, options, include_header=True)
            return
        header = cs.consent_header(self._consent_template)
        components = [{"type": "header", "parameters": [header]}] if header else None
        await self.whatsapp.send_template(
            to,
            template_name,
            cs.consent_language(self._consent_template),
            components=components,
        )

    async def _send_consent_reminder(
        self, to: str, options: list[dict], include_header: bool = False
    ) -> None:
        """Lightweight nudge after the one-time template — text + Yes/No pills, no
        template send and (by default) no PDF header, so re-prompting stays cheap."""
        await self.send_buttons(
            to,
            cs.consent_reminder_text(self._consent_template),
            [o["label"] for o in options],
            header=cs.consent_header(self._consent_template) if include_header else None,
            footer=self._consent_template.get("footer"),
        )

    # ------------------------------------------------------------------
    # Session selection (Continue / Choose / Start new)
    # ------------------------------------------------------------------

    async def _maybe_prompt_session_choice(
        self,
        incoming: IncomingMessage,
        ctx: dict,
        sessions: list | None = None,
    ) -> bool:
        """Present the session-choice prompt if there's anything to choose from.

        Options: Continue (the template's t_sid) if a t_cache exists · one entry per
        existing session from /sessions (if any) · Start new (always). Captures this
        inbound as the user's reply, to be injected as context once they pick.

        ``sessions`` lets a caller that already fetched the list (the consent gate)
        hand it over instead of paying for a second /sessions round-trip.

        Returns True if a prompt was sent (caller should return); False when there's
        nothing to choose (no t_cache and no sessions) so the caller auto-creates.
        """
        redis = await self.session_manager.get_redis()
        t = await ts.get_t_cache(redis, self._agent_id, incoming.from_number)
        if sessions is None:
            sessions = await self._client.get_sessions(
                incoming.from_number, self._agent_id,
                byoa_secret=self._byoa_secret, byoa_kid=self._byoa_kid, byoa_iss=self._byoa_iss,
            )

        choices: list[dict] = []
        if t and t.get("t_sid"):
            choices.append({"kind": "continue", "label": "Continue", "sid": t["t_sid"]})
        # Offer the 4 most recent sessions (already sorted desc), skipping the t_sid
        # that's already the "Continue" option.
        shown = 0
        for s in (sessions or []):
            sid = s.get("sid")
            if not sid or (t and sid == t.get("t_sid")):
                continue
            choices.append({"kind": "choose", "label": self._session_choice_label(s), "sid": sid})
            shown += 1
            if shown >= 4:
                break

        if not choices:
            return False  # nothing to resume — let the caller start a new session

        choices.append({"kind": "new", "label": "Start new", "sid": None})

        new_ctx = {
            **ctx,
            "session_choice": {
                "choices": choices,
                "user_reply": self._user_text(incoming),
                "template_ctx": (t or {}).get("template_ctx"),
            },
            "session_choice_state": "awaiting_choice",
        }
        await self.session_manager.update_session(self._session_id_for(incoming), context=new_ctx)
        await self.send_buttons(
            incoming.from_number,
            self._session_choice_prompt(choices),
            [c["label"] for c in choices],
            button="View chats",
        )
        self.logger.info(
            "session_choice_prompted",
            phone_number=incoming.from_number,
            options=[c["kind"] for c in choices],
        )
        return True

    async def _resolve_session_choice(self, incoming: IncomingMessage, ctx: dict) -> None:
        """Handle the button tap that resolves an awaiting session-choice prompt."""
        stored = ctx.get("session_choice") or {}
        choices = stored.get("choices") or []
        choice = self._match_choice(incoming, choices)
        if choice is None:
            # Unrecognized tap/text — re-show the options rather than guessing.
            await self.send_buttons(
                incoming.from_number,
                self._session_choice_prompt(choices),
                [c["label"] for c in choices],
                button="View chats",
            )
            return

        base_ctx = {
            k: v for k, v in ctx.items()
            if k not in ("session_choice", "session_choice_state")
        }
        created, is_fresh = await self._session_for_choice(incoming, choice)

        stored_ctx = {
            **base_ctx,
            "medassist_session_id": created.session_id,
        }
        update_kwargs: dict = {"context": stored_ctx}
        if created.session_validity_s:
            update_kwargs["expire_seconds"] = created.session_validity_s
        await self.session_manager.update_session(self._session_id_for(incoming), **update_kwargs)

        # The user has now responded to the template, so consume the template pointer:
        # future organic returns fall back to Choose + Start new (no stale "Continue").
        redis = await self.session_manager.get_redis()
        await ts.clear_t_cache(redis, self._agent_id, incoming.from_number)

        self.logger.info(
            "session_choice_resolved",
            kind=choice.get("kind"),
            sid=created.session_id,
        )

        # A fresh session (Start new, OR a Continue/Choose whose session no longer
        # exists) opens on the message the user typed before the prompt — routed to the
        # LLM instead of a canned welcome, so their question isn't lost. Only a
        # genuinely resumed session also injects the prior template context.
        if is_fresh:
            text = stored.get("user_reply") or "Hi"
        else:
            # Continue / Choose → resume the picked session with template context + reply.
            text = (
                self._template_context_text(stored.get("template_ctx"), stored.get("user_reply"))
                or stored.get("user_reply")
                or "Hi"
            )

        response = await self._chat_with_retry(
            incoming, created.session_id,
            self._build_chat_payload(text), stored_ctx,
        )
        await self._reply(incoming, stored_ctx, created.session_id, response)

    async def _session_for_choice(
        self, incoming: IncomingMessage, choice: dict
    ) -> tuple[MedassistSessionCreated, bool]:
        """Resolve a chosen option to a session.

        Returns (created, is_fresh): Continue/Choose resume the picked session
        (is_fresh=False); Start new — or a Continue/Choose whose session 404s —
        creates a fresh one (is_fresh=True) so the caller shows the welcome instead
        of resuming.
        """
        kind = choice.get("kind")
        sid = choice.get("sid")
        if kind in ("continue", "choose") and sid:
            try:
                resumed = await self._client.get_session(
                    sid, incoming.from_number, self._agent_id,
                    byoa_secret=self._byoa_secret, byoa_kid=self._byoa_kid, byoa_iss=self._byoa_iss,
                )
                return resumed, False
            except MedassistSessionNotFound:
                self.logger.info("session_choice_not_found_creating_new", sid=sid, kind=kind)
        # New session — store it and return (mirrors the auto-create path).
        return await self._create_and_store_session(incoming, {}), True

    def _match_choice(self, incoming: IncomingMessage, choices: list[dict]) -> dict | None:
        """Map a button tap (or typed text) back to one of the offered choices.

        send_buttons assigns id=str(index) in option order, so a numeric reply id
        indexes directly; otherwise fall back to a case-insensitive label match.
        """
        reply = incoming.interactive_reply or {}
        rid = reply.get("id")
        if rid is not None and str(rid).isdigit():
            idx = int(rid)
            if 0 <= idx < len(choices):
                return choices[idx]
        target = (reply.get("title") or self._user_text(incoming) or "").strip().lower()
        for c in choices:
            if c["label"].strip().lower() == target:
                return c
        return None

    @staticmethod
    def _session_choice_label(session: dict) -> str:
        """Short label for a session in the Choose list, e.g. "chat on 24/07 4:35 pm".

        Built from ``c_ate`` (epoch) when present, else the ``c_at`` ISO string,
        shown in the agent's region timezone (UTC if the region is missing/unknown).
        Capped at 24 chars (WhatsApp list-row limit); a few chars over the 20-char
        button limit just means the picker renders as a list rather than buttons.
        """
        tz = pytz.timezone(pytz.country_timezones.get(session.get("region") or "", ["UTC"])[0])
        dt = None
        c_ate = session.get("c_ate")
        if c_ate:
            try:
                dt = datetime.fromtimestamp(int(c_ate), tz)
            except Exception:
                dt = None
        if dt is None and session.get("c_at"):
            try:
                dt = datetime.fromisoformat(
                    str(session["c_at"]).replace("Z", "+00:00")
                ).astimezone(tz)
            except Exception:
                dt = None
        if dt is None:
            return f"session {str(session.get('sid') or '')[:6]}"[:24]
        hour = dt.strftime("%I").lstrip("0") or "12"
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p").lower()
        return f"chat on {dt.strftime('%d/%m')} {hour}:{minute} {ampm}"[:24]

    @staticmethod
    def _session_choice_prompt(choices: list[dict]) -> str:
        has_resume = any(c.get("kind") in ("continue", "choose") for c in choices)
        if has_resume:
            return "You have a previous conversation. Continue it, pick another, or start fresh?"
        return "How would you like to proceed?"

    @staticmethod
    def _template_context_text(template_ctx: Optional[dict], user_reply: Optional[str]) -> str:
        """Build the first chat message: template info (if any) + the user's reply."""
        parts: list[str] = []
        if template_ctx:
            tid = template_ctx.get("template_id")
            params = template_ctx.get("template_params") or {}
            if tid:
                detail = ", ".join(f"{k}={v}" for k, v in params.items())
                parts.append(
                    f"[The user was sent the '{tid}' WhatsApp template"
                    + (f" ({detail})" if detail else "")
                    + " and has now replied.]"
                )
        if user_reply:
            parts.append(user_reply)
        return "\n".join(parts)

    async def _create_and_store_session(
        self, incoming: IncomingMessage, ctx: dict
    ) -> MedassistSessionCreated:
        created = await self._client.create_session(
            incoming.from_number, self._agent_id,
            byoa_secret=self._byoa_secret, byoa_kid=self._byoa_kid, byoa_iss=self._byoa_iss,
        )
        # Every session-creation path funnels through here (organic first
        # message, session-choice resume, mid-form recreate), so this one bind
        # covers them all.
        bind_turn_context(sid=created.session_id)
        update_kwargs: dict = {
            "context": {
                **ctx,
                "medassist_session_id": created.session_id,
            }
        }
        if created.session_validity_s:
            update_kwargs["expire_seconds"] = created.session_validity_s
        await self.session_manager.update_session(self._session_id_for(incoming), **update_kwargs)
        return created

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def _build_declined_payload(self, incoming: IncomingMessage, pending: PendingElicitation) -> dict | None:
        """Build a payload that includes TOOL DECLINED context so the LLM knows what was interrupted."""
        user_text = self._user_text(incoming)
        if not user_text:
            return None
        context_parts = []
        acc = pending.doctor_accumulated
        if acc.get("doctor_id"):
            context_parts.append(f"selected_doctor_id={acc['doctor_id']}")
        if acc.get("hospital_id"):
            context_parts.append(f"hospital_id={acc['hospital_id']}")
        if acc.get("preferred_date"):
            context_parts.append(f"preferred_date={acc['preferred_date']}")
        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""
        declined_text = (
            f"[TOOL DECLINED: {pending.tool_name} was waiting for input{context_str}]\n{user_text}"
        )
        return self._build_chat_payload(declined_text)

    def _build_payload(self, incoming: IncomingMessage) -> dict | None:
        if incoming.type == "text" and incoming.text_body:
            return self._build_chat_payload(incoming.text_body)
        if incoming.type == "interactive" and incoming.interactive_reply:
            title = reply_text(incoming.interactive_reply)
            if title:
                return self._build_chat_payload(title)
        if incoming.type == "audio" and incoming.audio_id:
            return self._build_audio_payload(incoming.audio_id)
        if incoming.type in ("image", "document") and (incoming.media_id or incoming.media_url):
            # Resolved in _chat_with_retry: downloaded once, uploaded to matrix per session.
            return {"__file": incoming.media_id or incoming.media_url}
        if incoming.type == "location" and incoming.location_lat is not None:
            place = f", Place: {incoming.location_name}" if incoming.location_name else ""
            text = f"[User shared location. Latitude: {incoming.location_lat}, Longitude: {incoming.location_lng}{place}]"
            self.logger.info(
                "medassist_location_payload",
                phone_number=incoming.from_number,
                lat=incoming.location_lat,
                lng=incoming.location_lng,
                place=incoming.location_name or "",
                text_sent=text,
            )
            return self._build_chat_payload(text)
        return None

    def _build_audio_payload(self, audio_id: str) -> dict:
        return {"__audio_id": audio_id}

    async def _resolve_audio_payload(self, audio_id: str) -> dict:
        from app.services.audio.transcription import transcribe_audio
        audio_bytes = await self.whatsapp.download_media(audio_id)
        transcription = await transcribe_audio(audio_bytes, "audio/ogg")
        if not transcription:
            return self._build_chat_payload(
                "[Voice message received but could not be transcribed. Please send as text.]"
            )
        self.logger.info("medassist_audio_transcribed", chars=len(transcription))
        return self._build_chat_payload(transcription)

    async def _fetch_inbound_file(
        self, incoming: IncomingMessage, media_ref: str
    ) -> tuple[bytes, str] | None:
        """Download an inbound photo/document as ``(bytes, mime_type)``; None when matrix
        can't take it. Netcore/Twilio send no mime type, so it is read off the bytes."""
        declared = (incoming.mime_type or "").split(";")[0].strip().lower()
        if declared and declared not in self._UPLOAD_TYPES:
            self.logger.info("medassist_file_rejected", mime_type=declared)
            return None
        data = await self.whatsapp.download_media(media_ref)
        mime = declared or next(
            (m for sig, m in self._FILE_SIGNATURES if data.startswith(sig)), ""
        )
        if mime not in self._UPLOAD_TYPES or len(data) > self._MAX_UPLOAD_BYTES:
            self.logger.info("medassist_file_rejected", mime_type=mime, size_bytes=len(data))
            return None
        return data, mime

    async def _file_payload(
        self, sid: str, incoming: IncomingMessage, data: bytes, mime_type: str
    ) -> dict:
        """Upload to this session's storage and build the ``ct: "file"`` turn. A failed
        upload is told to the agent in text instead, so the turn still gets a reply."""
        try:
            file_id = await self._client.upload_file(
                sid, data, mime_type, self._agent_id, incoming.from_number,
                self._byoa_secret, self._byoa_kid, self._byoa_iss,
            )
        except MedassistFileUploadError as e:
            self.logger.warning("medassist_file_upload_failed", sid=sid, error=str(e)[:300])
            return self._file_failed_payload(incoming)
        turn = {"urls": [file_id]}
        if incoming.caption:
            turn["text"] = incoming.caption
        return {"_id": str(uuid.uuid4()), "ev": "chat", "ct": "file", "data": turn}

    def _file_failed_payload(self, incoming: IncomingMessage) -> dict:
        label = "photo" if incoming.type == "image" else "document"
        note = f"[User shared a {label} but it couldn't be uploaded]"
        return self._build_chat_payload(f"{note}\n{incoming.caption}" if incoming.caption else note)

    @staticmethod
    def _welcome_response(created: MedassistSessionCreated) -> MedassistResponse:
        """Turn a freshly-created session's agent-config initial_message into a
        MedassistResponse, so a new session opens with the canonical welcome
        (text + suggestion buttons) rather than routing the user's message to the LLM."""
        im = created.initial_message or {}
        options = [
            s.get("label") or s.get("value", "")
            for s in (im.get("suggestions") or []) if isinstance(s, dict)
        ]
        return MedassistResponse(text=im.get("text", ""), options=[o for o in options if o])

    async def _recover_from_tool_error(
        self,
        incoming: IncomingMessage,
        session_id: str,
        error_response: MedassistResponse,
        ctx: dict,
    ) -> MedassistResponse:
        """Ask MedAssist LLM to generate a natural recovery message after a tool error.

        The LLM receives the error context and generates an empathetic, conversation-continuing
        response instead of exposing the raw error string to the user.
        Only one level of recovery — if the LLM itself returns an error, fall back to static text.
        """
        error_context = error_response.error_detail or "The previous action could not be completed."
        recovery_payload = self._build_chat_payload(f"[Tool failed: {error_context}]")
        self.logger.info(
            "medassist_tool_error_recovery",
            phone_number=incoming.from_number,
            error_detail=error_context,
        )
        try:
            recovered = await self._client.stream_chat(
                session_id, recovery_payload, self._agent_id, incoming.from_number,
                self._byoa_secret, self._byoa_kid, self._byoa_iss,
            )
            # Don't recurse if recovery also errors
            if recovered.is_error:
                return error_response
            return recovered
        except Exception:
            return error_response

    async def _chat_with_retry(
        self,
        incoming: IncomingMessage,
        session_id: str,
        payload: dict,
        ctx: dict,
    ) -> MedassistResponse:
        if "__audio_id" in payload:
            payload = await self._resolve_audio_payload(payload["__audio_id"])
        file = None
        if "__file" in payload:
            try:
                file = await self._fetch_inbound_file(incoming, payload["__file"])
                if file is None:
                    return MedassistResponse(text=self._FILE_REJECTED_TEXT)
            except Exception as e:
                self.logger.warning("medassist_file_download_failed", error=str(e)[:300])
                payload = self._file_failed_payload(incoming)

        async def _chat(sid: str):
            # A file is uploaded per attempt: its id is only valid in the session it was made for.
            body = await self._file_payload(sid, incoming, *file) if file else payload
            return await self._client.stream_chat(
                sid, body, self._agent_id, incoming.from_number,
                self._byoa_secret, self._byoa_kid, self._byoa_iss,
            )

        try:
            return await _chat(session_id)
        except MedassistSessionExpired:
            self.logger.info("medassist_session_recreating", phone_number=incoming.from_number)
            created = await self._create_and_store_session(
                incoming, {k: v for k, v in ctx.items() if k not in (
                    "medassist_session_id", "pending_elicitation"
                )}
            )
            # Persist the new session id into the caller's ctx so the follow-up
            # update_session() doesn't write back the stale one (which would 404 the
            # very next message and re-create endlessly).
            ctx["medassist_session_id"] = created.session_id
            ctx.pop("pending_elicitation", None)
            # A brand-new session opens with the agent's canonical welcome, not the
            # retried user message routed through the LLM.
            if created.initial_message:
                return self._welcome_response(created)
            payload["_id"] = str(uuid.uuid4())
            return await _chat(created.session_id)
        except RuntimeError as e:
            # Transient matrix hiccups that are safe to retry once on the SAME session
            # (preserving conversation context): a generic server_error, or an empty
            # LLM turn ("No response" / parsing — matrix produced 0 response chunks).
            msg = str(e).lower()
            _TRANSIENT_MARKERS = ("server_error", "no response")
            if not any(m in msg for m in _TRANSIENT_MARKERS):
                raise
            self.logger.info(
                "medassist_transient_error_retrying",
                phone_number=incoming.from_number, error=str(e)[:200],
            )
            payload["_id"] = str(uuid.uuid4())
            return await _chat(session_id)
