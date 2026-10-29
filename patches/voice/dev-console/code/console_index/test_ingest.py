"""Ingest tests — driven by real captured stream records (tests_data/).

The fixture batch encodes the nasty production facts: out-of-order msg_ids,
tool_input as a JSON string, tool_result with no tool_name, optional usage.
Requires local agents_pg (docker-compose.dev.yml), like tests.py.
"""

import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db import connections
from django.test import Client, SimpleTestCase, TestCase, override_settings

from console_index import ingest
from console_index.models import ConsoleEvent, ConsoleSession

FIXTURES = json.loads(
    (Path(__file__).parent / "tests_data" / "stream_records.json").read_text()
)["records"]

SESSION_REC = FIXTURES[0]
FLOW_RECS = FIXTURES[1:]  # captured order: -0, -2, -1 (out of msg_id order)
SID = uuid.UUID("44862c36-8a0a-4fd2-8cd0-011c3b62d18c")

INGEST_URL = "/console-index/ingest/"

LIVE_SETTINGS = {"DRY_RUN": False, "CONTEXT_KEYS": [], "REINGEST_DAYS": 15}


def _post(client, records):
    return client.post(
        INGEST_URL, data=json.dumps({"records": records}),
        content_type="application/json",
    )


@override_settings(CONSOLE_INDEX=LIVE_SETTINGS)
class IngestHappyPathTests(TestCase):
    databases = {"default", "agents_pg"}

    def setUp(self):
        self.client = Client()

    def _assert_projection(self):
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.agent_id, SESSION_REC["new_image"]["agent_id"]["S"])
        self.assertEqual(s.wid, "77088166996724")
        self.assertFalse(s.authenticated)
        self.assertIsNone(s.userid)          # guest: userid in image but not stored
        self.assertEqual(s.channels, ["web"])  # web session has no channel attr
        self.assertIsNone(s.feedback)
        self.assertFalse(s.archived)
        self.assertEqual(s.msg_count, 3)
        self.assertEqual(s.user_msg_count, 0)
        self.assertEqual(s.tool_call_count, 1)   # tool_result must not count
        self.assertEqual(s.tokens_in, 6 + 149)
        self.assertEqual(s.tokens_out, 90 + 136)

        rows = list(ConsoleEvent.objects.filter(session_id=SID).order_by("msg_id"))
        self.assertEqual(len(rows), 3)
        by_msg = {r.msg_id: r for r in rows}
        call = by_msg["1787687696159-0"]
        self.assertEqual(call.tool_name, "mcp_server_123__list_patients")
        self.assertEqual(call.params, {"page_no": 0, "page_size": 500})  # string tool_input parsed
        result = by_msg["1787687696159-1"]
        self.assertEqual(result.role, "tool")
        self.assertIsNone(result.tool_name)   # tool_result rows carry no tool_name
        self.assertEqual(result.tool_id, call.tool_id)
        plain = by_msg["1787687696159-2"]
        self.assertEqual(plain.tool_id, "")

    def test_happy_path_out_of_order_batch(self):
        resp = _post(self.client, FIXTURES)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"failed_indices": [], "dry_run": False})
        self._assert_projection()

    def test_replay_is_idempotent(self):
        _post(self.client, FIXTURES)
        resp = _post(self.client, FIXTURES)   # full replay, at-least-once delivery
        self.assertEqual(resp.status_code, 200)
        self._assert_projection()             # identical counts, no duplicates

    def test_tool_input_as_map_variant(self):
        rec = copy.deepcopy(FLOW_RECS[0])
        rec["new_image"]["content"]["L"][1]["M"]["tool_input"] = {
            "M": {"page_no": {"N": "0"}, "page_size": {"N": "500"}}
        }
        _post(self.client, [SESSION_REC, rec])
        row = ConsoleEvent.objects.get(session_id=SID, msg_id="1787687696159-0")
        self.assertEqual(row.params, {"page_no": 0, "page_size": 500})

    def test_session_modify_sets_feedback_without_touching_counters(self):
        _post(self.client, FIXTURES)
        rec = copy.deepcopy(SESSION_REC)
        rec["event_name"] = "MODIFY"
        rec["new_image"]["feedbacks"] = {"L": [{"S": "helpful"}]}
        rec["new_image"]["nps_base5"] = {"N": "4"}
        _post(self.client, [rec])
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.feedback, {"nps_base5": 4, "values": ["helpful"]})
        self.assertEqual(s.msg_count, 3)      # facet update never touches counters

    def test_archived_session_modify_flags_the_row_and_keeps_counters(self):
        _post(self.client, FIXTURES)
        rec = copy.deepcopy(SESSION_REC)
        rec["event_name"] = "MODIFY"
        rec["new_image"]["archived"] = {"BOOL": True}
        _post(self.client, [rec])
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertTrue(s.archived)
        self.assertEqual(s.msg_count, 3)

    def test_not_initiated_remove_and_flow_modify_are_skipped(self):
        rec = copy.deepcopy(SESSION_REC)
        rec["new_image"]["conversation_initiated"] = {"BOOL": False}
        _post(self.client, [rec])
        self.assertFalse(ConsoleSession.objects.filter(session_id=SID).exists())

        remove = {"table": "med-assist-session", "event_name": "REMOVE",
                  "keys": SESSION_REC["keys"], "new_image": None, "old_image": None}
        flow_modify = copy.deepcopy(FLOW_RECS[0])
        flow_modify["event_name"] = "MODIFY"
        resp = _post(self.client, [remove, flow_modify])
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertEqual(ConsoleEvent.objects.count(), 0)

    def test_garbage_records_logged_and_skipped_not_failed(self):
        garbage = [
            {"table": "med-assist-session-flow", "event_name": "INSERT",
             "new_image": {"role": {"S": "user"}}},                    # no session_id
            {"table": "med-assist-session", "event_name": "INSERT",
             "new_image": {"session_id": {"S": "not-a-uuid"}}},        # bad uuid
            "not-even-an-object",
        ]
        with self.assertLogs("console_index.ingest", level="ERROR") as logs:
            resp = _post(self.client, garbage + [SESSION_REC])
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertEqual(sum("console_index_ingest_skip" in l for l in logs.output), 3)
        # rest of the batch still processed
        self.assertTrue(ConsoleSession.objects.filter(session_id=SID).exists())

    def test_flow_channel_reaches_event_row_and_session_rollup(self):
        """matrix now stamps channel on flow records — event rows carry it and
        the session channels rollup picks it up (sessions hop channels)."""
        rec = copy.deepcopy(FLOW_RECS[1])  # plain assistant message
        rec["new_image"]["channel"] = {"S": "whatsapp"}
        _post(self.client, [SESSION_REC, rec])
        row = ConsoleEvent.objects.get(session_id=SID, msg_id=rec["keys"]["msg_id"]["S"])
        self.assertEqual(row.channel, "whatsapp")
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.channels, ["web", "whatsapp"])
        # replay: no duplicate channel entry
        _post(self.client, [rec])
        s.refresh_from_db()
        self.assertEqual(s.channels, ["web", "whatsapp"])

    def test_missing_partition_self_heals(self):
        """Write paths ensure current+next partitions before inserting — a
        dropped/never-created partition can never fail an insert (the Oct-1
        failure mode). Simulates a month rollover nobody prepared for."""
        import console_index.ingest as ingest_mod
        from datetime import date
        from console_index import partitions as p

        conn = connections["agents_pg"]
        current = date.today().replace(day=1)
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {p.partition_name(current)}")
        ingest_mod._PARTITIONS_READY_FOR_MONTH.clear()  # fresh-pod state

        resp = _post(self.client, FIXTURES)
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertIn(p.partition_name(current), p.list_partitions(conn))
        self.assertEqual(ConsoleEvent.objects.filter(session_id=SID).count(), 3)

    def test_http_contract(self):
        self.assertEqual(self.client.get(INGEST_URL).status_code, 405)
        bad = self.client.post(INGEST_URL, data="{", content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        notlist = self.client.post(INGEST_URL, data=json.dumps({"records": "x"}),
                                   content_type="application/json")
        self.assertEqual(notlist.status_code, 400)
        # No jwt-payload header anywhere above: middleware exemption proven by
        # the fact that none of these were 401s.


@override_settings(CONSOLE_INDEX=LIVE_SETTINGS)
class ReingestTests(TestCase):
    databases = {"default", "agents_pg"}

    def setUp(self):
        self.client = Client()

    def _dynamo_mocks(self):
        item = SimpleNamespace(
            session_id=str(SID),
            agent_id=SESSION_REC["new_image"]["agent_id"]["S"],
            wid="77088166996724",
            authenticated_user=False,
            userid="ed8380a1-92d6-4c86-ab1c-b90d6bfb8f9a",
            c_ate=1787687413,
            tz="Asia/Calcutta",
            initial_context="{}",
            conversation_initiated=True,
            feedbacks=None,
            nps_base5=None,
            archived=None,
        )
        flow = [
            {"msg_id": "1787687696159-0", "role": "assistant", "c_ate": 1787687700,
             "usage": {"in_t": 6, "op_t": 90},
             "content": [{"type": "text", "text": "hi"},
                         {"type": "tool_call", "tool_id": "t1",
                          "tool_name": "selfcare_triage",
                          "tool_input": '{"pathway": "Home care"}'}]},
            {"msg_id": "1787687696159-1", "role": "tool", "c_ate": 1787687700,
             "channel": "whatsapp",
             "content": [{"type": "tool_result", "tool_id": "t1", "result": "{}"}]},
        ]
        return item, flow

    def test_flow_before_session_triggers_full_reingest(self):
        item, flow = self._dynamo_mocks()
        with patch("conversations.dynamo_models.SessionModel") as sm, \
             patch("conversations.dynamo_models.query_session_flow", return_value=flow):
            sm.DoesNotExist = type("DoesNotExist", (Exception,), {})
            sm.get.return_value = item
            # Only a flow record — session row doesn't exist yet.
            resp = _post(self.client, [FLOW_RECS[0]])
        self.assertEqual(resp.json()["failed_indices"], [])
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.msg_count, 2)          # rebuilt from mocked Dynamo flow
        self.assertEqual(s.tool_call_count, 1)
        self.assertEqual(s.tokens_in, 6)
        # re-ingest rollup: session channel ("web") + distinct flow channels
        self.assertEqual(s.channels, ["web", "whatsapp"])
        self.assertEqual(ConsoleEvent.objects.filter(session_id=SID).count(), 2)

        # The live record that triggered the rebuild now replays: its msg_id is
        # already projected -> probe skips it, counters unchanged.
        resp = _post(self.client, [FLOW_RECS[0]])
        self.assertEqual(resp.json()["failed_indices"], [])
        s.refresh_from_db()
        self.assertEqual(s.msg_count, 2)

    def test_flow_after_archive_rebuilds_the_session_archived(self):
        item, flow = self._dynamo_mocks()
        item.archived = True
        with patch("conversations.dynamo_models.SessionModel") as sm, \
             patch("conversations.dynamo_models.query_session_flow", return_value=flow):
            sm.DoesNotExist = type("DoesNotExist", (Exception,), {})
            sm.get.return_value = item
            resp = _post(self.client, [FLOW_RECS[0]])
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertTrue(ConsoleSession.objects.get(session_id=SID).archived)

    def test_session_missing_in_dynamo_is_skipped(self):
        with patch("conversations.dynamo_models.SessionModel") as sm:
            sm.DoesNotExist = type("DoesNotExist", (Exception,), {})
            sm.get.side_effect = sm.DoesNotExist()
            resp = _post(self.client, [FLOW_RECS[0]])
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertFalse(ConsoleSession.objects.filter(session_id=SID).exists())


