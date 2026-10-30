import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx
import jwt
import orjson

from app.bridge.medassist.elicitation import (
    DoctorOption,
    ElicitationComponent,
    PendingCard,
    PendingElicitation,
)
from app.bridge.medassist.exceptions import (
    MedassistFileUploadError,
    MedassistSessionExpired,
    MedassistSessionNotFound,
    MedassistTokenExchangeError,
)
from app.bridge.medassist.template_session import _norm_phone
from app.core.logging import get_logger

logger = get_logger(__name__)

# Origin channel - it lets matrix tell WhatsApp traffic apart from
# the web/app clients hitting the same session APIs.
_CHANNEL = "whatsapp"


@dataclass
class MedassistResponse:
    text: str
    options: list[str] = field(default_factory=list)
    pending_elicitation: Optional[PendingElicitation] = None
    is_error: bool = False
    error_detail: str = ""
    # A finished elicitation ({text, tool_id, tool_result?}) to hand back to the
    # agent as a chat turn — what the web widget sends on a "success" card.
    close: Optional[dict] = None


@dataclass
class MedassistSessionCreated:
    session_id: str
    session_token: str
    initial_message: dict | None = None
    session_validity_s: int | None = None


# Session-expired HTTP status codes returned by medassist
_SESSION_EXPIRED_STATUSES = {401, 410}
# Error codes in JSON error bodies that indicate session expiry
_SESSION_EXPIRED_CODES = {"session_expired", "session_not_found"}
# TTL for the cached Bearer-token bundle (~ matrix refresh-token lifetime).
_TOKEN_CACHE_TTL_SECONDS = 7200
# Refresh the sess token this many seconds before its actual expiry.
_SESS_EXPIRY_SKEW_SECONDS = 30
# TTL for cached public agent config (initial_message rarely changes; short
# enough that a console edit propagates quickly).
_AGENT_CONFIG_CACHE_TTL_SECONDS = 300

def _doctor_option(entry: dict, info: dict) -> DoctorOption:
    """One doctor_card entry → the doctor, a subtext line and their per-date slots."""
    doctor_id = entry["doctor_id"]
    hospitals = info.get("hospitals") or []
    first = hospitals[0] if hospitals else {}
    hospital_id = str(entry.get("hospital_id") or first.get("hospital_id") or "")
    hospital = next((h for h in hospitals if str(h.get("hospital_id")) == hospital_id), first)
    detail = (info.get("specialty"), info.get("experience"), info.get("qualification"), info.get("fee"))
    dates = [
        # No "slots" key means that date isn't loaded yet; [] means it's fully booked.
        {"date": day["date"], "slots": None if day.get("slots") is None else [s for s in day["slots"] if s]}
        for day in (entry.get("availability") or [])
        if day.get("date")
    ]
    return DoctorOption(
        doctor_id=doctor_id,
        hospital_id=hospital_id,
        name=info.get("name") or f"Dr. {doctor_id}",
        hospital_name=hospital.get("name", ""),
        description=" · ".join(str(d) for d in detail if d),
        preferred_date=entry.get("preferred_date") or "",
        image=info.get("profile_pic") or "",
        dates=sorted(dates, key=lambda d: d["date"]),
    )


def _card_summary(inp: dict) -> str:
    """Numbered text for cards that can't be picked (not in progress)."""
    lines = [inp["text"] + "\n"] if inp.get("text") else []
    for i, card in enumerate(inp.get("cards", []), 1):
        lines.append(f"{i}. {card.get('title', '')}")
        lines.extend(f"   {extra}" for extra in (card.get("tags_text"), card.get("banner_text")) if extra)
    return "\n".join(lines)


