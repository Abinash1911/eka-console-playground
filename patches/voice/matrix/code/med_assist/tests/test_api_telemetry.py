"""Every API reports session_id / agent_id / wid in its logs, and every
request is logged.

The ask this guards: each endpoint must be debuggable from logs alone — you
should be able to find every request for a given session/agent/workspace, see
whether it succeeded, and see why it failed if it didn't. Endpoints that
legitimately have no identity to report (ping/health) are listed explicitly,
so adding one is a deliberate act rather than an omission.
"""

import base64
import inspect
import io
import json
import logging
import os
import re

import pytest
from unittest.mock import patch

os.environ.setdefault(
    "MATRIX",
    json.dumps(
        {
            "CURR_ENV": "prod",
            "TOKENSALT": "x",
            "AUTH_JWT_KEY": "Owpyr-uhQ1vQQkhj1IEyz-SYGNiwxDPJk3b7vxqfB9E",
        }
    ),
)

from fastapi.routing import APIRoute, APIWebSocketRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from common.utils import bind_request_context, collect_request_attributes  # noqa: E402

WID = "77088166996724"
AGENT_ID = base64.b64encode(f"uuid#{WID}".encode()).decode()

# Endpoints with no session, agent or workspace in scope. Liveness probes and
# the root banner — nothing to attribute a request to.
NO_IDENTITY_ENDPOINTS = {
    "root",
    "health_check",
    "init",  # GET /reloaded/ping
    "eka_agent_ping",
    "voice_test_client",  # dev-only static page, 404s in prod
}


def _routes():
    return [
        r
        for r in main.app.routes
        if isinstance(r, (APIRoute, APIWebSocketRoute)) and hasattr(r, "endpoint")
    ]


def test_every_endpoint_reports_the_tracked_attributes():
    """Each handler either binds them itself or depends on the auth parser,
    which binds agent_id/wid for it."""
    missing = []
    for route in _routes():
        name = route.endpoint.__name__
        if name in NO_IDENTITY_ENDPOINTS:
            continue
        module = inspect.getmodule(route.endpoint)
        source = inspect.getsource(module)
        binds_directly = "bind_request_context(" in source
        via_auth_dependency = "parse_authenticated_request" in source
        if not (binds_directly or via_auth_dependency):
            missing.append(f"{name} ({module.__name__})")
    assert not missing, (
        "endpoints with no session_id/agent_id/wid in their logs: "
        + ", ".join(sorted(set(missing)))
    )


def test_bind_request_context_skips_absent_values():
    """A guest request has no agent — report nothing rather than a null."""
    with collect_request_attributes() as attributes:
        bind_request_context(session_id="s1", agent_id=None, wid=None)
    # sid is bound alongside session_id automatically — see
    # test_bind_request_context_aliases_session_id_as_sid.
    assert attributes == {"session_id": "s1", "sid": "s1"}


def test_bind_request_context_accumulates_across_calls():
    """The middleware binds session_id, auth adds agent_id/wid later."""
    with collect_request_attributes() as attributes:
        bind_request_context(session_id="s1")
        bind_request_context(agent_id="a1", wid="w1")
    assert attributes == {
        "session_id": "s1",
        "sid": "s1",
        "agent_id": "a1",
        "wid": "w1",
    }


def test_bind_request_context_aliases_session_id_as_sid():
    """Router log lines pass sid= explicitly; third-party (echo) logs never
    will. Binding both under the same contextvar is what makes session_id
    the one join key that works across every log line regardless of who
    wrote it."""
    with collect_request_attributes() as attributes:
        bind_request_context(session_id="s1")
    assert attributes["sid"] == attributes["session_id"] == "s1"

    # A caller that already has its own sid (unusual, but must not crash or
    # be silently overwritten by session_id).
    with collect_request_attributes() as attributes:
        bind_request_context(session_id="s1", sid="explicit")
    assert attributes["sid"] == "explicit"


# --- New Relic ---------------------------------------------------------------
#
# The same three attributes have to reach APM, not just the logs, so a
# transaction can be found by session/agent/workspace. bind_request_context is
# the single place that forwards them, for the same reason it is the single
# place that binds them.


def _forwarded_to_newrelic():
    """Captures what bind_request_context hands to New Relic.

    Patched at the logger, not at the agent: `newrelic` is a prod-only extra
    (pyproject.toml), so it is not installed here and never will be in CI.
    """
    sent = []
    return sent, patch(
        "common.utils.logger.add_custom_attributes_newrelic", sent.extend
    )


def test_newrelic_gets_the_tracked_attributes():
    sent, patched = _forwarded_to_newrelic()
    with patched:
        bind_request_context(
            session_id="s1", agent_id="a1", wid="w1", request_id="r1"
        )
    assert dict(sent) == {
        "session_id": "s1",
        "agent_id": "a1",
        "wid": "w1",
        "request_id": "r1",
    }


