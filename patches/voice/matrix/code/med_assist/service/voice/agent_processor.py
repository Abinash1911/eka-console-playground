"""
EchoAgentProcessor — Pipecat FrameProcessor that bridges Pipecat's audio pipeline
to the existing GenericAgent (echo-agents) for LLM interaction.

Receives transcribed user text from the context aggregator, runs it through
GenericAgent.run_stream(), and pushes LLMTextFrames to the TTS stage.
ElevenLabs TTS handles sentence aggregation internally via TextAggregationMode.SENTENCE.

Conversation history is kept in-memory (no Redis) for the duration of the call.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import time
import uuid

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> str:
    return datetime.now(IST).strftime("%H:%M:%S.%f")[:-3]

from echo.agents.generic_agent import GenericAgent
from echo.llm.schemas import StreamEventType
from echo.models.user_conversation import (
    ConversationContext,
    Message,
    MessageRole,
    TextMessage,
)
from pipecat.frames.frames import (
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from common.utils import get_logger
from med_assist.config.voice import VOICE_PROFILING_ENABLED

logger = get_logger("med_assist.service.voice.agent_processor")

class EchoAgentProcessor(FrameProcessor):
    """
    Pipecat FrameProcessor that wraps GenericAgent for voice conversations.

    Pipeline position: after UserContextAggregator, before TTS.

    On receiving an LLMContextFrame (from the context aggregator),
    it extracts the latest user message, runs GenericAgent.run_stream(),
    and emits LLMTextFrames for the TTS stage. Sentence aggregation is
    handled by ElevenLabs TTS (TextAggregationMode.SENTENCE).
    """

    def __init__(
        self,
        agent: GenericAgent,
        session_id: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._agent = agent
        self._session_id = session_id
        self._conversation_history: list[Message] = []
        # Names of the tools the agent called, in order, for the call record.
        self.tools_used: list[str] = []

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        # Extract the latest user message from the LLMContext
        messages = frame.context.get_messages()
        if not messages:
            await self.push_frame(frame, direction)
            return

        # Find the last user message
        user_text = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        p.get("text", "") for p in content if p.get("type") == "text"
                    ]
                    user_text = " ".join(text_parts).strip()
                else:
                    user_text = str(content).strip()
                break

        if not user_text:
            await self.push_frame(frame, direction)
            return

        if VOICE_PROFILING_ENABLED:
            # Length, not content: this line is on whenever someone turns
            # VOICE_PROFILING_ENABLED on to debug the pipeline, and the
            # transcript is the patient speaking. redact_processor cannot
            # help here -- it matches keys, and this is an f-string.
            logger.info(f"[VOICE] {self._session_id} : stt_complete : {_ist_now()} : {len(user_text)} chars")

        # Append user message to in-memory conversation history
        msg_id = str(uuid.uuid4())[:8]
        user_message = Message(
            msg_id=f"voice-{msg_id}",
            role=MessageRole.USER,
            content=[TextMessage(type="text", text=user_text)],
            timestamp=int(time.time()),
        )
        self._conversation_history.append(user_message)

        # Build ConversationContext from full history
        context = ConversationContext(messages=list(self._conversation_history))

        # Generate a unique output message ID
        out_msg_id = f"voice-out-{msg_id}"

        # Signal start of LLM response
        await self.push_frame(LLMFullResponseStartFrame())

        # Run GenericAgent stream and push text chunks directly to TTS.
        # ElevenLabs TTS handles sentence aggregation (TextAggregationMode.SENTENCE).
        full_response = ""
        first_token_logged = False
        self._current_generator = None

        try:
            self._current_generator = self._agent.run_stream(context, out_msg_id)
            async for event in self._current_generator:
                if event.type == StreamEventType.TEXT:
                    chunk = event.text or ""
                    full_response += chunk

                    if not first_token_logged:
                        if VOICE_PROFILING_ENABLED:
                            logger.info(f"[VOICE] {self._session_id} : llm_first_byte : {_ist_now()}")
                        first_token_logged = True

                    # Push each chunk directly — TTS handles sentence buffering
                    if chunk:
                        await self.push_frame(LLMTextFrame(text=chunk))

                elif event.type == StreamEventType.DONE:
                    if VOICE_PROFILING_ENABLED:
                        logger.info(f"[VOICE] {self._session_id} : llm_done : {_ist_now()}")

                    # Append assistant response to conversation history
                    if full_response.strip():
                        assistant_message = Message(
                            msg_id=out_msg_id,
                            role=MessageRole.ASSISTANT,
                            content=[
                                TextMessage(type="text", text=full_response.strip())
                            ],
                            timestamp=int(time.time()),
                        )
                        self._conversation_history.append(assistant_message)

                elif event.type == StreamEventType.ERROR:
                    logger.error(
                        "Agent stream error in voice pipeline",
                        fn="process_frame",
                        error=str(event.error),
                    )

                elif event.type == StreamEventType.TOOL_CALL_START:
                    # Only noted for the call record; the caller cannot see a tool call.
                    name = (event.details or {}).get("tool_name")
                    if name:
                        self.tools_used.append(name)

                # TOOL_CALL_END is out of scope for voice

        except asyncio.CancelledError:
            logger.debug(
                "Agent stream cancelled (user interrupted)",
                fn="process_frame",
            )
            # Save whatever was generated so far to conversation history
            if full_response.strip():
                assistant_message = Message(
                    msg_id=out_msg_id,
                    role=MessageRole.ASSISTANT,
                    content=[TextMessage(type="text", text=full_response.strip())],
                    timestamp=int(time.time()),
                )
                self._conversation_history.append(assistant_message)
            raise  # Re-raise so Pipecat's task cancellation completes

        except Exception as e:
            logger.error(
                "Error running agent stream for voice",
                fn="process_frame",
                error=str(e),
            )
            await self.push_frame(
                TextFrame(text="Sorry, I encountered an error. Please try again.")
            )

        finally:
            # Close the async generator to clean up the HTTP stream promptly
            if self._current_generator is not None:
                await self._current_generator.aclose()
                self._current_generator = None
            # Signal end of LLM response — always push so downstream state stays consistent
            await self.push_frame(LLMFullResponseEndFrame())

    def get_conversation_history(self) -> list[Message]:
        """Return the in-memory conversation history (for transcript persistence)."""
        return list(self._conversation_history)
