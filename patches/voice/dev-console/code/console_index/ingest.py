"""Projection: Dynamo stream records -> console_session / console_event.

Single code path for three callers: the Lambda-fed ingest endpoint (live),
the backfill command (Step 4), and the message-before-session /staleness
self-heal (reingest_session). Dynamo is the only source of truth; everything
here is a disposable projection and every write is idempotent:

  - session facets: SETs from the record's full image (replay-safe by nature);
  - counters: advanced only when the (session_id, msg_id) existence probe on
    console_event says this message was never applied (streams are
    at-least-once AND out-of-order across items — verified live);
  - re-ingest: recompute-from-Dynamo, delete-then-insert in one transaction.

Error contract (decided 26 Aug, no dead-letter table):
  - permanently bad records -> one ERROR event `console_index_ingest_skip`
    carrying the record's IDENTITY only (table, event_name, sequence_number,
    session_id, msg_id) — never new_image/old_image, which hold the patient
    conversation. Those identify the record well enough to fetch it from
    Dynamo. Then skipped, never retried (a parse error can't be fixed by
    retrying).

    !! The CloudWatch metric filter that alarms on this used to match the
    literal prefix `console_index_ingest_skip` in a plain-text line. Logs are
    JSON now, so the token is the `event` field: the filter pattern must be
    `{ $.event = "console_index_ingest_skip" }`. It lives outside this repo;
    update it when this deploys or the alarm goes silently dead.
  - transient failures (DB down, ...) -> record index returned in
    failed_indices -> Lambda retries -> SQS DLQ after max attempts.
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from console_index.models import ConsoleEvent, ConsoleSession
from core.logging import bind_log_context, get_logger, scoped_log_context
from core.region import UnknownRegion, activate, deactivate, pg_alias, region_for_aws

logger = get_logger(__name__)

SESSION_TABLE_HINT = "session-flow"  # flow table name contains this; session table doesn't

# In-process cache for agent_id -> wid (AgentConfig rarely changes; entries
# are only used to fill wid on old Dynamo rows that lack it).
_AGENT_WID_CACHE: dict = {}

# Month for which console_event partitions are known to exist, per regional
# Postgres alias (per process).
# Self-healing replacement for a scheduled partition job: every write path
# calls _ensure_event_partitions() first — it does real DDL once per pod per
# month and is a dict-check otherwise, so a missing partition can never fail
# an insert (the classic Oct-1 outage). Partition DROPs (retention) still
# belong to the console_index_maintenance command.
_PARTITIONS_READY_FOR_MONTH: dict = {}


def _ensure_event_partitions() -> None:
    from datetime import date

    from django.db import connections

    from console_index import partitions

    alias = pg_alias()
    month = date.today().replace(day=1)
    if _PARTITIONS_READY_FOR_MONTH.get(alias) == month:
        return
    connection = connections[alias]
    for sql in partitions.ensure_current_and_next_sql():
        try:
            with connection.cursor() as cur:
                cur.execute(sql)
        except Exception as e:
            # Two pods racing CREATE TABLE can still collide in a narrow
            # window despite IF NOT EXISTS — the loser's error is harmless.
            if "already exists" not in str(e):
                raise
    _PARTITIONS_READY_FOR_MONTH[alias] = month


class PermanentRecordError(ValueError):
    """Record can never be applied (shape/parse) — log + skip, don't retry."""


# ---------------------------------------------------------------------------
# Dynamo-typed JSON -> plain python
# ---------------------------------------------------------------------------

def _deserialize_image(image: dict) -> dict:
    """Deserialize a raw Dynamo-typed image ({"k": {"S": "v"}, ...})."""
    from boto3.dynamodb.types import TypeDeserializer

    if not isinstance(image, dict):
        raise PermanentRecordError(f"image is not a dict: {type(image).__name__}")
    de = TypeDeserializer()
    try:
        return {k: _plain(de.deserialize(v)) for k, v in image.items()}
    except Exception as e:
        raise PermanentRecordError(f"undeserializable image: {e}") from e


