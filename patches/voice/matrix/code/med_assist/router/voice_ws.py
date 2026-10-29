"""
Voice WebSocket router — Vobiz telephony WebSocket endpoint for Pipecat voice sessions.

Handles bidirectional audio streaming over WebSocket using the Plivo/Vobiz protocol.
"""

import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from common.utils import (
    bind_request_context,
    bind_session_context,
    clear_session_context,
    get_logger,
)
from common.utils.exceptions import AgentNotFound, SessionNotFound
from med_assist.config.voice import (
    VOICE_LLM_MAX_ITERATIONS,
    VOICE_LLM_MAX_TOKENS,
    VOICE_LLM_MODEL,
    VOICE_LLM_PROVIDER,
    VOICE_LLM_TEMPERATURE,
)
from med_assist.models.agent_config import EncryptedLLMConfig
from med_assist.service.voice import telephony_auth
from med_assist.service.voice.pipeline import run_voice_ws_pipeline
from med_assist.utils.agent_config_utils import get_voice_config
from med_assist.utils.session_utils import get_runtime_config_from_session
from med_assist.utils.session_utils import get_session_from_cache

logger = get_logger("med_assist.router.voice_ws")
router = APIRouter()


@router.websocket("/session/{session_id}/")
async def vobiz_voice_ws(websocket: WebSocket, session_id: str, token: str = ""):
    """
    Vobiz telephony WebSocket endpoint.

    ``token`` is the short-lived HMAC token /voice/answer put on the URL; it is
    checked once VOICE_TELEPHONY_SECRET is set (see telephony_auth.py).

    1. Accepts the WebSocket connection
    2. Checks the token, then validates that the session exists
    3. Fetches agent config and voice config
    4. Runs the voice pipeline with FastAPIWebsocketTransport
    """
    clear_session_context()
    bind_session_context(session_id)
    bind_request_context(session_id=session_id)
    session_cache = None
    try:
        # Accept the WebSocket connection first (required by Vobiz protocol)
        await websocket.accept()

        # Vobiz has no interactive auth path to mint a sess_token, so the gate
        # is the HMAC token /voice/answer signed for this session. Checked
        # before the session is even looked up.
        if not telephony_auth.verify_ws_token(session_id, token):
            logger.warning(
                "Vobiz voice WebSocket rejected — bad or expired token",
                fn="vobiz_voice_ws",
                sid=session_id,
            )
            await websocket.close(code=4001, reason="Unauthorized")
            return
        telephony_auth.warn_if_open()

        # Validate session
        session_cache = await get_session_from_cache(session_id)
        bind_request_context(agent_id=session_cache.agent_id, wid=session_cache.wid)

        # Fetch agent config
        agent_config = await get_runtime_config_from_session(session_cache)

        if not agent_config.prompt_config:
            logger.warning(
                "No prompt config — closing 4002", fn="vobiz_voice_ws", sid=session_id
            )
            await websocket.close(code=4002, reason="Agent has no prompt configuration")
            return

        # Override the DB-sourced LLM with Anthropic Haiku 4.5 (direct API).
        # Bedrock ap-south-1 was adding ~1s TTFB per turn; the telephony UX needs
        # sub-second. Only applies to the Vobiz path — WebRTC keeps the DB LLM.
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            agent_config.primary_llm_config = EncryptedLLMConfig(
                provider=VOICE_LLM_PROVIDER,
                model=VOICE_LLM_MODEL,
                api_key=anthropic_key,
                temperature=VOICE_LLM_TEMPERATURE,
                max_tokens=VOICE_LLM_MAX_TOKENS,
                max_iterations=VOICE_LLM_MAX_ITERATIONS,
            )
            logger.info(
                "Voice LLM override → Anthropic",
                fn="vobiz_voice_ws",
                sid=session_id,
                provider=VOICE_LLM_PROVIDER,
                model=VOICE_LLM_MODEL,
            )
        else:
            logger.warning(
                "ANTHROPIC_API_KEY not set — falling back to agent DB LLM config",
                fn="vobiz_voice_ws",
                sid=session_id,
            )

        # Fetch voice config directly from DB (not cached in session)
        voice_config = await get_voice_config(agent_config.db_id)
        if not voice_config:
            logger.warning(
                "No voice config — closing 4003", fn="vobiz_voice_ws", sid=session_id
            )
            await websocket.close(code=4003, reason="Agent has no voice configuration")
            return
        if not voice_config.stt_config:
            logger.warning(
                "No STT config — closing 4003", fn="vobiz_voice_ws", sid=session_id
            )
            await websocket.close(code=4003, reason="STT API key not configured")
            return
        if not voice_config.tts_config:
            logger.warning(
                "No TTS config — closing 4003", fn="vobiz_voice_ws", sid=session_id
            )
            await websocket.close(code=4003, reason="TTS API key not configured")
            return

        logger.info(
            "All validations passed — starting voice pipeline",
            fn="vobiz_voice_ws",
            sid=session_id,
            agent_id=session_cache.agent_id,
        )

        # Run the voice pipeline (blocks until call ends)
        await run_voice_ws_pipeline(
            websocket, session_cache, agent_config, voice_config
        )
        logger.info("Voice pipeline finished", fn="vobiz_voice_ws", sid=session_id)

    except SessionNotFound:
        logger.warning("Session not found", fn="vobiz_voice_ws", sid=session_id)
        await websocket.close(code=4004, reason="Session not found")
    except AgentNotFound:
        logger.warning("Agent not found", fn="vobiz_voice_ws", sid=session_id)
        await websocket.close(code=4004, reason="Agent configuration not found")
    except WebSocketDisconnect:
        logger.info(
            "Vobiz voice WebSocket disconnected",
            fn="vobiz_voice_ws",
            sid=session_id,
        )
    except Exception as e:
        logger.error(
            "Vobiz voice WebSocket error",
            fn="vobiz_voice_ws",
            sid=session_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