def _parse_elicitation_data(message_id: str, data: dict) -> MedassistResponse:
    """
    Parse a ct=tool elicitation data dict into the text, options and pending to act on.
    Sets pending whenever details.status == "progress" (tool needs more input), and
    ``close`` when the tool finished with something the agent should be told.
    """
    tool_id = data.get("tool_id", "")
    tool_name = data.get("tool_name", "")
    details = data.get("details") or {}
    component = details.get("component", "")
    inp = details.get("input") or {}
    status = details.get("status", "")
    is_in_progress = status == "progress"

    text = ""
    options: list[str] = []
    pending: Optional[PendingElicitation] = None
    is_error = False
    error_detail = ""

    meta = details.get("_meta") or {}
    schema = meta.get("schema") or {}
    schema_fields = schema.get("required") or list((schema.get("properties") or {}).keys())

    if component in (ElicitationComponent.PILLS, ElicitationComponent.MULTI):
        text = inp.get("text", "")
        pill_opts = inp.get("options", [])
        options = [
            o.get("label") or o.get("value", "")
            for o in pill_opts if isinstance(o, dict)
        ]
        if is_in_progress or pill_opts:
            pending = PendingElicitation(
                message_id=message_id,
                tool_id=tool_id,
                tool_name=tool_name,
                component=component,
                status=status,
                options=pill_opts,
                input_data=inp,
                schema_fields=schema_fields,
                # MCP pills read the pick from the request _meta (the widget sends
                # {"mcp_meta_fields": {"value": ...}}); echo's elicit_selection declares none.
                mcp_meta_wrapper=bool(meta.get("mcp_meta_fields")),
            )

    elif component == ElicitationComponent.CARD:
        pending_cards = [
            PendingCard(
                card_id=card.get("card_id", ""),
                title=card.get("title", ""),
                tool_result=(card.get("primary_cta") or {}).get("tool_result"),
            )
            for card in inp.get("cards", [])
        ]
        options = [c.title for c in pending_cards]
        if is_in_progress:
            # Shown as a list with each card's subtext, so the text is just the prompt.
            text = inp.get("text", "")
            pending = PendingElicitation(
                message_id=message_id,
                tool_id=tool_id,
                tool_name=tool_name,
                component=ElicitationComponent.CARD,
                status=status,
                cards=pending_cards,
                input_data=inp,
                schema_fields=schema_fields,
                orientation=meta.get("orientation") or "",
            )
        else:
            text = _card_summary(inp)

    elif component == "media_card":
        media_card = inp.get("media_card") or {}
        lines = []
        voucher_code = media_card.get("title", "")
        description = media_card.get("description", "")
        tags = media_card.get("tags_text", "")
        if voucher_code:
            lines.append(f"Your voucher code: *{voucher_code}*")
        if description:
            lines.append(description)
        if tags:
            lines.append(tags)
        text = "\n".join(lines)
        # media_card is the final step — no pending

    elif component == "doctor_card":
        text = inp.get("text", "")
        if is_in_progress:
            doctor_details = inp.get("doctor_details") or {}
            doctor_opts = [
                _doctor_option(entry, doctor_details.get(entry["doctor_id"], {}))
                for entry in inp.get("doctors", [])
                if entry.get("doctor_id")
            ]
            # date_slots / flat_slots: kept for one release for pods on the previous build.
            date_slots_map: dict[str, list[str]] = {}
            flat_slots: list[dict] = []
            for doctor in doctor_opts:
                for day in doctor.dates:
                    if not day["slots"]:
                        continue
                    date_slots_map[day["date"]] = day["slots"]
                    flat_slots.extend(
                        {
                            "date": day["date"],
                            "slot_time": slot_time,
                            "doctor_id": doctor.doctor_id,
                            "hospital_id": doctor.hospital_id,
                            "doctor_name": doctor.name,
                            "hospital_name": doctor.hospital_name,
                        }
                        for slot_time in day["slots"]
                    )

            pending = PendingElicitation(
                message_id=message_id,
                tool_id=tool_id,
                tool_name=tool_name,
                component="doctor_card",
                status=status,
                input_data=inp,
                doctor_options=doctor_opts,
                date_slots=date_slots_map,
                flat_slots=flat_slots,
                schema_fields=schema_fields,
            )

    elif component in ("mobile_number", "otp", "email_address"):
        _default_prompts = {
            "mobile_number": "Please enter your mobile number:",
            "otp": "Please enter the OTP sent to you:",
            "email_address": "Please enter your email address:",
        }
        _default_user_fields = {"mobile_number": "mobile_number", "otp": "otp", "email_address": "email_address"}
        text = inp.get("text") or inp.get("description") or _default_prompts[component]
        if is_in_progress:
            meta_section = details.get("_meta") or {}
            mcp_meta_fields_list = meta_section.get("mcp_meta_fields") or []
            # Fixed params = inp fields that aren't prompt text
            input_fields = {k: v for k, v in inp.items() if k not in ("text", "description")}
            if mcp_meta_fields_list:
                # Schema uses mcp_meta_fields convention: user value goes under {"mcp_meta_fields": {field: val}}
                user_field = mcp_meta_fields_list[0]
                mcp_meta_wrapper = True
            else:
                # Derive user field: required fields not already supplied by inp
                fixed_keys = set(input_fields.keys())
                schema_required = schema.get("required") or list((schema.get("properties") or {}).keys())
                user_fields = [f for f in schema_required if f not in fixed_keys]
                user_field = user_fields[0] if user_fields else _default_user_fields[component]
                mcp_meta_wrapper = False
            pending = PendingElicitation(
                message_id=message_id,
                tool_id=tool_id,
                tool_name=tool_name,
                component=component,
                schema_fields=[user_field],
                input_fields=input_fields,
                mcp_meta_wrapper=mcp_meta_wrapper,
            )

    elif component in ("error", "") or (component == "text" and status == "failure"):
        # Matrix's own callback failures arrive as component "text" (_meta.message) or
        # "error" (_meta.tool_result.result_error); MCP errors carry tool_result.error.
        disp_msg = meta.get("disp_message") or meta.get("disp_msg", "")
        tool_result = meta.get("tool_result") or {}
        raw_error = str(
            tool_result.get("error") or tool_result.get("result_error") or meta.get("message") or ""
        )
        if raw_error:
            logger.error("medassist_elicitation_tool_error", tool_name=tool_name, error=raw_error)
        text = disp_msg or raw_error or "The action could not be completed."
        is_error = True
        error_detail = raw_error or disp_msg

    close = None
    if status == "success" and not is_error and (meta.get("disp_message") or meta.get("tool_result")):
        close = {"text": meta.get("disp_message") or "", "tool_id": tool_id}
        # Matrix merges user_text into tool_result, so only a dict can ride along.
        if isinstance(meta.get("tool_result"), dict):
            close["tool_result"] = meta["tool_result"]

    logger.info(
        "medassist_elicitation_parsed",
        tool_name=tool_name,
        component=component,
        has_pending=pending is not None,
        options_count=len(options),
        closes=close is not None,
    )
    return MedassistResponse(
        text=text,
        options=options,
        pending_elicitation=pending,
        is_error=is_error,
        error_detail=error_detail,
        close=close,
    )