def _plain(value):
    """Decimal -> int/float recursively (TypeDeserializer yields Decimals)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _epoch_to_dt(epoch) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=dt_timezone.utc)


def _session_uuid(raw) -> uuid_mod.UUID:
    try:
        return uuid_mod.UUID(str(raw))
    except (ValueError, AttributeError, TypeError) as e:
        raise PermanentRecordError(f"non-uuid session_id {raw!r}") from e


# ---------------------------------------------------------------------------
# Entry point: one Lambda POST / one backfill batch
# ---------------------------------------------------------------------------

def _record_identity(record) -> dict:
    """The payload-free fields that identify a stream record.

    Everything here comes from the Lambda's ``_wrap`` (see
    infra/lambda/console_index_forwarder/lambda_function.py). Deliberately
    excludes new_image/old_image: those carry the full message content, which
    is both PHI and the reason a single skipped record used to write 8KB to
    New Relic. ``keys`` is the small one — just session_id, plus msg_id on the
    flow table — and it is enough to pull the real record from Dynamo.
    """
    if not isinstance(record, dict):
        return {"record_type": type(record).__name__}
    keys = record.get("keys") or {}

    def _key(name):
        # Dynamo-typed JSON: {"session_id": {"S": "..."}}
        v = keys.get(name)
        return v.get("S") if isinstance(v, dict) else v

    return {
        "table": record.get("table"),
        "event_name": record.get("event_name"),
        "sequence_number": record.get("sequence_number"),
        "session_id": _key("session_id"),
        "msg_id": _key("msg_id"),
        "approx_ts": record.get("approx_ts"),
    }


def apply_records(records: list, dry_run: bool) -> list[int]:
    """Apply a batch of wrapped stream records; return transient-failure indices."""
    failed = []
    for i, record in enumerate(records):
        # Scoped, not bind+clear: one batch spans many sessions, so each
        # record's ids must not leak onto the next — but the request context
        # the ingest view bound around the whole batch has to survive.
        with scoped_log_context(**_record_identity(record)):
            try:
                _apply_one(record, dry_run=dry_run)
            except UnknownRegion:
                # The Lambda's region isn't configured here (yet). Retrying
                # is right: a permanent skip would silently drop the data
                # until someone noticed and backfilled.
                logger.exception("console_index_ingest_transient", index=i)
                failed.append(i)
            except PermanentRecordError as e:
                # NOTE: "console_index_ingest_skip" is matched verbatim by a
                # CloudWatch metric filter (see the module docstring). As a
                # structlog event it is now the `event` field rather than a
                # message prefix — the filter pattern must be updated to match.
                logger.error("console_index_ingest_skip", reason=str(e))
            except Exception:
                logger.exception("console_index_ingest_transient", index=i)
                failed.append(i)
    return failed


def _apply_one(record: dict, dry_run: bool) -> None:
    if not isinstance(record, dict):
        raise PermanentRecordError("record is not an object")
    event_name = record.get("event_name")
    table = record.get("table") or ""

    if event_name == "REMOVE":
        # Dynamo-side deletes (TTL/cleanup) never touch the read model —
        # PG retention is independent.
        logger.debug("console_index_ignoring_remove", table=table)
        return
    if event_name not in ("INSERT", "MODIFY"):
        raise PermanentRecordError(f"unknown event_name {event_name!r}")

    image = record.get("new_image")
    if image is None:
        raise PermanentRecordError(f"{event_name} record without new_image")
    data = _deserialize_image(image)

    # The stream's AWS region says which regional database the row belongs
    # in (the Lambda reads it off the stream ARN). Records from a Lambda
    # build that doesn't send it are home's.
    token = activate(region_for_aws(record.get("aws_region")))
    try:
        _apply_image(event_name, table, data, dry_run)
    finally:
        deactivate(token)


def _apply_image(event_name: str, table: str, data: dict, dry_run: bool) -> None:
    if SESSION_TABLE_HINT in table:
        if event_name == "MODIFY":
            # Flow rows are write-once in matrix (create_item/create_items
            # only). If this ever fires, that assumption broke — make it loud.
            # session_id/msg_id/sequence_number are already bound by
            # apply_records, so the record is identifiable without dumping it.
            logger.error(
                "console_index_ingest_skip",
                reason="flow-MODIFY-write-once-violated",
            )
            return
        _apply_flow_event(data, dry_run=dry_run)
    else:
        _upsert_session_facets(data, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Session-table records
# ---------------------------------------------------------------------------

def _wid_for_agent(agent_id: str):
    """agent_id -> workspace_id via AgentConfig; None on miss. Cached."""
    if not agent_id:
        return None
    if agent_id in _AGENT_WID_CACHE:
        return _AGENT_WID_CACHE[agent_id]
    from agents.models import AgentConfig

    wid = (
        AgentConfig.objects.filter(agent_id=agent_id)
        .values_list("workspace_id", flat=True)
        .first()
    )
    if wid:
        _AGENT_WID_CACHE[agent_id] = wid
    return wid


# Keys promoted whatever CONTEXT_KEYS says. Phone calls (matrix voice) record how
# the call went under "call" and which registered number answered under
# "integration_uuid"; the number's Calls page reads both from context_promoted.
ALWAYS_PROMOTED = ("call", "integration_uuid")


def _parse_context(raw) -> dict:
    """initial_context arrives as a JSON *string* (verified fixture). Filter
    to the whitelist — predicates, not payloads."""
    keys = {*(settings.CONSOLE_INDEX.get("CONTEXT_KEYS") or []), *ALWAYS_PROMOTED}
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in keys and v is not None}


def _feedback_blob(data: dict):
    """{"nps_base5": ..., "values": [...]} when any end-user feedback exists,
    else None (presence filter = feedback IS NOT NULL)."""
    feedbacks = data.get("feedbacks") or []
    nps = data.get("nps_base5")
    if not feedbacks and nps is None:
        return None
    return {
        "nps_base5": int(nps) if nps is not None else None,
        "values": list(feedbacks),
    }


def session_facets_from_image(data: dict) -> dict | None:
    """Facet dict for update_or_create defaults, or None when the session
    must be skipped (explicitly not initiated). Never contains counters."""
    if data.get("conversation_initiated") is False:
        return None
    agent_id = data.get("agent_id") or ""
    facets = {
        "agent_id": agent_id,
        "wid": data.get("wid") or _wid_for_agent(agent_id),
        "authenticated": bool(data.get("authenticated_user")),
        # Guests carry a userid too (verified fixture) — store only for
        # authenticated users so the partial index stays guest-free.
        "userid": data.get("userid") if data.get("authenticated_user") else None,
        "created_at": _epoch_to_dt(data["c_ate"]) if data.get("c_ate") else timezone.now(),
        "tz": data.get("tz"),
        "context_promoted": _parse_context(data.get("initial_context")),
        "last_ingested_at": timezone.now(),
        # Archived rows stay projected (counters keep flowing) but hidden from lists.
        "archived": bool(data.get("archived")),
    }
    fb = _feedback_blob(data)
    if fb is not None:
        facets["feedback"] = fb
    # Web sessions have no channel attribute (verified fixture) -> "web".
    facets["_channel"] = data.get("channel") or "web"
    return facets


def _upsert_session_facets(data: dict, dry_run: bool) -> None:
    sid = _session_uuid(data.get("session_id"))
    facets = session_facets_from_image(data)
    if facets is None:
        logger.debug("console_index_session_not_initiated", session_id=sid)
        return
    channel = facets.pop("_channel")
    if dry_run:
        logger.info(
            "console_index_dry_run_session_upsert",
            session_id=sid, channel=channel, facet_keys=sorted(facets),
        )
        return
    obj, created = ConsoleSession.objects.update_or_create(session_id=sid, defaults=facets)
    if channel not in (obj.channels or []):
        # Append-only channel rollup; sessions can hop channels.
        obj.channels = list(obj.channels or []) + [channel]
        obj.save(update_fields=["channels"])


# ---------------------------------------------------------------------------
# Flow-table records
# ---------------------------------------------------------------------------

def _parse_tool_input(raw):
    """tool_input occurs as BOTH a JSON string and a map (verified fixture)."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_raw": raw}
    if isinstance(raw, dict):
        return raw
    return {"_raw": str(raw)}