@override_settings(CONSOLE_INDEX={"DRY_RUN": True, "CONTEXT_KEYS": [], "REINGEST_DAYS": 15})
class DryRunTests(TestCase):
    databases = {"default", "agents_pg"}

    def test_dry_run_writes_nothing_but_logs_intent(self):
        # Dry run allows reads: with an empty DB the flow records take the
        # re-ingest path, which fetches from Dynamo — mock it (in staging
        # this is exactly the rehearsal we want; in tests, no network).
        item = SimpleNamespace(
            session_id=str(SID), agent_id="a", wid="w", authenticated_user=False,
            userid=None, c_ate=1787687413, tz=None, initial_context="{}",
            conversation_initiated=True, feedbacks=None, nps_base5=None, archived=None,
        )
        with patch("conversations.dynamo_models.SessionModel") as sm, \
             patch("conversations.dynamo_models.query_session_flow", return_value=[]):
            sm.DoesNotExist = type("DoesNotExist", (Exception,), {})
            sm.get.return_value = item
            with self.assertLogs("console_index.ingest", level="INFO") as logs:
                resp = Client().post(
                    INGEST_URL, data=json.dumps({"records": FIXTURES}),
                    content_type="application/json",
                )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["dry_run"])
        self.assertEqual(resp.json()["failed_indices"], [])
        self.assertEqual(ConsoleSession.objects.count(), 0)
        self.assertEqual(ConsoleEvent.objects.count(), 0)
        self.assertTrue(any("would upsert session" in l for l in logs.output))
        self.assertTrue(any("would rebuild session" in l for l in logs.output))