class MedassistClient:
    """Async HTTP client for the medassist streaming API."""

    def __init__(self, base_url: str, session_manager=None) -> None:
        self._base_url = base_url.rstrip("/")
        # Used only for the Redis-backed Bearer-token cache (wa:mx_tokens:*).
        self._session_manager = session_manager

    @staticmethod
    def _bearer_headers(sess_token: str, extra: dict | None = None) -> dict:
        """Auth headers for a session API — matrix derives agent/wid/user from the
        Bearer sess token, so no x-agent-id/x-auth-token is sent."""
        h = {
            "Authorization": f"Bearer {sess_token}",
            "Content-Type": "application/json",
            "x-channel": _CHANNEL,
        }
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------
    # Bearer token: exchange + Redis cache + auto-refresh
    # ------------------------------------------------------------------

    def _token_cache_key(self, agent_id: str, phone: str) -> str:
        return f"wa:mx_tokens:{agent_id}:{_norm_phone(phone)}"

    async def _get_cached_tokens(self, agent_id: str, phone: str) -> dict | None:
        redis = await self._session_manager.get_redis()
        raw = await redis.get(self._token_cache_key(agent_id, phone))
        if not raw:
            return None
        try:
            return orjson.loads(raw)
        except Exception:
            return None

    async def clear_cached_tokens(self, agent_id: str, phone: str) -> None:
        """Drop the cached Bearer bundle (used on an explicit session reset)."""
        redis = await self._session_manager.get_redis()
        await redis.delete(self._token_cache_key(agent_id, phone))

    async def _store_tokens(self, agent_id: str, phone: str, data: dict) -> str:
        """Persist a token-exchange response bundle; return the sess_token."""
        if data.get("userid_change_detected"):
            logger.info("medassist_userid_change_detected", agent_id=agent_id)
        bundle = {
            "sess_token": data["sess_token"],
            "refresh_token": data["refresh_token"],
            "sess_exp": int(time.time()) + int(data.get("expires_in") or 3600),
            "user_id": data.get("user_id"),
        }
        redis = await self._session_manager.get_redis()
        await redis.set(
            self._token_cache_key(agent_id, phone),
            orjson.dumps(bundle),
            ex=_TOKEN_CACHE_TTL_SECONDS,
        )
        return bundle["sess_token"]

    async def exchange_tokens(
        self,
        agent_id: str,
        *,
        byoa_token: str | None = None,
        refresh_token: str | None = None,
        sess_token: str | None = None,
    ) -> dict:
        """POST /reloaded/med-assist/auth/token-exchange.

        The current sess token (when present) rides in the Authorization: Bearer
        header (matrix reads it allow_expired). Body carries agent_id + auth_token
        (initial BYOA) and/or refresh_token. Returns the response bundle on 200/202;
        raises MedassistTokenExchangeError on any non-2xx (so the caller can fall
        back from a failed refresh to a fresh BYOA init).
        """
        # Matrix selects the flow by ?type=, never by inferring it from the body:
        # ?type=refresh → refresh flow (reads refresh_token); omitted → partner/BYOA
        # init flow (reads auth_token). Without the query param a refresh call would
        # silently fall into the partner/guest flow and ignore refresh_token.
        url = f"{self._base_url}/reloaded/med-assist/auth/token-exchange"
        if refresh_token:
            url += "?type=refresh"
        headers = {"Content-Type": "application/json", "x-channel": _CHANNEL}
        if sess_token:
            headers["Authorization"] = f"Bearer {sess_token}"
        body: dict = {"agent_id": agent_id}
        if byoa_token:
            body["auth_token"] = byoa_token
        if refresh_token:
            body["refresh_token"] = refresh_token

        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            response = await client.post(url, headers=headers, content=orjson.dumps(body))

        mode = "refresh" if refresh_token else "init"
        logger.info(
            "medassist_token_exchange_response",
            mode=mode, status=response.status_code, body=response.text[:400],
        )
        if response.status_code not in (200, 202):
            raise MedassistTokenExchangeError(response.status_code, response.text)
        return response.json()

    async def _ensure_sess_token(
        self,
        agent_id: str,
        phone: str,
        byoa_secret: str,
        byoa_kid: str,
        byoa_iss: str,
        *,
        force: bool = False,
    ) -> str:
        """Return a valid Bearer sess token, exchanging/refreshing as needed.

        Order: fresh cached token → refresh-exchange (Bearer old sess + refresh) →
        BYOA init-exchange. A failed refresh (401/403) falls through to BYOA.
        """
        bundle = await self._get_cached_tokens(agent_id, phone)
        if (
            bundle
            and not force
            and (bundle.get("sess_exp") or 0) > int(time.time()) + _SESS_EXPIRY_SKEW_SECONDS
        ):
            return bundle["sess_token"]

        refresh_token = (bundle or {}).get("refresh_token")
        old_sess = (bundle or {}).get("sess_token")
        if refresh_token:
            try:
                data = await self.exchange_tokens(
                    agent_id, refresh_token=refresh_token, sess_token=old_sess
                )
                return await self._store_tokens(agent_id, phone, data)
            except MedassistTokenExchangeError as e:
                logger.info("medassist_token_refresh_failed_reauth", status=e.status_code)

        mobile = self.mobile_for(phone, agent_id)
        byoa = self._byoa_token(mobile, byoa_secret, byoa_kid, byoa_iss)
        if not byoa:
            raise RuntimeError("BYOA credentials missing; cannot obtain a sess token")
        data = await self.exchange_tokens(agent_id, byoa_token=byoa)
        return await self._store_tokens(agent_id, phone, data)

    async def _authed_request(
        self,
        method: str,
        url: str,
        agent_id: str,
        phone: str,
        byoa_secret: str,
        byoa_kid: str,
        byoa_iss: str,
        *,
        content: bytes | None = None,
        timeout: float = 30,
    ) -> httpx.Response:
        """Non-streaming session call with a Bearer token and a one-shot refresh:
        on ANY 401, force a token refresh and retry once (message-agnostic — a
        persistent 401 after refresh is left for the caller to treat as ownership/
        not-found)."""
        sess = await self._ensure_sess_token(agent_id, phone, byoa_secret, byoa_kid, byoa_iss)
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.request(
                method, url, headers=self._bearer_headers(sess), content=content
            )
            if response.status_code == 401:
                sess = await self._ensure_sess_token(
                    agent_id, phone, byoa_secret, byoa_kid, byoa_iss, force=True
                )
                response = await client.request(
                    method, url, headers=self._bearer_headers(sess), content=content
                )
        return response

    @staticmethod
    def _byoa_token(
        mobile_number: str,
        byoa_secret: str,
        byoa_kid: str,
        byoa_iss: str = "",
        partner_id: str = "",
    ) -> str | None:
        """Generate a short-lived BYOA signed JWT (HS256) for the given mobile number.

        The token is a JWS (NOT a JWE) signed with the partner's shared secret. Matrix's
        ``verify_partner_token`` must mirror the same key convention: the shared secret is
        ``token_urlsafe(32)`` (base64url of 32 raw bytes) and the HMAC key is those 32 raw
        bytes. ``sub`` carries the partner_id when present (empty for WhatsApp, where the
        mobile is the identifier instead).
        """
        if not byoa_secret or not byoa_kid:
            return None
        # byoa_secret is token_urlsafe(32): base64url of 32 raw bytes.
        # Validate the decoded length to catch misconfiguration early, and use the raw
        # bytes as the HS256 HMAC key.
        try:
            raw = base64.urlsafe_b64decode(byoa_secret + "==")
        except Exception:
            logger.error("byoa_secret_not_base64url")
            return None
        if len(raw) != 32:
            logger.error("byoa_secret_invalid_length", expected=32, actual=len(raw))
            return None
        now = int(time.time())
        claims = {
            "iss": byoa_iss or "https://eka.care",
            "aud": "https://eka.care",
            "iat": now,
            "exp": now + 240,
            "jti": str(uuid.uuid4()),
            "sub": partner_id or "",
            "mobile": mobile_number,
        }
        return jwt.encode(claims, raw, algorithm="HS256", headers={"kid": byoa_kid})

    _SA_AGENT_IDS = {"MzlmOTczYjMtYzVkNy00ZjIxLTgyYTctN2Y3ZWFmZTg3MWEyIzc3MDg4MTY2OTk2NzI0"}

    def mobile_for(self, phone_number: str, agent_id: str) -> str:
        """E.164 mobile used for the BYOA token / user_context.

        inbound WhatsApp number, prefixed with ``+`` if missing. TEST for SA (DNE)
        """
        if agent_id.strip() in self._SA_AGENT_IDS:
            return "+27738185829"  # TODO: replace with actual SA-formatted number once verified
        return f"+{phone_number}" if not phone_number.startswith("+") else phone_number

    def _agent_config_cache_key(self, agent_id: str) -> str:
        return f"wa:agent_config:{agent_id}"

    async def get_agent_config(self, agent_id: str) -> dict | None:
        """Fetch matrix's public agent config (unauthenticated GET), Redis-cached.

        ``GET /reloaded/med-assist/agent-config/{agent_id}`` → ``{"data": {...}}``.
        Matrix stopped returning ``initial_message`` in the create-session response,
        so it is sourced here instead. Fails open (returns None) so a config-fetch
        hiccup never blocks session creation.
        """
        redis = await self._session_manager.get_redis()
        ckey = self._agent_config_cache_key(agent_id)
        try:
            cached = await redis.get(ckey)
            if cached:
                return orjson.loads(cached)
        except Exception:
            pass

        url = f"{self._base_url}/reloaded/med-assist/agent-config/{agent_id}"
        try:
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                response = await client.get(url)
        except Exception as e:
            logger.warning("medassist_agent_config_unreachable", agent_id=agent_id, error=str(e))
            return None

        logger.info(
            "medassist_agent_config_response",
            status=response.status_code, agent_id=agent_id, body=response.text[:300],
        )
        if response.status_code != 200:
            return None
        data = (response.json() or {}).get("data") or None
        if data is not None:
            try:
                await redis.set(ckey, orjson.dumps(data), ex=_AGENT_CONFIG_CACHE_TTL_SECONDS)
            except Exception:
                pass
        return data

    async def get_initial_message(self, agent_id: str) -> dict | None:
        """The agent's initial_message ({text, suggestions}), from public config."""
        config = await self.get_agent_config(agent_id)
        if not config:
            return None
        return config.get("initial_message") or None

    async def create_session(
        self,
        phone_number: str,
        agent_id: str,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> MedassistSessionCreated:
        # Identity comes from the Bearer sess token; the body carries no user_context.
        url = f"{self._base_url}/reloaded/med-assist/session"
        body = {
            "session_context": {
                "mobile": phone_number,
                "channel": "whatsapp",
            },
            "channel": "whatsapp",
        }
        body_bytes = orjson.dumps(body)

        response = await self._authed_request(
            "POST", url, agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss,
            content=body_bytes,
        )

        logger.info(
            "medassist_create_session_response",
            status=response.status_code, body=response.text[:400], phone_number=phone_number,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create medassist session: HTTP {response.status_code} — {response.text}"
            )

        data = response.json()
        session_id = data["session_id"]
        # Matrix no longer returns initial_message in the create-session response;
        # source it from the public agent-config endpoint. Fall back to the
        # response value so this still works against a matrix that includes it.
        initial_message = data.get("initial_message") or await self.get_initial_message(agent_id)
        session_validity_s = data.get("session_validity_s") or None
        logger.info("medassist_session_created", sid=session_id, phone_number=phone_number)
        return MedassistSessionCreated(
            session_id=session_id,
            session_token="",  # per-session token retired from the client surface
            initial_message=initial_message,
            session_validity_s=session_validity_s,
        )

    async def get_session(
        self,
        sid: str,
        phone_number: str,
        agent_id: str,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> MedassistSessionCreated:
        """Confirm an existing session is resumable by this user.

        GET /reloaded/med-assist/session/{sid} with the Bearer sess token. Matrix
        authorizes via ownership (no per-session token is returned any more).
          200 → resumable → return the session_id (token field left empty)
          401 (persists after a token refresh) or 404 → not resumable →
               raise MedassistSessionNotFound (caller creates a fresh session)
        """
        url = f"{self._base_url}/reloaded/med-assist/session/{sid}"
        response = await self._authed_request(
            "GET", url, agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss,
        )

        logger.info(
            "medassist_get_session_response",
            sid=sid, status=response.status_code, body=response.text[:400],
        )

        if response.status_code in (401, 404):
            # 401 here means the (already-refreshed) sess token doesn't own this
            # session; either way it can't be resumed.
            raise MedassistSessionNotFound(f"Session not resumable: {sid} (HTTP {response.status_code})")
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to get medassist session: HTTP {response.status_code} — {response.text}"
            )

        data = response.json()
        logger.info("medassist_session_fetched", sid=sid, phone_number=phone_number)
        return MedassistSessionCreated(
            session_id=sid,
            session_token="",
            session_validity_s=data.get("session_validity_s") or None,
        )

    async def get_sessions(
        self,
        phone_number: str,
        agent_id: str,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> list[dict] | None:
        """List a number's sessions for the "Choose" flow.

        GET /reloaded/med-assist/session (the same collection resource that POST
        creates on) → {"data": [{session_id, c_at, c_ate, channel, ...}]}. Matrix
        resolves the user from the Bearer sess token — no query params. Normalizes
        each entry to ``{"sid", "c_ate", "c_at", "channel"}`` and returns them sorted
        by ``c_ate`` descending (most recent first). On ANY error / non-200, logs and
        returns ``None`` so the caller simply hides Choose.
        """
        url = f"{self._base_url}/reloaded/med-assist/session"

        try:
            response = await self._authed_request(
                "GET", url, agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss,
                timeout=15,
            )
            logger.info(
                "medassist_get_sessions_response",
                phone_number=phone_number, status=response.status_code, body=response.text,
            )
            if response.status_code != 200:
                logger.warning(
                    "medassist_get_sessions_failed",
                    status=response.status_code, body=response.text[:300],
                )
                return None
            body = response.json() or {}
            data = body.get("data") if isinstance(body, dict) else body
            # Agent's data region ("IN", "ZA") — one per list; used to localise times.
            region = body.get("region") if isinstance(body, dict) else None
            sessions = []
            for s in (data or []):
                sid = s.get("session_id") or s.get("sid")
                if not sid:
                    continue
                sessions.append({
                    "sid": sid,
                    "c_ate": s.get("c_ate"),
                    "c_at": s.get("c_at"),
                    "channel": s.get("channel"),
                    "region": region,
                })
            sessions.sort(key=lambda s: s.get("c_ate") or 0, reverse=True)
            logger.info(
                "medassist_sessions_listed",
                phone_number=phone_number, count=len(sessions), region=region,
            )
            return sessions
        except Exception as e:
            logger.error("medassist_get_sessions_error", phone_number=phone_number, error=str(e))
            return None

    async def stream_chat(
        self,
        session_id: str,
        message: dict,
        agent_id: str,
        phone_number: str,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> MedassistResponse:
        """
        Send a message to medassist and accumulate the full streamed response.

        Authenticated with the Bearer sess token (no per-session token). A 401 on
        the first attempt forces one token refresh and re-opens the stream; a 401
        that survives the refresh (or a 410) → MedassistSessionExpired so the bridge
        recreates the session.

        The medassist endpoint returns NDJSON with events:
          {"ev": "stream", "ct": "text", "data": {"text": "..."}}  — text chunk
          {"ev": "stream", "ct": "tool", "data": {...}}             — tool/elicitation
          {"ev": "eos", ...}                                        — end of stream
        """
        url = f"{self._base_url}/reloaded/med-assist/session/{session_id}/chat"

        if "_id" not in message:
            message["_id"] = str(uuid.uuid4())
        if "ts" not in message:
            message["ts"] = int(time.time() * 1000)
        content = orjson.dumps(message)

        sess = await self._ensure_sess_token(
            agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss
        )

        async with httpx.AsyncClient(timeout=120, verify=False) as client:
            for attempt in range(2):
                text_parts: list[str] = []
                options: list[str] = []
                pending: Optional[PendingElicitation] = None
                close: Optional[dict] = None

                async with client.stream(
                    "POST", url, headers=self._bearer_headers(sess), content=content,
                ) as response:
                    if response.status_code == 401 and attempt == 0:
                        await response.aread()
                        sess = await self._ensure_sess_token(
                            agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss, force=True
                        )
                        continue
                    if response.status_code in _SESSION_EXPIRED_STATUSES or response.status_code == 404:
                        # 401/410 = expired; 404 = matrix no longer has this session
                        # (stale cached sid). Both → recreate + retry in the bridge.
                        await response.aread()
                        raise MedassistSessionExpired(
                            f"Session gone during chat: HTTP {response.status_code}"
                        )
                    if response.status_code != 200:
                        body = await response.aread()
                        raise RuntimeError(
                            f"Medassist chat error: HTTP {response.status_code} — {body.decode()}"
                        )

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = orjson.loads(line)
                        except Exception:
                            logger.warning("medassist_invalid_chunk", line=line)
                            continue

                        ev = chunk.get("ev")

                        if ev == "err":
                            code = chunk.get("code", "")
                            if code in _SESSION_EXPIRED_CODES:
                                raise MedassistSessionExpired(
                                    f"Session expired in stream: code={code}"
                                )
                            raise RuntimeError(f"Medassist stream error: {chunk}")

                        if ev == "stream":
                            logger.debug("medassist_stream_chunk", chunk=chunk)
                            ct = chunk.get("ct")
                            data = chunk.get("data", {})

                            if ct == "text":
                                t = data.get("text", "")
                                if t:
                                    text_parts.append(t)

                            elif ct == "tool" and data.get("tool_type") == "elicitation":
                                parsed = _parse_elicitation_data(chunk.get("_id", ""), data)
                                t = parsed.text
                                if parsed.is_error:
                                    # Error overrides any optimistic LLM text already streamed
                                    text_parts = [t] if t else text_parts
                                elif t and t not in "".join(text_parts):
                                    # The tool's question is its own paragraph, not glued to the agent's text.
                                    text_parts.append(f"\n\n{t}" if text_parts else t)
                                if parsed.options:
                                    options = parsed.options
                                if parsed.pending_elicitation is not None:
                                    pending = parsed.pending_elicitation
                                if parsed.close is not None:
                                    close = parsed.close

                            else:
                                t = data.get("text", "")
                                if t:
                                    text_parts.append(t)

                        elif ev == "eos":
                            break

                    result_text = "".join(text_parts)
                    logger.info(
                        "medassist_stream_complete",
                        sid=session_id,
                        response_length=len(result_text),
                        options_count=len(options),
                        has_pending=pending is not None,
                    )
                    return MedassistResponse(
                        text=result_text, options=options, pending_elicitation=pending, close=close
                    )

        # Both attempts saw a first-attempt 401 (token refresh didn't help).
        raise MedassistSessionExpired("Session unauthorized during chat after token refresh")

    async def upload_file(
        self,
        session_id: str,
        data: bytes,
        mime_type: str,
        agent_id: str,
        phone_number: str,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> str:
        """Upload one file through matrix's ``ct: "file"`` flow and return its file id.

        Step 1 asks matrix for an upload target; step 2 uploads the bytes there. The
        caller sends the id in a ``ct: "file"`` chat turn (step 3, a normal stream_chat).

        Matrix picks the storage, so the target's shape is all this branches on:
        Eka Records (vault) carries ``fields`` for a presigned POST, S3/Azure is a
        presigned PUT. The id belongs to this session, so a recreated session needs
        a fresh upload.
        """
        url = f"{self._base_url}/reloaded/med-assist/session/{session_id}/chat"
        body = orjson.dumps({
            "_id": str(uuid.uuid4()),
            "ts": int(time.time() * 1000),
            "ev": "chat",
            "ct": "file",
            # file_sizes is required by Records and ignored by S3/Azure.
            "data": {"extensions": [mime_type], "file_sizes": [len(data)]},
        })
        try:
            response = await self._authed_request(
                "POST", url, agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss,
                content=body,
            )
            if response.status_code in _SESSION_EXPIRED_STATUSES or response.status_code == 404:
                raise MedassistSessionExpired(
                    f"Session gone during upload: HTTP {response.status_code}"
                )
            if response.status_code != 200:
                raise MedassistFileUploadError(
                    f"upload request: HTTP {response.status_code} — {response.text[:200]}"
                )
            target = self._upload_target(response.text)

            async with httpx.AsyncClient(timeout=60) as client:
                if target.get("fields"):
                    # httpx writes `data` parts before `files`, so the file is the
                    # last part, as the Records POST policy requires. 204 on success.
                    upload = await client.post(
                        target["url"],
                        data=target["fields"],
                        files={"file": ("upload", data, mime_type)},
                    )
                else:
                    # S3 signs Content-Type into the URL; Azure rejects a PUT without the blob type.
                    upload = await client.put(
                        target["url"],
                        content=data,
                        headers={"Content-Type": mime_type, "x-ms-blob-type": "BlockBlob"},
                    )
                upload.raise_for_status()
        except httpx.HTTPError as e:
            raise MedassistFileUploadError(f"file upload failed: {e}") from e

        logger.info(
            "medassist_file_uploaded",
            sid=session_id,
            file_id=target["id"],
            records=bool(target.get("fields")),
            size_bytes=len(data),
        )
        return target["id"]

    @staticmethod
    def _upload_target(ndjson: str) -> dict:
        """The ``{id, url, fields?}`` target from step 1's stream; raise on an err event."""
        for line in ndjson.splitlines():
            if not line.strip():
                continue
            try:
                chunk = orjson.loads(line)
            except orjson.JSONDecodeError:
                logger.warning("medassist_invalid_chunk", line=line)
                continue
            if chunk.get("ev") == "err":
                # Matrix nests the error under data: {"code": ..., "msg": ...}.
                error = chunk.get("data") or {}
                if error.get("code") in _SESSION_EXPIRED_CODES:
                    raise MedassistSessionExpired(f"Session expired in upload: code={error.get('code')}")
                raise MedassistFileUploadError(
                    f"matrix refused the upload: {error.get('code')} — {error.get('msg')}"
                )
            if chunk.get("ev") == "chat" and chunk.get("ct") == "file":
                urls = (chunk.get("data") or {}).get("urls") or []
                if urls:
                    return urls[0]
        raise MedassistFileUploadError("matrix returned no upload target")

    async def call_tool_callback(
        self,
        session_id: str,
        agent_id: str,
        phone_number: str,
        pending: PendingElicitation,
        tool_params: dict,
        byoa_secret: str = "",
        byoa_kid: str = "",
        byoa_iss: str = "",
    ) -> MedassistResponse:
        """
        Call the tool_callback endpoint directly, bypassing the LLM.
        Used to advance a multi-step elicitation (pills→card→media_card).
        Authenticated with the Bearer sess token. Returns a MedassistResponse.
        """
        url = (
            f"{self._base_url}/reloaded/med-assist/session/{session_id}"
            f"/messages/{pending.message_id}/tools/{pending.tool_id}"
        )
        body = orjson.dumps({"tool_params": tool_params})

        logger.info(
            "medassist_tool_callback",
            sid=session_id,
            tool_name=pending.tool_name,
            component=pending.component,
            tool_params=tool_params,
        )

        response = await self._authed_request(
            "POST", url, agent_id, phone_number, byoa_secret, byoa_kid, byoa_iss,
            content=body,
        )

        if response.status_code in _SESSION_EXPIRED_STATUSES or response.status_code == 404:
            # 401/410 = expired; 404 = session gone from matrix → recreate + retry.
            raise MedassistSessionExpired(
                f"Tool callback session gone: HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Tool callback error: HTTP {response.status_code} — {response.text}"
            )

        chunk = response.json()
        # Response shape: {"ev": "stream", "_id": "...", "ct": "tool", "data": {...}}
        message_id = chunk.get("_id", pending.message_id)
        data = chunk.get("data", {})

        response = _parse_elicitation_data(message_id, data)

        logger.info(
            "medassist_tool_callback_complete",
            sid=session_id,
            tool_name=pending.tool_name,
            next_component=((data.get("details") or {}).get("component")),
            has_next_pending=response.pending_elicitation is not None,
            is_error=response.is_error,
        )
        return response
