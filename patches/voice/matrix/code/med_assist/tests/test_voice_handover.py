import asyncio
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import orjson
import pytest
from fastapi import HTTPException
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseEndFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from common.utils.exceptions import SessionNotFound
from med_assist.service.voice import handover, handover_settings, telephony_auth, telephony_binding
from med_assist.service.voice.handover_processor import FAILURE_MESSAGE, HandoverProcessor
from med_assist.service.voice.handover_settings import HandoverSettings
from med_assist.service.voice.handover_tool import HandoverState, TransferToHumanTool

IST = ZoneInfo("Asia/Kolkata")
SECRET = "s3cret-value"
WORKSPACE = "b-1708593434660086"
AGENT_ID = base64.b64encode(f"agent-uuid#{WORKSPACE}".encode()).decode()
NUMBER_UUID = "0e01e91b-dd5b-4055-9a4c-19742b1325a9"
STAFF = "+919999911111"
CONFIG = {
    "handover": {"number": STAFF, "hours": {"start": "09:00", "end": "18:00"}, "ring_seconds": 25}
}


def _settings(**overrides):
    return HandoverSettings.model_validate({**CONFIG["handover"], **overrides})


def _at(hour, minute=0, tz=IST):
    return datetime(2026, 10, 29, hour, minute, tzinfo=tz)


def _secret(value=SECRET):
    return patch.object(
        telephony_auth,
        "get_config_value",
        lambda key, default=None: value if key == "VOICE_TELEPHONY_SECRET" else default,
    )


def _host():
    return patch.object(handover, "get_config", lambda: {"HOST": "https://matrix.test"})


class TestSettings:
    def test_reads_the_binding_config_from_a_dict_or_json(self):
        assert handover_settings.from_binding_config(CONFIG).number == STAFF
        assert handover_settings.from_binding_config(orjson.dumps(CONFIG)).ring_seconds == 25
        assert handover_settings.from_binding_config(orjson.dumps(CONFIG).decode()).number == STAFF

    @pytest.mark.parametrize(
        "config",
        [
            None,
            {},
            {"handover": None},
            "not json",
            {"handover": {"number": "99999"}},
            {"handover": {"number": STAFF, "ring_seconds": 3}},
            {"handover": {"number": STAFF, "hours": {"start": "9am", "end": "18:00"}}},
            {
                "handover": {
                    "number": STAFF,
                    "hours": {"start": "09:00", "end": "18:00", "timezone": "Mars/Base"},
                }
            },
        ],
    )
    def test_anything_unusable_means_no_handover_not_a_crash(self, config):
        assert handover_settings.from_binding_config(config) is None

    def test_a_bad_number_is_not_echoed_into_the_logs(self):
        with patch.object(handover_settings, "logger") as logger:
            handover_settings.from_binding_config({"handover": {"number": "SECRET-ish-123"}})
        assert "SECRET-ish-123" not in str(logger.warning.call_args)

    def test_staff_hours(self):
        s = _settings()
        assert s.is_open(_at(9, 0)) is True  # start is inclusive
        assert s.is_open(_at(17, 59)) is True
        assert s.is_open(_at(18, 0)) is False  # end is exclusive
        assert s.is_open(_at(3, 0)) is False

    def test_hours_are_read_in_the_clinics_timezone(self):
        s = _settings()
        assert (
            s.is_open(datetime(2026, 10, 29, 4, 30, tzinfo=timezone.utc)) is True
        )  # 10:00 in India
        # 13:00 UTC looks like office hours on a UTC clock, but it is 18:30 in India.
        assert s.is_open(datetime(2026, 10, 29, 13, 0, tzinfo=timezone.utc)) is False

    def test_overnight_hours(self):
        s = _settings(hours={"start": "22:00", "end": "06:00"})
        assert s.is_open(_at(23, 0)) is True
        assert s.is_open(_at(5, 59)) is True
        assert s.is_open(_at(12, 0)) is False

    def test_no_hours_means_always_open(self):
        assert _settings(hours=None).is_open(_at(3, 0)) is True
        assert _settings(hours=None).hours_text() == "any time"


