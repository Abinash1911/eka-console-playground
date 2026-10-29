import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from echo.llm.schemas import StreamEvent, StreamEventType
from echo.models.user_conversation import Message, MessageRole, TextMessage
from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from med_assist.service.voice import call_record
from med_assist.service.voice.agent_processor import EchoAgentProcessor
from med_assist.service.voice.call_record import CallFacts

CALLER = "+919876543210"


def _session(context=None):
    return SimpleNamespace(
        session_id="sess-1",
        initial_context=json.dumps(
            context if context is not None else {"channel": "vobiz", "caller": CALLER}
        ),
    )


def _message(role):
    return Message(
        msg_id=f"m-{role}", role=role, content=[TextMessage(type="text", text="hi")], timestamp=1
    )


class TestMaskNumber:
    def test_keeps_the_country_prefix_and_the_last_four_digits(self):
        assert call_record.mask_number("+919876543210") == "+91xxxxxx3210"
        assert call_record.mask_number("+14155550100") == "+14xxxxx0100"

    @pytest.mark.parametrize("value", [None, "", "9876543210", "+91", "call me", "+91987654321x"])
    def test_anything_else_is_not_shown(self, value):
        assert call_record.mask_number(value) is None

    def test_the_full_number_is_not_in_the_mask(self):
        assert "98765" not in call_record.mask_number(CALLER)


class TestFacts:
    def test_the_first_reason_a_call_ended_wins(self):
        facts = CallFacts()
        facts.end("transferred")
        facts.end("caller_hung_up")  # the stream closing after a transfer
        assert facts.ended_by == "transferred"

    def test_the_context_has_only_what_the_console_needs(self):
        facts = CallFacts(
            started=100.0,
            user_turns=4,
            handover="transferred",
            tools_used=["book", "book", "lookup"],
        )
        facts.end("silence")
        with patch.object(call_record.time, "monotonic", return_value=231.4):
            assert call_record.to_context(facts, CALLER) == {
                "call": {
                    "v": 1,
                    "duration_s": 131,
                    "ended_by": "silence",
                    "user_turns": 4,
                    "handover": "transferred",
                    "tools": ["book", "lookup"],
                    "caller": "+91xxxxxx3210",
                }
            }

    def test_without_a_valid_caller_the_field_is_left_out(self):
        assert "caller" not in call_record.to_context(CallFacts(), None)["call"]
        assert "caller" not in call_record.to_context(CallFacts(), "private")["call"]

    def test_a_call_with_no_recorded_end_counts_as_the_caller_leaving(self):
        assert call_record.to_context(CallFacts(), None)["call"]["ended_by"] == "caller_hung_up"


@pytest.mark.asyncio
class TestSave:
    async def test_merges_the_call_into_the_session_context_in_the_sessions_region(self):
        update = AsyncMock()
        with (
            patch.object(call_record, "update_session_context", update),
            patch.object(call_record, "session_region", AsyncMock(return_value="IN")),
        ):
            facts = CallFacts()
            facts.end("silence")
            await call_record.save(_session(), facts)
        sid, context, region = update.await_args.args
        assert (sid, region) == ("sess-1", "IN")
        assert set(context) == {"call"}
        assert context["call"]["caller"] == "+91xxxxxx3210"
        assert CALLER not in json.dumps(context)  # only the masked number goes into the record

    async def test_a_failure_is_logged_not_raised(self):
        with (
            patch.object(
                call_record, "update_session_context", AsyncMock(side_effect=RuntimeError("down"))
            ),
            patch.object(call_record, "session_region", AsyncMock(return_value="IN")),
            patch.object(call_record, "logger") as logger,
        ):
            await call_record.save(_session(), CallFacts())
        logger.error.assert_called_once()

    async def test_finish_counts_caller_turns_and_notes_the_handover(self):
        update = AsyncMock()
        facts = CallFacts()
        history = [
            _message(MessageRole.ASSISTANT),
            _message(MessageRole.USER),
            _message(MessageRole.USER),
        ]
        with (
            patch.object(call_record, "update_session_context", update),
            patch.object(call_record, "session_region", AsyncMock(return_value="IN")),
        ):
            await call_record.finish(_session(), facts, history, ["lookup"], "declined")
        call = update.await_args.args[1]["call"]
        assert (call["user_turns"], call["handover"], call["tools"]) == (2, "declined", ["lookup"])

    async def test_finish_says_none_when_there_was_no_handover(self):
        update = AsyncMock()
        with (
            patch.object(call_record, "update_session_context", update),
            patch.object(call_record, "session_region", AsyncMock(return_value="IN")),
        ):
            await call_record.finish(_session(), CallFacts(), [], [], None)
        assert update.await_args.args[1]["call"]["handover"] == "none"


class _FakeAgent:
    def __init__(self, events):
        self._events = events

    async def run_stream(self, context, out_msg_id):
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_the_agent_processor_notes_which_tools_the_agent_called():
    events = [
        StreamEvent(
            type=StreamEventType.TOOL_CALL_START,
            details={"tool_id": "t1", "tool_name": "search_doctors"},
        ),
        StreamEvent(
            type=StreamEventType.TOOL_CALL_START, details={"tool_id": "t2"}
        ),  # no name: ignored
        StreamEvent(
            type=StreamEventType.TOOL_CALL_START,
            details={"tool_id": "t3", "tool_name": "book_appointment"},
        ),
        StreamEvent(type=StreamEventType.TEXT, text="Booked."),
        StreamEvent(type=StreamEventType.DONE),
    ]
    processor = EchoAgentProcessor(_FakeAgent(events), session_id="sess-1")
    processor.push_frame = AsyncMock()
    frame = LLMContextFrame(
        context=LLMContext(messages=[{"role": "user", "content": "book me a doctor"}])
    )
    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert processor.tools_used == ["search_doctors", "book_appointment"]
    assert (
        processor.get_conversation_history()[-1].content[0].text == "Booked."
    )  # the reply still works