def test_newrelic_does_not_get_the_sid_alias():
    """sid duplicates session_id. Harmless in logs, where it is a join key for
    lines written by callers that never say session_id; pure noise against the
    128-attribute-per-transaction cap. This pins the allow-list so a later
    refactor cannot start forwarding everything bind_request_context sees."""
    sent, patched = _forwarded_to_newrelic()
    with patched:
        bind_request_context(session_id="s1", userid="u1", auth_level="user")
    assert dict(sent) == {"session_id": "s1"}


def test_newrelic_is_not_called_when_nothing_tracked_is_bound():
    sent, patched = _forwarded_to_newrelic()
    with patched:
        bind_request_context(userid="u1")
    assert sent == []


def test_newrelic_attributes_accumulate_across_calls():
    """Same staged arrival as the logs: the middleware binds session_id off
    the URL, the auth dependency adds agent_id/wid once the token verifies.
    Both land on the one transaction the request is already inside."""
    sent, patched = _forwarded_to_newrelic()
    with patched:
        bind_request_context(session_id="s1")
        bind_request_context(agent_id="a1", wid="w1")
    assert dict(sent) == {"session_id": "s1", "agent_id": "a1", "wid": "w1"}


def test_newrelic_attributes_reach_a_real_request():
    """End to end through the ASGI stack, which is the only way to prove the
    middleware's binding actually reaches the transaction.

    Unauthenticated, so it 403s before any agent is resolved — session_id and
    request_id are all this request has, and both must be there.
    """
    sid = "11111111-1111-1111-1111-111111111111"
    sent, patched = _forwarded_to_newrelic()
    with patched:
        TestClient(main.app).get(f"/eka-agent/sessions/{sid}")
    stamped = dict(sent)
    assert stamped["session_id"] == sid
    assert stamped["request_id"]
    assert "sid" not in stamped


def test_binding_survives_an_absent_newrelic_agent():
    """The normal case in dev and CI. Telemetry must never break a request."""
    import common.utils.newrelic as nr

    with patch.object(nr, "NEWRELIC_AVAILABLE", False):
        assert nr.add_custom_attributes_newrelic([("session_id", "s1")]) is None
        bind_request_context(session_id="s1", agent_id="a1", wid="w1")


def test_attributes_are_sent_through_the_agents_batch_api():
    """Exercises the call the prod agent actually receives — unreachable
    otherwise, since newrelic is not installed here."""
    from unittest.mock import MagicMock

    import common.utils.newrelic as nr

    agent = MagicMock()
    with patch.object(nr, "NEWRELIC_AVAILABLE", True), patch.object(
        nr, "newrelic", agent
    ):
        nr.add_custom_attributes_newrelic([("wid", "w1")])
    agent.agent.add_custom_attributes.assert_called_once_with([("wid", "w1")])


def test_a_failing_newrelic_agent_does_not_break_the_request():
    from unittest.mock import MagicMock

    import common.utils.newrelic as nr

    agent = MagicMock()
    agent.agent.add_custom_attributes.side_effect = RuntimeError("agent down")
    with patch.object(nr, "NEWRELIC_AVAILABLE", True), patch.object(
        nr, "newrelic", agent
    ):
        nr.add_custom_attributes_newrelic([("wid", "w1")])


def _capture_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    handler.setFormatter(root.handlers[0].formatter)
    previous = root.handlers
    root.handlers = [handler]
    return stream, previous


def _restore(previous):
    logging.getLogger().handlers = previous


def _json_lines(stream):
    out = []
    for line in stream.getvalue().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def test_access_log_carries_full_context_on_failure():
    """What the failure line must carry: the request's identity, its outcome
    and its duration — for a request that never reached a handler."""
    sid = "11111111-1111-1111-1111-111111111111"
    stream, previous = _capture_logs()
    try:
        # Unauthenticated, so it 403s without touching Redis — all this needs
        # is for the request to reach the router and come back.
        TestClient(main.app).get(f"/eka-agent/sessions/{sid}")
    finally:
        _restore(previous)
    access = [r for r in _json_lines(stream) if r.get("event") == "http request"]
    assert len(access) == 1
    entry = access[0]
    assert entry["method"] == "GET"
    assert entry["path"] == f"/eka-agent/sessions/{sid}"
    assert entry["resp_code"] == 403
    assert entry["session_id"] == sid
    assert entry["sid"] == sid
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["request_id"]