@override_settings(CONSOLE_INDEX={"DRY_RUN": False, "CONTEXT_KEYS": ["source"], "REINGEST_DAYS": 15})
class ContextWhitelistTests(TestCase):
    databases = {"default", "agents_pg"}

    def test_whitelist_projection(self):
        rec = copy.deepcopy(SESSION_REC)
        rec["new_image"]["initial_context"] = {
            "S": json.dumps({"source": "campaign-x", "secret_payload": "drop-me"})
        }
        _post(Client(), [rec])
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.context_promoted, {"source": "campaign-x"})


@override_settings(
    CONSOLE_INDEX=LIVE_SETTINGS,
    REGIONS={
        "IN": {"pg_alias": "agents_pg", "mysql_alias": "default", "dynamo_region": "ap-south-1"},
        "ZA": {"pg_alias": "agents_pg_zz", "mysql_alias": "default_zz", "dynamo_region": "af-south-1"},
    },
    HOME_REGION="IN",
)
class RegionalWriteTests(TestCase):
    """The write paths bypass the router (raw DDL, transaction.atomic) and
    must follow the region the same way it does. ZA has no DATABASES entry
    here, so reaching for it is the proof."""
    databases = {"default", "agents_pg"}

    def test_partition_ddl_targets_the_regions_alias(self):
        import console_index.ingest as ingest_mod
        from django.utils.connection import ConnectionDoesNotExist
        from core.region import activate, deactivate

        ingest_mod._PARTITIONS_READY_FOR_MONTH.clear()
        ingest_mod._ensure_event_partitions()  # home: real DDL on agents_pg
        self.assertEqual(list(ingest_mod._PARTITIONS_READY_FOR_MONTH), ["agents_pg"])

        token = activate("ZA")
        try:
            with self.assertRaises(ConnectionDoesNotExist):
                ingest_mod._ensure_event_partitions()
        finally:
            deactivate(token)
        # Home's cache entry is untouched by the other region's attempt.
        self.assertEqual(list(ingest_mod._PARTITIONS_READY_FOR_MONTH), ["agents_pg"])

    def test_record_goes_to_its_streams_region(self):
        """The Lambda tags each record with the stream's AWS region; ingest
        applies it under that region. ZA has no database here, so a ZA record
        is a transient failure (retried by the Lambda) and never lands in
        India's table."""
        za = {**copy.deepcopy(SESSION_REC), "aws_region": "af-south-1"}
        unknown = {**copy.deepcopy(SESSION_REC), "aws_region": "eu-west-1"}
        home = {**copy.deepcopy(SESSION_REC), "aws_region": "ap-south-1"}
        resp = _post(self.client, [za, unknown, home])
        self.assertEqual(resp.json()["failed_indices"], [0, 1])
        self.assertEqual(ConsoleSession.objects.filter(session_id=SID).count(), 1)