def event_rows_from_message(sid, data: dict, ingested_at) -> tuple[list, int]:
    """(ConsoleEvent list, tool_call_count) for one flow message.

    One row per tool_call/tool_result content item; a message with no tool
    items gets exactly one plain row (tool_id='') — every message has >=1 row,
    which is what makes the PK-prefix probe the counter dedupe.
    tool_call_count counts type=tool_call ONLY (results would double-count).
    """
    msg_id = data.get("msg_id")
    if not msg_id:
        raise PermanentRecordError("flow record without msg_id")
    role = data.get("role") or "user"
    created_at = _epoch_to_dt(data["c_ate"]) if data.get("c_ate") else timezone.now()
    # matrix now stamps channel on flow records (per-message — sessions can
    # hop channels); older records lack it -> NULL.
    channel = data.get("channel")

    rows, tool_calls = [], 0
    for item in data.get("content") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "tool_call":
            tool_calls += 1
            rows.append(ConsoleEvent(
                session_id=sid, msg_id=msg_id, tool_id=item.get("tool_id") or "",
                role=role, tool_name=item.get("tool_name"),
                params=_parse_tool_input(item.get("tool_input")),
                channel=channel, created_at=created_at, ingested_at=ingested_at,
            ))
        elif itype == "tool_result":
            # role='tool' messages: tool_id present, NO tool_name (verified
            # fixture). Result payloads stay in Dynamo — predicates only.
            rows.append(ConsoleEvent(
                session_id=sid, msg_id=msg_id, tool_id=item.get("tool_id") or "",
                role=role, tool_name=None, params=None,
                channel=channel, created_at=created_at, ingested_at=ingested_at,
            ))
    if not rows:
        rows.append(ConsoleEvent(
            session_id=sid, msg_id=msg_id, tool_id="", role=role,
            tool_name=None, params=None,
            channel=channel, created_at=created_at, ingested_at=ingested_at,
        ))
    return rows, tool_calls


