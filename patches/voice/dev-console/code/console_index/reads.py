"""Postgres query layer for the conversations list page.

Replaces the four mutually-exclusive Dynamo query paths with ONE composable
queryset over console_session (+ EXISTS semi-joins to console_event for tool
filters). Every filter combines with every other. Pagination is page-number
offset with a fetch-one-extra probe for has_next — deliberately NO COUNT(*)
or SUM aggregates: they scan the whole filtered set on every page load and
the page doesn't need them.

Scope guard: this serves the LIST page only. The detail drawer (conversation,
context, feedback, annotation) keeps reading Dynamo/MySQL via its existing
endpoints.
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from console_index.models import ConsoleEvent, ConsoleSession

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


def _date_bounds(date_from: str, date_to: str):
    """YYYY-MM-DD strings -> aware UTC datetimes; date_to end-of-day inclusive
    (same semantics as conversations.views._date_range_to_epoch)."""
    lo = hi = None
    if date_from:
        try:
            lo = datetime.fromisoformat(date_from).replace(tzinfo=dt_timezone.utc)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            hi = (datetime.fromisoformat(date_to).replace(tzinfo=dt_timezone.utc)
                  + timedelta(days=1) - timedelta(seconds=1))
        except (ValueError, TypeError):
            pass
    return lo, hi


def _param_q(name: str, raw: str) -> Q:
    """Containment Q for a tool param value. Form values arrive as strings but
    stored params keep JSON types (page_no: 0), so try every plausible
    coercion — any match counts."""
    candidates = [raw]
    try:
        candidates.append(int(raw))
    except (ValueError, TypeError):
        try:
            candidates.append(float(raw))
        except (ValueError, TypeError):
            pass
    if raw.lower() in ("true", "false"):
        candidates.append(raw.lower() == "true")
    q = Q()
    for v in candidates:
        q |= Q(params__contains={name: v})
    return q


def _annotator_session_ids(workspace_id: str, annotator_oid: str) -> list:
    """Session UUIDs annotated by this oid — via MySQL SessionAnnotation.
    (annotator identity isn't stored in PG; has_annotation is just a flag)."""
    from conversations.models import SessionAnnotation

    raw_ids = (
        SessionAnnotation.objects
        .filter(workspace_id=workspace_id, oid=annotator_oid)
        .values_list("session_id", flat=True)
        .distinct()
    )
    ids = []
    for r in raw_ids:
        try:
            ids.append(uuid_mod.UUID(str(r)))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


def fetch_sessions(engine_agent_id: str, workspace_id: str, filters: dict,
                   page: int, page_size: int = PAGE_SIZE) -> dict:
    """One composable query for the list page.

    filters keys (all optional; strings from request.GET, except channels: list):
      date_from, date_to, tool_name, tool_param_name, tool_param_value,
      has_feedback ('1'/'0'), user_feedback ('1'/'0'), annotator_oid,
      channels (list), min_msgs, max_msgs, min_user_msgs, max_user_msgs
    """
    qs = ConsoleSession.objects.filter(agent_id=engine_agent_id, archived=False)

    lo, hi = _date_bounds(filters.get("date_from", ""), filters.get("date_to", ""))
    if lo:
        qs = qs.filter(created_at__gte=lo)
    if hi:
        qs = qs.filter(created_at__lte=hi)

    tool_name = filters.get("tool_name", "")
    param_name = filters.get("tool_param_name", "")
    param_value = filters.get("tool_param_value", "")
    if tool_name or param_name:
        ev = ConsoleEvent.objects.filter(session_id=OuterRef("session_id"))
        if tool_name:
            ev = ev.filter(tool_name=tool_name)
        if param_name:
            ev = ev.filter(params__has_key=param_name)
            if param_value:
                ev = ev.filter(_param_q(param_name, param_value))
        qs = qs.filter(Exists(ev))

    has_feedback = filters.get("has_feedback", "")
    if has_feedback == "1":
        qs = qs.filter(has_annotation=True)
    elif has_feedback == "0":
        qs = qs.filter(has_annotation=False)

    # End-user feedback presence (tri-state; feedback IS NOT NULL == present)
    user_feedback = filters.get("user_feedback", "")
    if user_feedback == "1":
        qs = qs.filter(feedback__isnull=False)
    elif user_feedback == "0":
        qs = qs.filter(feedback__isnull=True)

    annotator_oid = filters.get("annotator_oid", "")
    if annotator_oid:
        qs = qs.filter(session_id__in=_annotator_session_ids(workspace_id, annotator_oid))

    # Multi-select: session matches when it used ANY selected channel.
    channels = filters.get("channels") or []
    if channels:
        qs = qs.filter(channels__overlap=list(channels))

    for key, lookup in (
        ("min_msgs", "msg_count__gte"), ("max_msgs", "msg_count__lte"),
        ("min_user_msgs", "user_msg_count__gte"), ("max_user_msgs", "user_msg_count__lte"),
    ):
        raw = filters.get(key, "")
        if raw:
            try:
                qs = qs.filter(**{lookup: int(raw)})
            except (ValueError, TypeError):
                pass

    qs = qs.order_by("-created_at")

    # Query visibility (SQL + EXPLAIN index plans) is handled globally by
    # core.query_debug.QueryLoggingMiddleware behind settings.QUERY_DEBUG.

    # Fetch one extra row: its presence answers has_next without a COUNT(*).
    try:
        page = max(1, int(page))
    except (ValueError, TypeError):
        page = 1
    offset = (page - 1) * page_size
    rows = list(qs[offset:offset + page_size + 1])
    has_next = len(rows) > page_size

    return {
        "sessions": [_row(s) for s in rows[:page_size]],
        "page": page,
        "has_next": has_next,
        "has_prev": page > 1,
    }


def list_calls(agent_id: str, integration_uuid: str, page=1, page_size: int = PAGE_SIZE) -> dict:
    """One registered phone number's calls, newest first.

    Phone calls are sessions whose context carries the number's integration
    uuid (matrix saves it when it answers). The query leads with agent_id so it
    stays on cs_agent_created_idx; the uuid is then matched inside that agent's
    sessions. Calls answered while the number pointed at a different agent are
    not found. Same fetch-one-extra paging as the conversations list.
    """
    qs = ConsoleSession.objects.filter(
        agent_id=agent_id,
        archived=False,
        context_promoted__integration_uuid=str(integration_uuid),
    ).order_by("-created_at")

    try:
        page = max(1, int(page))
    except (ValueError, TypeError):
        page = 1
    offset = (page - 1) * page_size
    rows = list(qs[offset:offset + page_size + 1])
    return {
        "calls": rows[:page_size],
        "page": page,
        "has_next": len(rows) > page_size,
        "has_prev": page > 1,
    }


def _row(s: ConsoleSession) -> dict:
    """Shape one session to the _sessions_table.html contract. Keys like
    has_feedback are pre-set so the legacy _attach_* helpers no-op."""
    from conversations.views import _humanize_date

    iso = s.created_at.isoformat() if s.created_at else ""
    ctx = s.context_promoted or {}
    return {
        "session_id": str(s.session_id),
        "date": _humanize_date(iso),
        "date_iso": iso,
        "initial_context": ctx,
        "initial_context_json": json.dumps(ctx),
        "has_context": bool(ctx),
        "has_feedback": s.has_annotation,
        "has_user_feedback": s.feedback is not None,
        # Strings on purpose: the generic table cell pipes values through
        # format_value, which suffixes numeric *count* fields with " calls"
        # (wanted on usage tables, not here). Strings pass through bare.
        "msg_count": str(s.msg_count),
        "tool_call_count": str(s.tool_call_count),
        "channels": ", ".join(s.channels or []),
    }