@pytest.mark.parametrize(
    "path", ["/", "/reloaded/ping", "/reloaded/health", "/eka-agent/ping"]
)
def test_probes_get_no_access_line(path):
    """Liveness/readiness run every few seconds per pod and say nothing when
    they pass. They are the one thing deliberately not logged."""
    stream, previous = _capture_logs()
    try:
        TestClient(main.app).get(path)
    finally:
        _restore(previous)
    assert not [r for r in _json_lines(stream) if r.get("event") == "http request"]


def test_successful_requests_get_no_access_line():
    """The access line is a third copy on success: every handler logs its own
    outcome with the same session_id/agent_id/wid, and the APM transaction
    carries method/path/status/duration. Only failures earn a line.

    The config lookup is patched because it reaches DynamoDB — unpatched this
    endpoint 500s here and the test would pass for the wrong reason.
    """
    from unittest.mock import AsyncMock, MagicMock

    from med_assist.router import agent_config

    config = MagicMock()
    config.model_dump.return_value = {"agent_id": AGENT_ID, "name": "test"}

    stream, previous = _capture_logs()
    try:
        with patch.object(
            agent_config,
            "get_agent_config_public_with_campaign",
            AsyncMock(return_value=config),
        ):
            response = TestClient(main.app).get(f"/eka-agent/agents/{AGENT_ID}")
    finally:
        _restore(previous)

    assert response.status_code == 200, "the request must actually succeed"
    lines = _json_lines(stream)
    assert not [r for r in lines if r.get("event") == "http request"]
    # The handler's own line is what makes the access line redundant.
    assert [r for r in lines if r.get("event") == "agent config ok"]


def test_failed_requests_still_get_an_access_line():
    """A 403 from the auth dependency never reaches a handler, so nothing else
    records it. Same for 404s and 422s."""
    stream, previous = _capture_logs()
    try:
        TestClient(main.app).post("/eka-agent/nudges", json={"url": "https://x/p"})
    finally:
        _restore(previous)
    access = [r for r in _json_lines(stream) if r.get("event") == "http request"]
    assert len(access) == 1
    assert access[0]["resp_code"] == 403


def test_request_id_is_echoed_and_reused():
    client = TestClient(main.app)
    generated = client.get("/reloaded/ping")
    assert generated.headers["x-request-id"]

    supplied = client.get("/reloaded/ping", headers={"x-request-id": "caller-123"})
    assert supplied.headers["x-request-id"] == "caller-123"


_UUID_A = "11111111-1111-1111-1111-111111111111"
_UUID_B = "22222222-2222-2222-2222-222222222222"
_UUID_C = "33333333-3333-3333-3333-333333333333"
_UUID_D = "44444444-4444-4444-4444-444444444444"


@pytest.mark.parametrize(
    "path,expected",
    [
        (f"/eka-agent/sessions/{_UUID_A}", _UUID_A),
        (f"/reloaded/med-assist/session/{_UUID_B}/chat", _UUID_B),
        (f"/reloaded/ws/med-assist/voice/session/{_UUID_C}/", _UUID_C),
        (f"/eka-agent/sessions/{_UUID_D}/summary", _UUID_D),
    ],
)
def test_session_id_extracted_from_both_url_shapes(path, expected):
    """The /eka-agent namespace mounts on /sessions; the legacy one on
    /session. Both have to yield a session_id."""
    match = main._SESSION_ID_RE.search(path)
    assert match and match.group(1) == expected


def test_session_list_path_has_no_session_id():
    """POST/GET /sessions is the collection, not one session."""
    assert main._SESSION_ID_RE.search("/eka-agent/sessions") is None


def test_non_uuid_path_segment_is_not_bound_as_a_session_id():
    """The uuid-shape guard: a future route under /session(s)/ whose next
    segment isn't a session id (e.g. a literal word) must not be captured."""
    assert main._SESSION_ID_RE.search("/reloaded/auth/session/token-exchange") is None


@pytest.mark.asyncio
async def test_authenticated_request_stamps_agent_id_and_wid():
    from med_assist.service.auth.tokens.access import (
        mint_sess_token,
        parse_authenticated_request,
    )
    from starlette.requests import Request

    # Patched, not read from config: the module-level key is bound at import
    # time and another test module may have imported it under a different
    # MATRIX, which made this pass alone and fail in the full suite.
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    with patch("med_assist.service.auth.tokens.access.AUTH_JWT_KEY", key):
        token = mint_sess_token(
            userid="oid-1", level="user", wid=WID, agent_id=AGENT_ID
        )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/eka-agent/sessions",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    with patch("med_assist.service.auth.tokens.access.AUTH_JWT_KEY", key):
        with collect_request_attributes() as attributes:
            await parse_authenticated_request(Request(scope))
    for attr in ("agent_id", "wid"):
        assert attr in attributes, f"{attr} not bound by the auth dependency"
    assert attributes["agent_id"] == AGENT_ID
    assert attributes["wid"] == WID


