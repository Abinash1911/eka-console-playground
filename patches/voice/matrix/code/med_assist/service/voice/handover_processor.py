"""
Starts the transfer once the agent has finished saying it is connecting the caller.

Placed between the agent and text-to-speech in the phone pipeline. The tool only
sets ``HandoverState.requested``; this processor waits for the agent's reply to
end (``LLMFullResponseEndFrame``) and for the caller to have heard it
(``BotStoppedSpeakingFrame``, confirmed by a short settle so a pause between two
sentences does not count), then asks Vobiz to move the call. If the agent says
nothing, a timer starts the transfer anyway. If Vobiz refuses, the caller is told
and the agent can offer it again.
"""

import asyncio
from typing import Awaitable, Callable

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    LLMFullResponseEndFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from common.utils import get_logger
from med_assist.service.voice.handover_tool import HandoverState

logger = get_logger("med_assist.service.voice.handover_processor")

# After the bot stops, wait this long for it to start again (next sentence) before moving the call.
SETTLE_SECS = 0.5
# If the reply is never spoken (empty reply, TTS error), move the call after this long.
SILENT_REPLY_GRACE_SECS = 8
FAILURE_MESSAGE = "Sorry, I could not connect you right now. How else can I help you?"


class HandoverProcessor(FrameProcessor):
    def __init__(
        self,
        state: HandoverState,
        transfer: Callable[[], Awaitable[bool]],
        session_id: str,
        settle_secs: float = SETTLE_SECS,
        grace_secs: float = SILENT_REPLY_GRACE_SECS,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._state = state
        self._transfer = transfer
        self._session_id = session_id
        self._settle_secs = settle_secs
        self._grace_secs = grace_secs
        self._reply_ended = False
        self._bot_restarted = False
        self._started = False
        self._tasks: set[asyncio.Task] = set()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if not self._state.requested or self._started:
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            self._reply_ended = True
            self._spawn(self._after(self._grace_secs))
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_restarted = True
        elif isinstance(frame, BotStoppedSpeakingFrame) and self._reply_ended:
            self._bot_restarted = False
            self._spawn(self._after(self._settle_secs, only_if_quiet=True))

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _after(self, delay: float, only_if_quiet: bool = False):
        await asyncio.sleep(delay)
        if only_if_quiet and self._bot_restarted:
            return
        await self._start_transfer()

    async def _start_transfer(self):
        if self._started or not self._state.requested:
            return
        self._started = True
        if await self._transfer():
            self._state.outcome = "transferred"
            logger.info("Handover started", fn="_start_transfer", sid=self._session_id)
            return
        self._state.outcome = "failed"
        logger.error(
            "Handover failed — caller stays with the agent",
            fn="_start_transfer",
            sid=self._session_id,
            error="transfer request not accepted",
        )
        # Let the agent offer it again, and tell the caller now. Timers from this
        # attempt must not fire for the next one.
        self._cancel_pending()
        self._state.requested = False
        self._started = False
        self._reply_ended = False
        await self.push_frame(TTSSpeakFrame(text=FAILURE_MESSAGE))

    def _cancel_pending(self):
        for task in list(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()

    async def cleanup(self):
        await super().cleanup()
        self._cancel_pending()