def _row(**overrides):
    row = {
        "workspace_id": WORKSPACE,
        "channel": "telephony",
        "provider": "vobiz",
        "is_active": True,
        "archived_at": None,
        "product": "agent",
        "product_id": AGENT_ID,
        "binding_active": True,
        "config": orjson.dumps(CONFIG).decode(),
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
class TestHandoverForNumber:
    async def _lookup(self, row):
        pg = MagicMock()
        pg.fetch_one = AsyncMock(return_value=row)
        with patch.object(telephony_binding, "get_pg_client", lambda: pg):
            return await telephony_binding.handover_for_number(NUMBER_UUID)

    async def test_returns_the_settings_for_a_served_number(self):
        assert (await self._lookup(_row())).number == STAFF

    async def test_none_when_the_number_has_no_handover(self):
        assert await self._lookup(_row(config="{}")) is None

    async def test_none_when_the_number_is_not_served(self):
        assert await self._lookup(_row(binding_active=False)) is None
        assert await self._lookup(None) is None


class TestXml:
    def test_transfer_xml_rings_the_staff_phone_from_the_dialled_number(self):
        with _secret(), _host():
            root = ET.fromstring(handover.transfer_xml(_settings(), "sess-1", "+918000012345"))
        dial = root.find("Dial")
        assert dial.get("callerId") == "+918000012345"
        assert dial.get("timeout") == "25"
        assert dial.get("redirect") == "true"
        assert dial.find("Number").text == STAFF
        action = dial.get("action")
        assert action.startswith(
            "https://matrix.test/reloaded/med-assist/voice/transfer-result/sess-1?token="
        )

    def test_caller_id_is_left_out_when_unknown_or_not_a_phone_number(self):
        with _secret(), _host():
            for callee in (None, "", "not-a-number", '+91"><Hangup/>'):
                dial = ET.fromstring(handover.transfer_xml(_settings(), "sess-1", callee)).find(
                    "Dial"
                )
                assert dial.get("callerId") is None

    def test_result_urls_carry_tokens_that_open_only_their_own_door(self):
        with _secret(), _host():
            url = handover.result_url("sess-1")
            token = url.split("?token=")[1]
            assert telephony_auth.verify_ws_token(
                "sess-1", token, purpose=handover.TRANSFER_PURPOSE
            )
            assert not telephony_auth.verify_ws_token(
                "sess-1", token
            )  # not the audio-socket purpose

    def test_a_finished_call_hangs_up_and_anything_else_apologises(self):
        done = ET.fromstring(handover.result_xml("completed"))
        assert [e.tag for e in done] == ["Hangup"]
        for status in ("busy", "no-answer", "failed", "timeout", "", None):
            tags = [e.tag for e in ET.fromstring(handover.result_xml(status))]
            assert tags == ["Speak", "Hangup"]


def _vobiz_client(response=None, error=None):
    """A stand-in for httpx.AsyncClient that records the POST."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=error, return_value=response)
    holder = MagicMock()
    holder.__aenter__ = AsyncMock(return_value=client)
    holder.__aexit__ = AsyncMock(return_value=False)
    return client, patch.object(handover.httpx, "AsyncClient", MagicMock(return_value=holder))


@pytest.mark.asyncio
class TestRequestTransfer:
    ENV = {"VOBIZ_AUTH_ID": "MA_TEST", "VOBIZ_AUTH_TOKEN": "tok"}

    async def test_sends_the_documented_transfer_request(self):
        client, patched = _vobiz_client(SimpleNamespace(status_code=202))
        with patched, patch.dict("os.environ", self.ENV):
            assert (
                await handover.request_transfer("call-1", "https://matrix.test/t?token=x") is True
            )
        args, kwargs = client.post.await_args
        assert args[0] == "https://api.vobiz.ai/api/v1/Account/MA_TEST/Call/call-1/"
        assert kwargs["headers"] == {"X-Auth-ID": "MA_TEST", "X-Auth-Token": "tok"}
        assert kwargs["json"] == {
            "legs": "aleg",
            "aleg_url": "https://matrix.test/t?token=x",
            "aleg_method": "POST",
        }

    async def test_the_api_base_can_be_overridden(self):
        client, patched = _vobiz_client(SimpleNamespace(status_code=202))
        with (
            patched,
            patch.dict("os.environ", {**self.ENV, "VOBIZ_API_BASE_URL": "https://api.test/v1/"}),
        ):
            await handover.request_transfer("call-1", "https://x")
        assert client.post.await_args.args[0] == "https://api.test/v1/Account/MA_TEST/Call/call-1/"

    @pytest.mark.parametrize("status", [400, 401, 404, 500])
    async def test_a_refusal_is_false_and_the_token_is_not_logged(self, status):
        _, patched = _vobiz_client(SimpleNamespace(status_code=status))
        with (
            patched,
            patch.dict("os.environ", self.ENV),
            patch.object(handover, "logger") as logger,
        ):
            assert await handover.request_transfer("call-1", "https://x/t?token=TOPSECRET") is False
        assert "TOPSECRET" not in str(logger.error.call_args)

    async def test_a_network_error_is_false_not_an_exception(self):
        _, patched = _vobiz_client(error=handover.httpx.ConnectTimeout("slow"))
        with patched, patch.dict("os.environ", self.ENV):
            assert await handover.request_transfer("call-1", "https://x") is False


def _session(context=None, session_id="sess-1"):
    return SimpleNamespace(
        session_id=session_id,
        agent_id=AGENT_ID,
        wid=WORKSPACE,
        initial_context=orjson.dumps(
            context
            if context is not None
            else {
                "channel": "vobiz",
                "caller": "+919876543210",
                "callee": "+918000012345",
                "call_uuid": "call-1",
                "integration_uuid": NUMBER_UUID,
            }
        ).decode(),
    )


@pytest.mark.asyncio
class TestOfferForCall:
    ENV = {"VOBIZ_AUTH_ID": "MA_TEST", "VOBIZ_AUTH_TOKEN": "tok"}

    async def _offer(
        self, session=None, call_id="call-1", secret=SECRET, env=None, settings=None, host=True
    ):
        env = self.ENV if env is None else env
        found = AsyncMock(return_value=_settings() if settings is None else settings)
        with (
            _secret(secret),
            patch.dict("os.environ", env, clear=False),
            patch.object(telephony_binding, "handover_for_number", found),
            patch.object(
                handover, "get_config", lambda: {"HOST": "https://matrix.test"} if host else {}
            ),
        ):
            return await handover.offer_for_call(session or _session(), call_id), found

    async def test_offered_when_everything_is_in_place(self):
        offer, found = await self._offer()
        assert offer.settings.number == STAFF
        found.assert_awaited_once_with(NUMBER_UUID)

    async def test_the_transfer_moves_the_call_to_the_signed_transfer_url(self):
        offer, _ = await self._offer(call_id="stream-call-9")
        with (
            _secret(),
            _host(),
            patch.object(handover, "request_transfer", AsyncMock(return_value=True)) as req,
        ):
            assert await offer.transfer() is True
        call_uuid, url = req.await_args.args
        assert call_uuid == "stream-call-9"  # the stream's call id wins over the answer's
        assert url.startswith(
            "https://matrix.test/reloaded/med-assist/voice/transfer/sess-1?token="
        )

    async def test_falls_back_to_the_call_id_from_the_answer(self):
        offer, _ = await self._offer(call_id="")
        with (
            _secret(),
            _host(),
            patch.object(handover, "request_transfer", AsyncMock(return_value=True)) as req,
        ):
            await offer.transfer()
        assert req.await_args.args[0] == "call-1"

    async def test_not_offered_without_the_shared_secret(self):
        offer, found = await self._offer(secret=None)
        assert offer is None
        found.assert_not_awaited()

    async def test_not_offered_without_vobiz_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            offer, _ = await self._offer(env={})
        assert offer is None

    async def test_not_offered_without_a_public_host(self):
        offer, _ = await self._offer(host=False)
        assert offer is None

    async def test_not_offered_without_a_call_id(self):
        session = _session({"channel": "vobiz", "integration_uuid": NUMBER_UUID})
        offer, _ = await self._offer(session=session, call_id="")
        assert offer is None

    async def test_not_offered_for_a_legacy_answer_url_with_no_number(self):
        session = _session({"channel": "vobiz", "call_uuid": "call-1"})
        offer, _ = await self._offer(session=session)
        assert offer is None


@pytest.mark.asyncio
class TestTool:
    def _tool(self, state=None, now=None, **settings):
        state = state or HandoverState()
        return TransferToHumanTool(_settings(**settings), state, "sess-1", now=now), state

    async def test_inside_staff_hours_it_marks_the_transfer_and_tells_the_agent_to_say_one_sentence(
        self,
    ):
        tool, state = self._tool(now=_at(10))
        text = await tool.run(reason="caller_asked")
        assert state.requested is True and state.reason == "caller_asked"
        assert "ONE short sentence" in text

    async def test_outside_staff_hours_it_declines_and_says_when_they_are_in(self):
        tool, state = self._tool(now=_at(21))
        text = await tool.run(reason="caller_asked")
        assert state.requested is False
        assert "09:00 to 18:00 (Asia/Kolkata)" in text
        assert "Do not transfer" in text

    async def test_asking_twice_does_not_transfer_twice(self):
        tool, _ = self._tool(now=_at(10))
        await tool.run(reason="caller_asked")
        assert "already in progress" in await tool.run(reason="caller_asked")

    async def test_an_unknown_reason_is_treated_as_other(self):
        tool, state = self._tool(now=_at(10))
        await tool.run(reason="because")
        assert state.reason == "other"


def test_the_tool_is_valid_for_the_llm():
    schema = TransferToHumanTool(_settings(), HandoverState(), "sess-1").to_anthropic_schema()
    assert schema["name"] == "transfer_to_human"
    assert schema["input_schema"]["properties"]["reason"]["enum"]
    assert schema["input_schema"]["required"] == ["reason"]


class _Pushed:
    def __init__(self):
        self.frames = []

    async def __call__(self, frame, direction=FrameDirection.DOWNSTREAM):
        self.frames.append(frame)


def _processor(requested=True, transfer_ok=True, settle=0.01, grace=0.15):
    state = HandoverState(requested=requested)
    transfer = AsyncMock(return_value=transfer_ok)
    processor = HandoverProcessor(state, transfer, "sess-1", settle_secs=settle, grace_secs=grace)
    pushed = _Pushed()
    processor.push_frame = pushed
    return processor, state, transfer, pushed


async def _send(processor, *frames):
    for frame in frames:
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)


@pytest.mark.asyncio
class TestProcessor:
    async def test_transfers_once_the_reply_is_over_and_the_caller_has_heard_it(self):
        processor, _, transfer, pushed = _processor()
        await _send(processor, LLMFullResponseEndFrame(), BotStoppedSpeakingFrame())
        await asyncio.sleep(0.08)
        transfer.assert_awaited_once()
        assert len(pushed.frames) == 2  # frames always pass through

    async def test_does_not_transfer_on_a_pause_before_the_reply_has_ended(self):
        processor, _, transfer, _ = _processor()
        await _send(processor, BotStoppedSpeakingFrame())
        await asyncio.sleep(0.08)
        transfer.assert_not_awaited()
        await processor.cleanup()

    async def test_a_pause_between_sentences_does_not_transfer_early(self):
        processor, _, transfer, _ = _processor(settle=0.05)
        await _send(
            processor,
            LLMFullResponseEndFrame(),
            BotStoppedSpeakingFrame(),
            BotStartedSpeakingFrame(),
        )
        await asyncio.sleep(0.1)
        transfer.assert_not_awaited()
        await _send(processor, BotStoppedSpeakingFrame())
        await asyncio.sleep(0.12)
        transfer.assert_awaited_once()
        await processor.cleanup()

    async def test_a_silent_reply_still_transfers_after_the_grace_period(self):
        processor, _, transfer, _ = _processor(grace=0.05)
        await _send(processor, LLMFullResponseEndFrame())
        await asyncio.sleep(0.15)
        transfer.assert_awaited_once()

    async def test_nothing_happens_unless_the_tool_asked(self):
        processor, _, transfer, _ = _processor(requested=False)
        await _send(processor, LLMFullResponseEndFrame(), BotStoppedSpeakingFrame())
        await asyncio.sleep(0.2)
        transfer.assert_not_awaited()

    async def test_the_transfer_is_started_only_once(self):
        processor, _, transfer, _ = _processor(settle=0.01, grace=0.05)
        await _send(processor, LLMFullResponseEndFrame(), BotStoppedSpeakingFrame())
        await asyncio.sleep(0.2)  # the grace timer fires too
        transfer.assert_awaited_once()

    async def test_when_vobiz_refuses_the_caller_is_told_and_the_agent_may_try_again(self):
        processor, state, transfer, pushed = _processor(transfer_ok=False, settle=0.01, grace=0.1)
        await _send(processor, LLMFullResponseEndFrame(), BotStoppedSpeakingFrame())
        await asyncio.sleep(0.04)  # refused; the first attempt's grace timer is still pending
        spoken = [f for f in pushed.frames if isinstance(f, TTSSpeakFrame)]
        assert [f.text for f in spoken] == [FAILURE_MESSAGE]
        assert state.requested is False

        # The agent asks again straight away. The first attempt's timer must not
        # fire for this one before its reply has even ended.
        state.requested = True
        transfer.return_value = True
        await asyncio.sleep(0.15)
        assert transfer.await_count == 1
        await _send(processor, LLMFullResponseEndFrame(), BotStoppedSpeakingFrame())
        await asyncio.sleep(0.06)
        assert transfer.await_count == 2


def _answer_context(create):
    _, body = create.await_args.args
    return body.session_context


@pytest.mark.asyncio
class TestRoutes:
    async def _call(self, route, *args, **kwargs):
        from med_assist.router import voice

        return await getattr(voice, route)(*args, **kwargs)

    def _good(self, session_id="sess-1"):
        with _secret():
            return telephony_auth.sign_ws_token(session_id, purpose=handover.TRANSFER_PURPOSE)

    async def _transfer(self, token, session=None, settings=None, lookup_error=None):
        with (
            _secret(),
            _host(),
            patch(
                "med_assist.router.voice.get_session_from_cache",
                AsyncMock(side_effect=lookup_error, return_value=session or _session()),
            ),
            patch.object(
                handover,
                "settings_for_session",
                AsyncMock(return_value=_settings() if settings is None else settings),
            ),
        ):
            return await self._call("vobiz_transfer", "sess-1", token=token)

    async def test_the_transfer_url_rings_the_staff_phone(self):
        response = await self._transfer(self._good())
        root = ET.fromstring(response.body)
        assert root.find("Dial/Number").text == STAFF
        assert root.find("Dial").get("callerId") == "+918000012345"

    async def test_the_transfer_url_refuses_a_missing_wrong_or_other_purpose_token(self):
        with _secret():
            ws_token = telephony_auth.sign_ws_token("sess-1")  # an audio-socket token
        for token in ("", "1.deadbeef", ws_token):
            with pytest.raises(HTTPException) as refused:
                await self._transfer(token)
            assert refused.value.status_code == 403

    async def test_the_transfer_url_is_off_without_the_shared_secret(self):
        with pytest.raises(HTTPException) as refused:
            with _secret(None), _host():
                await self._call("vobiz_transfer", "sess-1", token="")
        assert refused.value.status_code == 403

    async def test_the_transfer_url_404s_for_an_unknown_session_or_a_number_without_handover(self):
        token = self._good()
        with pytest.raises(HTTPException) as missing:
            await self._transfer(token, lookup_error=SessionNotFound())
        assert missing.value.status_code == 404
        with (
            _secret(),
            _host(),
            patch(
                "med_assist.router.voice.get_session_from_cache", AsyncMock(return_value=_session())
            ),
            patch.object(handover, "settings_for_session", AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as none_configured:
                await self._call("vobiz_transfer", "sess-1", token=token)
        assert none_configured.value.status_code == 404

    async def test_the_result_url_needs_the_token_and_answers_by_dial_status(self):
        token = self._good()
        with _secret():
            done = await self._call(
                "vobiz_transfer_result", "sess-1", token=token, DialStatus="completed"
            )
            missed = await self._call(
                "vobiz_transfer_result", "sess-1", token=token, DialStatus="no-answer"
            )
            with pytest.raises(HTTPException) as refused:
                await self._call(
                    "vobiz_transfer_result", "sess-1", token="", DialStatus="completed"
                )
        assert [e.tag for e in ET.fromstring(done.body)] == ["Hangup"]
        assert [e.tag for e in ET.fromstring(missed.body)] == ["Speak", "Hangup"]
        assert refused.value.status_code == 403

    async def test_the_answer_for_a_number_records_which_number_it_was(self):
        from med_assist.router.voice import vobiz_answer_for_number

        create = AsyncMock(return_value=SimpleNamespace(session_id="sess-1"))
        with (
            patch("med_assist.router.voice.create_session", create),
            patch(
                "med_assist.router.voice.get_config", lambda: {"HOST": "https://matrix.eka.care"}
            ),
            patch.object(telephony_binding, "agent_for_number", AsyncMock(return_value=AGENT_ID)),
        ):
            await vobiz_answer_for_number(
                NUMBER_UUID, From="+919876543210", To="+918000012345", CallUUID="call-1"
            )
        assert _answer_context(create)["integration_uuid"] == NUMBER_UUID

    async def test_the_legacy_answer_url_records_no_number_so_it_offers_no_handover(self):
        from med_assist.router.voice import vobiz_answer

        create = AsyncMock(return_value=SimpleNamespace(session_id="sess-1"))
        with (
            patch("med_assist.router.voice.create_session", create),
            patch(
                "med_assist.router.voice.get_config", lambda: {"HOST": "https://matrix.eka.care"}
            ),
            _secret(None),
        ):
            await vobiz_answer(
                AGENT_ID, key=None, From="+919876543210", To="+918000012345", CallUUID="call-1"
            )
        assert "integration_uuid" not in _answer_context(create)


@pytest.mark.asyncio
async def test_the_handover_tool_reaches_the_agent():
    from med_assist.service.voice import pipeline

    prompt = SimpleNamespace(task=SimpleNamespace(description="BASE"), timezone=None)
    agent_config = SimpleNamespace(
        prompt_config=object(),
        mcp_configs=None,
        knowledge_bases=None,
        custom_tools=None,
        primary_llm_config=None,
        workspace_id="w",
    )
    session_cache = SimpleNamespace(
        userid=None, session_id="sess-1", tz="Asia/Kolkata", wid=WORKSPACE, agent_id=AGENT_ID
    )
    tool = TransferToHumanTool(_settings(), HandoverState(), "sess-1")
    generic = MagicMock()
    with (
        patch.object(pipeline, "get_echo_agent_prompt", AsyncMock(return_value=prompt)),
        patch.object(pipeline, "enrich_prompt_with_kb_context", AsyncMock()),
        patch.object(pipeline, "session_region", AsyncMock(return_value="IN")),
        patch.object(pipeline, "GenericAgent", generic),
    ):
        await pipeline._build_agent(agent_config, session_cache, extra_tools=[tool])
        assert generic.call_args.kwargs["tools"] == [tool]
        await pipeline._build_agent(agent_config, session_cache)
        assert generic.call_args.kwargs["tools"] == []