def _apply_flow_event(data: dict, dry_run: bool) -> None:
    sid = _session_uuid(data.get("session_id"))
    msg_id = data.get("msg_id")
    if not msg_id:
        raise PermanentRecordError("flow record without msg_id")

    session = ConsoleSession.objects.filter(session_id=sid).first()
    reingest_window = timedelta(days=settings.CONSOLE_INDEX["REINGEST_DAYS"])
    msg_time = _epoch_to_dt(data["c_ate"]) if data.get("c_ate") else timezone.now()

    # Self-heal paths: message-before-session (streams don't order across
    # items/tables) or a session gone stale past the re-ingest window.
    if session is None:
        logger.info("console_index_flow_before_session", session_id=sid, action="full-reingest")
        reingest_session(str(sid), dry_run=dry_run)
        return
    if session.last_ingested_at and msg_time - session.last_ingested_at > reingest_window:
        logger.info("console_index_stale_session", session_id=sid, action="full-reingest")
        reingest_session(str(sid), dry_run=dry_run)
        return

    # Replay dedupe: every applied message has >=1 event row.
    if ConsoleEvent.objects.filter(session_id=sid, msg_id=msg_id).exists():
        logger.debug("console_index_replay_skip", session_id=sid, msg_id=msg_id)
        return

    now = timezone.now()
    rows, tool_calls = event_rows_from_message(sid, data, ingested_at=now)
    usage = data.get("usage") or {}

    if dry_run:
        logger.info(
            "console_index_dry_run_event_insert",
            rows=len(rows), session_id=sid, msg_id=msg_id,
            role=data.get("role"), tool_calls=tool_calls,
            in_t=usage.get("in_t"), op_t=usage.get("op_t"),
        )
        return

    _ensure_event_partitions()
    with transaction.atomic(using=pg_alias()):
        ConsoleEvent.objects.bulk_create(rows)
        updates = {
            "msg_count": F("msg_count") + 1,
            "tool_call_count": F("tool_call_count") + tool_calls,
            "last_ingested_at": now,
        }
        if data.get("role") == "user":
            updates["user_msg_count"] = F("user_msg_count") + 1
        if usage.get("in_t"):
            updates["tokens_in"] = F("tokens_in") + int(usage["in_t"])
        if usage.get("op_t"):
            updates["tokens_out"] = F("tokens_out") + int(usage["op_t"])
        # Per-message channel reaches the session rollup too (sessions hop
        # channels; e.g. a whatsapp message in a web-started session).
        # Read-modify-write is safe: records for a session are serial per shard.
        msg_channel = data.get("channel")
        if msg_channel and msg_channel not in (session.channels or []):
            updates["channels"] = list(session.channels or []) + [msg_channel]
        ConsoleSession.objects.filter(session_id=sid).update(**updates)


# ---------------------------------------------------------------------------
# Full re-ingest — self-heal + backfill engine
# ---------------------------------------------------------------------------