class LambdaWrapTests(SimpleTestCase):
    def test_wrap_tags_table_and_region_from_the_stream_arn(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "forwarder",
            Path(__file__).parent.parent / "infra/lambda/console_index_forwarder/lambda_function.py",
        )
        forwarder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(forwarder)

        wrapped = forwarder._wrap({
            "eventSourceARN": "arn:aws:dynamodb:af-south-1:1234:table/med-assist-session/stream/2026",
            "eventName": "INSERT",
            "dynamodb": {"SequenceNumber": "1", "Keys": {}, "NewImage": {}},
        })
        self.assertEqual(wrapped["table"], "med-assist-session")
        self.assertEqual(wrapped["aws_region"], "af-south-1")


@override_settings(REGIONS={"IN": {"pg_alias": "agents_pg", "mysql_alias": "default", "dynamo_region": "ap-south-1"},
                            "ZA": {"pg_alias": "agents_pg_zz", "mysql_alias": "default_zz", "dynamo_region": "af-south-1"}},
                   HOME_REGION="IN")
class MaintenanceRegionIsolationTests(TestCase):
    databases = {"default", "agents_pg"}

    def test_one_regions_failure_does_not_skip_the_others(self):
        from io import StringIO
        from django.core.management import call_command, CommandError

        seen = []
        def fake_maintain(self, connection, dry_run):
            seen.append(connection.alias)
            if connection.alias == "agents_pg":
                raise RuntimeError("boom")
        mod = "console_index.management.commands.console_index_maintenance"
        fake_connections = MagicMock(); fake_connections.__getitem__ = lambda self, a: SimpleNamespace(alias=a)
        with patch(f"{mod}.Command._maintain", fake_maintain), patch(f"{mod}.connections", fake_connections):
            with self.assertRaises(CommandError):
                call_command("console_index_maintenance", stdout=StringIO())
        self.assertEqual(seen, ["agents_pg", "agents_pg_zz"])  # ZA still ran after IN failed