@pytest.mark.asyncio
async def test_websocket_reports_all_three_attributes():
    """WebSockets get no access-log line (there's no single request/response
    to summarise), so this is the only place session_id/agent_id/wid show up
    for a socket — the handler's own log lines have to carry them."""
    from unittest.mock import AsyncMock, MagicMock

    from med_assist.models.session import SessionCache
    from med_assist.router import web_socket

    session = SessionCache(
        session_id="s1", wid="w1", agent_id="a1", idle_session_expiry=600
    )
    manager = MagicMock()
    manager.connect = AsyncMock(return_value=(True, {}))
    # Fail auth so the handler returns right after loading the session —
    # by then all three attributes must already be bound.
    manager.authenticate = AsyncMock(return_value=False)
    manager.disconnect = AsyncMock()

    with collect_request_attributes() as attributes:
        with patch.object(
            web_socket, "get_connection_manager", MagicMock(return_value=manager)
        ), patch.object(
            web_socket, "get_session_from_cache", AsyncMock(return_value=session)
        ):
            await web_socket.websocket_endpoint(MagicMock(), "s1")

    assert attributes == {
        "session_id": "s1",
        "sid": "s1",
        "agent_id": "a1",
        "wid": "w1",
    }


@pytest.mark.asyncio
async def test_public_agent_pages_report_agent_and_workspace(monkeypatch):
    """No sess token on these, so the path param is the only identity."""
    import common.config as config
    from med_assist.router import bot

    # get_config() caches MATRIX_CONFIG at module scope on first call, so
    # whichever test imports first wins for the rest of the process — pin it
    # here rather than depending on collection order for CURR_ENV/HOST.
    monkeypatch.setenv("MATRIX", json.dumps({"CURR_ENV": "prod"}))
    monkeypatch.setattr(config, "MATRIX_CONFIG", None)

    agent_id = base64.b64encode(f"uuid#{WID}".encode()).decode()
    for handler in (bot.get_agent_widget, bot.get_agent_iframe):
        # is_sebenza defaults to a FastAPI Query() sentinel that only resolves
        # to a real bool through the framework's dependency injection — a
        # direct call (as here) must supply the plain value itself.
        with collect_request_attributes() as attributes:
            await handler(agent_id=agent_id, name="widget", is_sebenza=False)
        assert attributes == {"agent_id": agent_id, "wid": WID}, handler.__name__


def test_widget_dev_overrides_are_unset():
    """OVERRIDE_HOST/OVERRIDE_SDK_TAG are a local-only escape hatch — a value
    left in them points every environment's widget at one developer's build."""
    from med_assist.router import bot

    assert bot.OVERRIDE_HOST is None
    assert bot.OVERRIDE_SDK_TAG is None


# Handlers whose outcome logs live in a helper the endpoint delegates to.
_OUTCOME_IN_HELPER = {
    "run_prompt_endpoint": "_logged_stream",
    "chat_stream": "generate",
    "vobiz_answer": "_answer_call",
    "vobiz_answer_for_number": "_answer_call",
}

_SUCCESS_MARKERS = (
    " ok",
    "succeeded",
    "served",
    "created",
    "established",
    "ended",
    "starting voice pipeline",
)


def _handler_body(fn):
    """The endpoint's source plus that of the helper it hands off to."""
    module = inspect.getmodule(fn)
    source = inspect.getsource(fn)
    helper = _OUTCOME_IN_HELPER.get(fn.__name__)
    if helper:
        source += inspect.getsource(module).split(f"def {helper}", 1)[-1]
    return source


def test_every_endpoint_logs_a_success_outcome():
    """Not an entry line — an outcome. It is what says the request worked,
    and it carries session_id/agent_id/wid from the bound context."""
    missing = []
    for route in _routes():
        fn = route.endpoint
        if fn.__name__ in NO_IDENTITY_ENDPOINTS:
            continue
        body = _handler_body(fn).lower()
        if not any(m in body for m in _SUCCESS_MARKERS):
            missing.append(fn.__name__)
    assert not missing, "endpoints with no success log: " + ", ".join(sorted(set(missing)))


def test_every_endpoint_logs_why_it_failed():
    """Every handler has at least one warning/error/critical carrying the
    reason, so a failure is diagnosable from the logs alone."""
    missing = []
    for route in _routes():
        fn = route.endpoint
        if fn.__name__ in NO_IDENTITY_ENDPOINTS:
            continue
        body = _handler_body(fn)
        logs_failure = re.search(r"logger\.(warning|error|critical)\(", body)
        reports_reason = "error=" in body
        if not (logs_failure and reports_reason):
            missing.append(fn.__name__)
    assert not missing, (
        "endpoints that do not log a failure reason: "
        + ", ".join(sorted(set(missing)))
    )