def reingest_session(session_id: str, dry_run: bool = False) -> bool:
    """Rebuild one session from Dynamo, from scratch. Idempotent: session
    facets+counters are SET (never incremented) and events are
    delete-then-insert in one transaction. Returns True when projected."""
    from conversations.dynamo_models import SessionModel, query_session_flow

    sid = _session_uuid(session_id)
    # Bound here rather than by the caller: reingest_session runs from the
    # self-heal paths, from the ingest batch, and from backfill's
    # ThreadPoolExecutor — and a thread-pool worker inherits NO contextvars,
    # so the submitting loop cannot bind this on its behalf.
    bind_log_context(session_id=str(sid))
    try:
        item = SessionModel.get(str(sid))
    except SessionModel.DoesNotExist:
        logger.warning("console_index_reingest_not_in_dynamo", session_id=sid)
        return False

    data = {
        "session_id": item.session_id,
        "agent_id": item.agent_id,
        "wid": item.wid,
        "authenticated_user": item.authenticated_user,
        "userid": item.userid,
        "c_ate": item.c_ate,
        "tz": item.tz,
        "initial_context": item.initial_context,
        "conversation_initiated": item.conversation_initiated,
        "feedbacks": list(item.feedbacks or []),
        "nps_base5": item.nps_base5,
        "channel": getattr(item, "channel", None),
        "archived": item.archived,
    }
    facets = session_facets_from_image(data)
    if facets is None:
        if not dry_run:
            # Not a real conversation — drop any stale projection of it.
            ConsoleSession.objects.filter(session_id=sid).delete()
        logger.info("console_index_reingest_not_initiated", session_id=sid)
        return False
    channel = facets.pop("_channel")

    plain_msgs = [_plain(m) for m in query_session_flow(str(sid))]
    now = timezone.now()
    all_rows, tool_calls, user_msgs, tokens_in, tokens_out = [], 0, 0, 0, 0
    for msg in plain_msgs:
        try:
            rows, calls = event_rows_from_message(sid, msg, ingested_at=now)
        except PermanentRecordError as e:
            # `msg` here is a whole Dynamo message — an assistant turn with
            # tool results can be tens of KB of patient conversation. Its
            # shape is enough to diagnose a parse failure; its content is not
            # needed and must not be shipped.
            logger.error(
                "console_index_ingest_skip",
                reason=str(e),
                msg_id=msg.get("msg_id"),
                role=msg.get("role"),
                content_parts=len(msg.get("content") or []),
            )
            continue
        all_rows.extend(rows)
        tool_calls += calls
        if msg.get("role") == "user":
            user_msgs += 1
        usage = msg.get("usage") or {}
        tokens_in += int(usage.get("in_t") or 0)
        tokens_out += int(usage.get("op_t") or 0)

    # Messages counted = distinct msg_ids that produced rows.
    msg_count = len({r.msg_id for r in all_rows})

    if dry_run:
        logger.info(
            "console_index_dry_run_session_rebuild",
            session_id=sid, msgs=msg_count, event_rows=len(all_rows),
            tool_calls=tool_calls, tokens_in=tokens_in, tokens_out=tokens_out,
            channel=channel,
        )
        return True

    _ensure_event_partitions()
    with transaction.atomic(using=pg_alias()):
        obj, _ = ConsoleSession.objects.update_or_create(
            session_id=sid,
            defaults={
                **facets,
                "msg_count": msg_count,
                "user_msg_count": user_msgs,
                "tool_call_count": tool_calls,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "last_ingested_at": now,
            },
        )
        # Channels rollup = session-image channel ∪ distinct flow channels
        # (per-message channel exists on newer flow records).
        rollup = [channel] + sorted(
            {r.channel for r in all_rows if r.channel and r.channel != channel}
        )
        if obj.channels != rollup:
            obj.channels = rollup
            obj.save(update_fields=["channels"])
        # Delete-then-insert: ingested_at is in the PK, so ON CONFLICT can
        # never dedupe re-ingested rows — this is what keeps rebuilds
        # duplicate-free.
        ConsoleEvent.objects.filter(session_id=sid).delete()
        ConsoleEvent.objects.bulk_create(all_rows)
    logger.info("console_index_reingested", session_id=sid, msgs=msg_count, rows=len(all_rows))
    return True