@override_settings(CONSOLE_INDEX={"DRY_RUN": False, "CONTEXT_KEYS": [], "REINGEST_DAYS": 15})
class PhoneCallContextTests(TestCase):
    """Phone calls are found by the number that answered, whatever CONTEXT_KEYS says."""

    databases = {"default", "agents_pg"}

    def test_call_summary_and_number_are_promoted_with_no_whitelist(self):
        rec = copy.deepcopy(SESSION_REC)
        call = {"v": 1, "duration_s": 42, "ended_by": "caller_hung_up", "handover": "none"}
        rec["new_image"]["initial_context"] = {
            "S": json.dumps({"call": call, "integration_uuid": "u-1", "secret_payload": "drop-me"})
        }
        _post(Client(), [rec])
        s = ConsoleSession.objects.get(session_id=SID)
        self.assertEqual(s.context_promoted, {"call": call, "integration_uuid": "u-1"})


class ParseContextTests(SimpleTestCase):
    @override_settings(CONSOLE_INDEX={"CONTEXT_KEYS": []})
    def test_phone_keys_survive_an_empty_whitelist(self):
        raw = json.dumps({"call": {"v": 1}, "integration_uuid": "u", "other": 1})
        self.assertEqual(ingest._parse_context(raw), {"call": {"v": 1}, "integration_uuid": "u"})

    @override_settings(CONSOLE_INDEX={"CONTEXT_KEYS": ["source"]})
    def test_configured_keys_are_added_to_them(self):
        raw = json.dumps({"call": {"v": 1}, "source": "x", "other": 1})
        self.assertEqual(ingest._parse_context(raw), {"call": {"v": 1}, "source": "x"})
