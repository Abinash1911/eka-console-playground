"""
Voice router — WebRTC signaling endpoint for Pipecat voice sessions.

POST /offer — accepts SDP offer, creates pipeline, returns SDP answer.
GET  /client — serves test WebRTC UI (dev only).
"""

import base64
import time

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from common.config import get_config
import uuid

from common.schemas import RequestContext
from common.utils import get_logger
from common.utils.exceptions import (
    AgentNotFound,
    AuthError,
    InvalidAgent,
    SessionNotFound,
    SessionNotOwned,
)
from med_assist.models.schemas.session import CreateSessionRequest
from med_assist.service.auth.tokens.access import parse_authenticated_request
from med_assist.service.manage_session import create_session, get_session, owns_session
from med_assist.service.voice import telephony_auth
from med_assist.service.voice.twilio_ice import get_ice_servers_payload
from med_assist.service.voice.webrtc_signaling import handle_webrtc_offer
from med_assist.utils.agent_config_utils import get_agent_runtime_config
from common.utils import bind_request_context
from med_assist.utils.session_utils import get_session_from_cache

logger = get_logger("med_assist.router.voice")
router = APIRouter()

#! SECURITY
# /answer is guarded by a shared secret (?key=) and hands Vobiz a signed, short-lived WS token — see
# med_assist/service/voice/telephony_auth.py. Both apply only once VOICE_TELEPHONY_SECRET is set; until then
# /answer is open (agent_id is a forgeable query param) and a warning is logged on every call.


