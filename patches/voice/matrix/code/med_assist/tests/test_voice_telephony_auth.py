import base64
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from common.utils.exceptions import SessionNotFound
from med_assist.service.voice import telephony_auth

SECRET = "s3cret-value"
AGENT_ID = base64.b64encode(b"agent-uuid#wsp_1").decode()


def _configured(secret=SECRET):
    return patch.object(
        telephony_auth,
        "get_config_value",
        lambda key, default=None: secret if key == "VOICE_TELEPHONY_SECRET" else default,
    )


class TestAnswerKey:
    def test_open_when_no_secret_is_configured(self):
        with _configured(None):
            assert telephony_auth.is_enforced() is False
            assert telephony_auth.answer_key_ok(None) is True
            assert telephony_auth.answer_key_ok("anything") is True

    def test_requires_the_exact_key_when_configured(self):
        with _configured():
            assert telephony_auth.is_enforced() is True
            assert telephony_auth.answer_key_ok(SECRET) is True
            assert telephony_auth.answer_key_ok(None) is False
            assert telephony_auth.answer_key_ok("") is False
            assert telephony_auth.answer_key_ok(SECRET + "x") is False


class TestWsToken:
    def test_round_trip(self):
        with _configured():
            token = telephony_auth.sign_ws_token("sess-1", now=1000)
            assert telephony_auth.verify_ws_token("sess-1", token, now=1001) is True

    def test_bound_to_its_session(self):
        with _configured():
            token = telephony_auth.sign_ws_token("sess-1", now=1000)
            assert telephony_auth.verify_ws_token("sess-2", token, now=1001) is False

    def test_expires(self):
        with _configured():
            token = telephony_auth.sign_ws_token("sess-1", now=1000)
            last_ok = 1000 + telephony_auth.WS_TOKEN_TTL_SECS
            assert telephony_auth.verify_ws_token("sess-1", token, now=last_ok) is True
            assert telephony_auth.verify_ws_token("sess-1", token, now=last_ok + 1) is False

    def test_tampered_expiry_or_mac_is_refused(self):
        with _configured():
            expires_at, mac = telephony_auth.sign_ws_token("sess-1", now=1000).split(".")
            later = f"{int(expires_at) + 9999}.{mac}"
            assert telephony_auth.verify_ws_token("sess-1", later, now=1001) is False
            assert (
                telephony_auth.verify_ws_token("sess-1", f"{expires_at}.{'0' * 64}", now=1001)
                is False
            )

    @pytest.mark.parametrize("token", [None, "", "no-dot", "abc.def", "123.", "9999999999.é"])
    def test_malformed_tokens_are_refused(self, token):
        with _configured():
            assert telephony_auth.verify_ws_token("sess-1", token, now=1000) is False

    def test_a_token_signed_with_another_secret_is_refused(self):
        with _configured("other"):
            token = telephony_auth.sign_ws_token("sess-1", now=1000)
        with _configured():
            assert telephony_auth.verify_ws_token("sess-1", token, now=1001) is False

    def test_not_signed_and_not_checked_without_a_secret(self):
        with _configured(None):
            assert telephony_auth.sign_ws_token("sess-1") == ""
            assert telephony_auth.verify_ws_token("sess-1", None) is True


async def _answer(key=None):
    from med_assist.router.voice import vobiz_answer

    create = AsyncMock(return_value=SimpleNamespace(session_id="sess-1"))
    with (
        patch("med_assist.router.voice.create_session", create),
        patch("med_assist.router.voice.get_config", lambda: {"HOST": "https://matrix.eka.care"}),
    ):
        try:
            response = await vobiz_answer(
                agent_id=AGENT_ID,
                key=key,
                From="+919876543210",
                To="+911234567890",
                CallUUID="call-1",
            )
        except HTTPException as exc:
            return exc, create
    return response, create


@pytest.mark.asyncio
class TestAnswerEndpoint:
    async def test_rejects_a_missing_key_before_creating_a_session(self):
        with _configured():
            exc, create = await _answer(key=None)
        assert exc.status_code == 403
        create.assert_not_awaited()

    async def test_rejects_a_wrong_key(self):
        with _configured():
            exc, create = await _answer(key="wrong")
        assert exc.status_code == 403
        create.assert_not_awaited()

    async def test_good_key_returns_a_signed_socket_url(self):
        with _configured():
            response, create = await _answer(key=SECRET)
            create.assert_awaited_once()
            body = response.body.decode()
            url = re.search(r"<Stream[^>]*>([^<]+)</Stream>", body).group(1)
            assert url.startswith(
                "wss://matrix-ws.eka.care/reloaded/ws/med-assist/voice/session/sess-1/?token="
            )
            token = url.split("?token=")[1]
            assert telephony_auth.verify_ws_token("sess-1", token) is True

    async def test_unchanged_without_a_secret(self):
        with _configured(None):
            response, create = await _answer(key=None)
        create.assert_awaited_once()
        body = response.body.decode()
        assert "?token=" not in body
        assert "/reloaded/ws/med-assist/voice/session/sess-1/<" in body


async def _connect(token):
    from med_assist.router.voice_ws import vobiz_voice_ws

    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    lookup = AsyncMock(side_effect=SessionNotFound())
    with patch("med_assist.router.voice_ws.get_session_from_cache", lookup):
        await vobiz_voice_ws(websocket, "sess-1", token=token)
    return websocket, lookup


@pytest.mark.asyncio
class TestAudioSocket:
    async def test_refuses_a_bad_token_before_looking_up_the_session(self):
        with _configured():
            websocket, lookup = await _connect("1.deadbeef")
        websocket.close.assert_awaited_once()
        assert websocket.close.await_args.kwargs["code"] == 4001
        lookup.assert_not_awaited()

    async def test_refuses_a_missing_token(self):
        with _configured():
            websocket, lookup = await _connect("")
        assert websocket.close.await_args.kwargs["code"] == 4001
        lookup.assert_not_awaited()

    async def test_a_valid_token_passes_the_gate(self):
        with _configured():
            token = telephony_auth.sign_ws_token("sess-1")
            websocket, lookup = await _connect(token)
        lookup.assert_awaited_once_with("sess-1")
        # Got as far as the session lookup (which this test makes fail with 4004).
        assert websocket.close.await_args.kwargs["code"] == 4004

    async def test_unchanged_without_a_secret(self):
        with _configured(None):
            _, lookup = await _connect("")
        lookup.assert_awaited_once_with("sess-1")