@router.post("/offer")
async def webrtc_offer(
    request: dict,
    background_tasks: BackgroundTasks,
    req_agent: RequestContext = Depends(parse_authenticated_request),
):
    """
    WebRTC signaling endpoint.

    1. Confirms the sess_token owns the session named in request_data
    2. Fetches agent config
    3. Creates WebRTC connection + Pipecat pipeline (runs in background)
    4. Returns SDP answer for client to complete handshake
    """
    bind_request_context(agent_id=req_agent.agent_id, wid=req_agent.wid)
    try:
        response = await handle_webrtc_offer(request, background_tasks, req_agent)
        logger.info(
            "WebRTC offer ok",
            fn="webrtc_offer",
            sid=(request or {}).get("session_id"),
            resp_code=200,
        )
        return response
    except InvalidAgent as ia:
        logger.error(
            "WebRTC offer rejected — invalid agent",
            fn="webrtc_offer",
            error=ia.message,
            resp_code=ia.status_code,
        )
        return JSONResponse(
            content={"error": {"code": ia.code, "msg": ia.message}},
            status_code=ia.status_code,
        )
    except HTTPException as he:
        logger.warning(
            "WebRTC offer rejected",
            fn="webrtc_offer",
            error=he.detail,
            resp_code=he.status_code,
        )
        raise
    except Exception as e:
        logger.error(
            "WebRTC offer failed",
            fn="webrtc_offer",
            error=str(e),
            error_type=type(e).__name__,
            resp_code=500,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to establish voice session")


@router.post("/answer")
async def vobiz_answer(
    agent_id: str = Query(..., description="Agent ID for this call"),
    key: Optional[str] = Query(None, description="Shared secret set on the Vobiz answer URL"),
    # Vobiz/Plivo sends these as form-encoded POST body
    From: Optional[str] = Form(None),
    To: Optional[str] = Form(None),
    CallUUID: Optional[str] = Form(None),
):
    """
    Vobiz telephony answer endpoint.

    Called by Vobiz when a phone call is answered. Creates a new session and
    returns XML instructing Vobiz to open a bidirectional audio WebSocket stream.

    Configure the answer URL in Vobiz as:
        https://<host>/reloaded/med-assist/voice/answer?agent_id=<id>&wid=<wid>&key=<VOICE_TELEPHONY_SECRET>
    """
    session_id = None
    bind_request_context(agent_id=agent_id)
    try:
        if not telephony_auth.answer_key_ok(key):
            logger.warning(
                "Vobiz answer rejected — bad or missing key",
                fn="vobiz_answer",
                agent_id=agent_id,
                resp_code=403,
            )
            raise HTTPException(status_code=403, detail="Forbidden")
        telephony_auth.warn_if_open()

        # Validate agent exists
        if not agent_id:
            raise HTTPException(
                status_code=400, detail="x-agent-id header is mandatory"
            )

        try:
            decoded_agent_id_headers = base64.b64decode(agent_id).decode("utf-8")
        except Exception:
            raise HTTPException(status_code=403, detail="Malformed agent token")

        wid = decoded_agent_id_headers.split("#")[1]
        bind_request_context(wid=wid)
        if From:
            if From.startswith("%2B"):
                From = From.replace("%2B", "+")
            if not From.startswith("+"):
                From = "+" + From

        # Create a new session for this phone call
        req_agent = RequestContext(
            agent_id=agent_id,
            wid=wid,
            userid=str(uuid.uuid4()),
            level="guest",
            client_id="vobiz",
            device_id=CallUUID,
        )

        request_body = CreateSessionRequest(
            # caller identity travels in session_context; the body carries no identity
            session_context={
                "channel": "vobiz",
                "caller": From,
                "callee": To,
                "call_uuid": CallUUID,
            },
            referer="vobiz-telephony",
        )

        session_response = await create_session(
            req_agent, request_body, save_initial_msg=True
        )
        session_id = session_response.session_id
        bind_request_context(session_id=session_id)
        # Vobiz has no interactive auth path to mint a sess_token, so the WS is
        # authenticated with a short-lived HMAC token for this session instead
        # (empty, and not checked, until VOICE_TELEPHONY_SECRET is set).
        ws_token = telephony_auth.sign_ws_token(session_id)

        # Build WebSocket URL for Vobiz to connect to
        public_url = get_config()["HOST"]
        if not public_url:
            raise HTTPException(status_code=500, detail="PUBLIC_URL not configured")

        # Convert http(s) to ws(s)
        ws_base = public_url.replace("https://", "wss://").replace("http://", "ws://")
        if "matrix.eka.care" in ws_base:
            ws_base = ws_base.replace("matrix.eka.care", "matrix-ws.eka.care")

        ws_url = f"{ws_base}/reloaded/ws/med-assist/voice/session/{session_id}/"
        if ws_token:
            ws_url += f"?token={ws_token}"

        xml_response = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            '    <Stream bidirectional="true" '
            'contentType="audio/x-l16;rate=16000" '
            'audioTrack="inbound" '
            'streamTimeout="600" '
            'keepCallAlive="true">'
            f"{ws_url}"
            "</Stream>\n"
            "</Response>"
        )

        logger.info(
            "Vobiz answer — session created",
            fn="vobiz_answer",
            sid=session_id,
            agent_id=agent_id,
            call_uuid=CallUUID,
            ws_url=ws_url,
            resp_code=200,
        )

        return Response(content=xml_response, media_type="application/xml")

    except AgentNotFound:
        logger.warning(
            "Vobiz answer — agent not found",
            fn="vobiz_answer",
            agent_id=agent_id,
            resp_code=404,
        )
        raise HTTPException(status_code=404, detail="Agent configuration not found")
    except HTTPException as he:
        logger.warning(
            "Vobiz answer rejected",
            fn="vobiz_answer",
            agent_id=agent_id,
            error=he.detail,
            resp_code=he.status_code,
        )
        raise
    except Exception as e:
        logger.error(
            "Vobiz answer failed",
            fn="vobiz_answer",
            sid=session_id,
            agent_id=agent_id,
            error=str(e),
            error_type=type(e).__name__,
            resp_code=500,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to generate answer XML")


@router.get("/ice-servers")
async def ice_servers(
    session_id: str = Query(..., description="Session ID"),
    req_agent: RequestContext = Depends(parse_authenticated_request),
):
    """Return ICE servers for the browser RTCPeerConnection.

    Backed by Twilio NTS (cached in Redis until token expiry). In non-prod,
    falls back to public Google STUN if Twilio is unavailable; in prod,
    Twilio failures bubble up as 503.
    """
    bind_request_context(
        session_id=session_id, agent_id=req_agent.agent_id, wid=req_agent.wid
    )
    try:
        session_cache, _ = await get_session(session_id, req_agent)
        # 404, not 401 or 403 — the token is valid and unexpired, it just
        # isn't this session's owner, so no new credential can help.
        if not owns_session(req_agent.userid, session_cache):
            raise SessionNotOwned()

        servers = await get_ice_servers_payload()
        logger.info(
            "ICE servers ok",
            fn="ice_servers",
            sid=session_id,
            server_count=len(servers or []),
            resp_code=200,
        )
        return {"ice_servers": servers}
    except AuthError:
        # Carries its own code/status — the `except Exception` below would
        # otherwise bury a 403 under a generic 503.
        raise
    except SessionNotFound:
        logger.warning(
            "Session not found", fn="ice_servers", sid=session_id, resp_code=404
        )
        raise HTTPException(status_code=404, detail="Session not found")
    except InvalidAgent as ia:
        logger.error(
            "Invalid agent",
            fn="ice_servers",
            sid=session_id,
            error=ia.message,
            resp_code=ia.status_code,
        )
        return JSONResponse(
            content={"error": {"code": ia.code, "msg": ia.message}},
            status_code=ia.status_code,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to fetch ICE servers",
            fn="ice_servers",
            sid=session_id,
            error=str(e),
            error_type=type(e).__name__,
            resp_code=503,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="ICE servers unavailable")


@router.get("/client")
async def voice_test_client():
    """Serve the voice test HTML page (dev only)."""
    if get_config()["CURR_ENV"] != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    html_path = Path(__file__).parent.parent / "static" / "voice_test.html"
    try:
        content = html_path.read_text()
    except OSError as e:
        # No try/except here originally, so a read failure was an unlogged
        # raw 500. Log it, then let the same exception propagate unchanged.
        logger.error(
            "voice test client unavailable",
            fn="voice_test_client",
            path=str(html_path),
            error=str(e),
            resp_code=500,
        )
        raise
    logger.info("voice test client served", fn="voice_test_client", resp_code=200)
    return HTMLResponse(content=content)


""" 

DEV:
curl -X POST \
    'https://kamilah-uncensuring-cubistically.ngrok-free.dev/reloaded/med-assist/voice/answer?agent_id=YjY3ODJiNGYtNmM5My00MmYxLWJjYzMtM2Y0MmZjNzYxNzZlIzE3MDE0MjYxMjk4NTU4OA==' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'From=%2B919876543210&To=%2B911234567890&CallUUID=f47ac10b-58cc-4372-a567-0e02b2c3d479'

PROD
curl -X POST \
    'https://matrix.eka.care/reloaded/med-assist/voice/answer?agent_id=MzNlOTk3YjctZDMyNy00NzU1LWI2YmYtMTQxNWNhNjZjOWMzIzc3MDg4MTY2OTk2NzI0' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'From=%2B919876543210&To=%2B911234567890&CallUUID=f47ac10b-58cc-4372-a567-0e02b2c3d479'

  The endpoint returns XML instructing Vobiz to open a bidirectional audio WebSocket stream:

  <?xml version="1.0" encoding="UTF-8"?>
  <Response>
      <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000" keepCallAlive="true">
        wss://<host>/reloaded/ws/med-assist/voice/session/<session_id>/?token=<jwt_token>
      </Stream>
  </Response>

"""
