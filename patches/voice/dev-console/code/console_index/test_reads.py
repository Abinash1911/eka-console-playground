"""Tests for the PG-backed conversation list (reads.py + view integration)."""

import json
import uuid
from datetime import datetime, timezone as dt_timezone
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from console_index.models import ConsoleEvent, ConsoleSession
from console_index.reads import fetch_sessions, list_calls

ENGINE_ID = "ENGINE_b64"
WS = "77088166996724"

READS_ON = {"DRY_RUN": False, "CONTEXT_KEYS": [], "REINGEST_DAYS": 15, "READS": True}
READS_OFF = {**READS_ON, "READS": False}

JWT = json.dumps({"b-id": WS, "oid": "oid-1", "fn": "Test", "ln": "User"})


def _mk_session(i, **over):
    now = timezone.now()
    defaults = dict(
        session_id=uuid.uuid4(), agent_id=ENGINE_ID, wid=WS,
        created_at=now - timezone.timedelta(minutes=i),
        channels=["web"], msg_count=4, user_msg_count=2, tool_call_count=1,
        context_promoted={}, last_ingested_at=now,
    )
    defaults.update(over)
    return ConsoleSession.objects.create(**defaults)


def _mk_event(session, tool_name=None, params=None, msg_id=None):
    now = timezone.now()
    return ConsoleEvent.objects.create(
        session_id=session.session_id, msg_id=msg_id or f"m-{uuid.uuid4().hex[:6]}",
        tool_id="t-1" if tool_name else "", role="assistant",
        tool_name=tool_name, params=params, created_at=now, ingested_at=now,
    )


@override_settings(CONSOLE_INDEX=READS_ON)
class FetchSessionsFilterTests(TestCase):
    databases = {"default", "agents_pg"}

    def _fetch(self, **filters):
        return fetch_sessions(ENGINE_ID, WS, filters, page=1)

    def test_tool_name_filter(self):
        s1, s2 = _mk_session(1), _mk_session(2)
        _mk_event(s1, tool_name="selfcare_triage", params={"pathway": "Home care"})
        _mk_event(s2, tool_name="other_tool", params={})
        out = self._fetch(tool_name="selfcare_triage")
        self.assertEqual([r["session_id"] for r in out["sessions"]], [str(s1.session_id)])

    def test_param_value_string_and_int_coercion(self):
        s1, s2 = _mk_session(1), _mk_session(2)
        _mk_event(s1, tool_name="list_patients", params={"page_no": 0})        # int-typed
        _mk_event(s2, tool_name="list_patients", params={"page_no": "0x"})
        out = self._fetch(tool_name="list_patients", tool_param_name="page_no",
                          tool_param_value="0")
        self.assertEqual([r["session_id"] for r in out["sessions"]], [str(s1.session_id)])
        # param key only
        out = self._fetch(tool_param_name="page_no")
        self.assertEqual(len(out["sessions"]), 2)

    def test_date_channel_annotation_min_msgs(self):
        old = _mk_session(1, created_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
        wa = _mk_session(2, channels=["web", "whatsapp"], has_annotation=True,
                         user_msg_count=9)
        _mk_session(3)
        self.assertEqual(len(self._fetch(date_from="2026-06-01")["sessions"]), 2)
        self.assertEqual(len(self._fetch(date_to="2026-02-01")["sessions"]), 1)
        self.assertEqual(len(self._fetch(channels=["whatsapp"])["sessions"]), 1)
        self.assertEqual(len(self._fetch(has_feedback="1")["sessions"]), 1)
        self.assertEqual(len(self._fetch(has_feedback="0")["sessions"]), 2)
        self.assertEqual(len(self._fetch(min_user_msgs="5")["sessions"]), 1)
        self.assertEqual(
            [r["session_id"] for r in self._fetch(min_user_msgs="5")["sessions"]],
            [str(wa.session_id)],
        )

    def test_annotator_filter_via_mysql(self):
        from conversations.models import AnnotationForm, SessionAnnotation
        from core.models import WorkspaceFeature
        WorkspaceFeature.objects.get_or_create(workspace_id=WS)
        s1, s2 = _mk_session(1), _mk_session(2)
        form = AnnotationForm.objects.create(name="f", form_schema={})
        SessionAnnotation.objects.create(
            session_id=str(s1.session_id), annotation_form=form,
            oid="oid-9", workspace_id=WS, values={"x": 1},
        )
        out = self._fetch(annotator_oid="oid-9")
        self.assertEqual([r["session_id"] for r in out["sessions"]], [str(s1.session_id)])

    def test_all_filters_combined(self):
        """The query the old system could never run."""
        hit = _mk_session(1, channels=["whatsapp"], has_annotation=True, user_msg_count=6)
        _mk_event(hit, tool_name="selfcare_triage", params={"pathway": "Home care"})
        decoy = _mk_session(2, channels=["whatsapp"], has_annotation=True, user_msg_count=6)
        _mk_event(decoy, tool_name="selfcare_triage", params={"pathway": "Emergency care"})
        out = self._fetch(
            tool_name="selfcare_triage", tool_param_name="pathway",
            tool_param_value="Home care", channels=["whatsapp"],
            has_feedback="1", min_user_msgs="3",
        )
        self.assertEqual([r["session_id"] for r in out["sessions"]], [str(hit.session_id)])

    def test_new_filters_user_feedback_msg_ranges_channel_overlap(self):
        quiet = _mk_session(1, msg_count=3, user_msg_count=1)
        busy = _mk_session(2, msg_count=25, user_msg_count=9,
                           feedback={"nps_base5": 2, "values": []},
                           channels=["whatsapp", "voice"])
        # user feedback tri-state
        self.assertEqual(
            [r["session_id"] for r in self._fetch(user_feedback="1")["sessions"]],
            [str(busy.session_id)])
        self.assertEqual(
            [r["session_id"] for r in self._fetch(user_feedback="0")["sessions"]],
            [str(quiet.session_id)])
        # msgs window
        self.assertEqual(len(self._fetch(min_msgs="5", max_msgs="30")["sessions"]), 1)
        self.assertEqual(len(self._fetch(max_msgs="4")["sessions"]), 1)
        # user msgs max
        self.assertEqual(
            [r["session_id"] for r in self._fetch(max_user_msgs="2")["sessions"]],
            [str(quiet.session_id)])
        # multi-channel overlap: any selected channel matches
        out = self._fetch(channels=["web", "voice"])
        self.assertEqual(len(out["sessions"]), 2)  # quiet=web, busy=voice
        self.assertEqual(len(self._fetch(channels=["voice"])["sessions"]), 1)

    def test_archived_sessions_are_hidden(self):
        live, _ = _mk_session(1), _mk_session(2, archived=True)
        out = self._fetch()
        self.assertEqual([r["session_id"] for r in out["sessions"]], [str(live.session_id)])

    def test_pagination_without_count(self):
        """No COUNT(*)/SUM queries: has_next comes from the extra fetched row."""
        for i in range(7):
            _mk_session(i, msg_count=10)
        out = fetch_sessions(ENGINE_ID, WS, {}, page=2, page_size=3)
        self.assertEqual(out["page"], 2)
        self.assertTrue(out["has_next"] and out["has_prev"])
        self.assertEqual(len(out["sessions"]), 3)
        for gone in ("total_sessions", "total_msgs", "num_pages"):
            self.assertNotIn(gone, out)
        # last page: partial, no next
        out = fetch_sessions(ENGINE_ID, WS, {}, page=3, page_size=3)
        self.assertEqual(len(out["sessions"]), 1)
        self.assertFalse(out["has_next"])
        # past the end: empty page, not an error (no count to clamp against)
        out = fetch_sessions(ENGINE_ID, WS, {}, page=99, page_size=3)
        self.assertEqual((out["page"], out["sessions"], out["has_next"]), (99, [], False))

    def test_row_contract(self):
        s = _mk_session(1, context_promoted={"source": "x"}, feedback={"nps_base5": 4, "values": []},
                        has_annotation=True)
        row = self._fetch()["sessions"][0]
        for key in ("session_id", "date", "date_iso", "initial_context",
                    "initial_context_json", "has_context", "has_feedback",
                    "has_user_feedback", "msg_count", "tool_call_count", "channels"):
            self.assertIn(key, row)
        self.assertIsInstance(row["initial_context_json"], str)
        self.assertTrue(row["has_context"] and row["has_feedback"] and row["has_user_feedback"])
        self.assertEqual(row["session_id"], str(s.session_id))


@override_settings(CONSOLE_INDEX=READS_ON, DEBUG=False)
class ViewIntegrationTests(TestCase):
    databases = {"default", "agents_pg"}

    def setUp(self):
        from agents.models import AgentConfig
        self.cfg = AgentConfig.objects.create(
            alias="a1", name="A1", workspace_id=WS, agent_id=ENGINE_ID,
        )
        self.s = _mk_session(1)
        self.client = Client()

    def _get(self, **params):
        params.setdefault("agent_id", str(self.cfg.pk))
        return self.client.get("/conversations/", params, HTTP_JWT_PAYLOAD=JWT)

    def test_pg_mode_renders_sessions_and_columns(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["pg_mode"])
        self.assertEqual(len(resp.context["sessions"]), 1)
        self.assertFalse(resp.context["pg_has_next"])
        fields = [c["field"] for c in resp.context["table_columns"]]
        self.assertIn("msg_count", fields)
        self.assertIn("channels", fields)
        self.assertContains(resp, "conversation")

    def test_legacy_param_and_flag_off_fall_back(self):
        resp = self._get(legacy="1")
        self.assertFalse(resp.context["pg_mode"])
        with override_settings(CONSOLE_INDEX=READS_OFF):
            resp = self._get()
            self.assertFalse(resp.context["pg_mode"])

    def test_query_debug_middleware_logs_sql_and_plans(self):
        with override_settings(QUERY_DEBUG=True, QUERY_DEBUG_EXPLAIN=True):
            with self.assertLogs("core.query_debug", level="INFO") as logs:
                resp = self._get()
        self.assertEqual(resp.status_code, 200)
        out = "\n".join(logs.output)
        self.assertIn("SQL [agents_pg]", out)          # queries logged per alias
        self.assertIn("console_session", out)           # the pg list query itself
        self.assertIn("SQL PLAN [agents_pg]", out)      # EXPLAIN ran
        self.assertIn("SQL summary:", out)              # per-request rollup

    def test_session_id_search_bypasses_pg(self):
        # Path 1 stays on Dynamo regardless of the flag; with no Dynamo access
        # in tests it just returns no rows — but pg_mode must be False. The
        # redesigned chrome (pg_ui) stays on during a search.
        resp = self._get(filter_session_id=str(uuid.uuid4()))
        self.assertFalse(resp.context["pg_mode"])
        self.assertTrue(resp.context["pg_ui"])

    def test_page_size_whitelist(self):
        for raw, expected in (("25", 25), ("100", 100), ("26", 50), ("junk", 50), ("", 50)):
            resp = self._get(page_size=raw)
            self.assertEqual(resp.context["page_size"], expected, raw)

    def test_filters_qs_excludes_session_search(self):
        resp = self._get(filter_session_id=str(uuid.uuid4()), filter_min_msgs="2")
        qs = resp.context["filters_qs"]
        self.assertNotIn("filter_session_id", qs)
        self.assertIn("filter_min_msgs=2", qs)

    def test_current_filters_and_chips(self):
        resp = self._get(filter_channel=["web", "voice"], filter_min_msgs="4",
                         filter_user_feedback="1")
        current = json.loads(resp.context["current_filters_json"])
        self.assertEqual(current["filter_channel"], ["web", "voice"])
        self.assertEqual(current["filter_min_msgs"], "4")
        self.assertNotIn("date_from", current)
        self.assertEqual(resp.context["adv_filter_count"], 3)
        # Chips are segment lists: [{'k': 'label'|'value', 't': text}, ...]
        chips = [" ".join(seg["t"] for seg in c) for c in resp.context["active_chips"]]
        self.assertIn("Channels web, voice", chips)
        self.assertIn("Msgs ≥ 4", chips)

    def test_date_preset_defaults_to_last_7_days(self):
        resp = self._get()
        today = timezone.now().date()
        self.assertEqual(resp.context["date_preset"], "7d")
        self.assertEqual(resp.context["date_to"], today.isoformat())
        self.assertEqual(resp.context["date_from"],
                         (today - timezone.timedelta(days=6)).isoformat())
        self.assertEqual(
            json.loads(resp.context["current_filters_json"])["date_preset"], "7d")

    def test_default_view_is_not_treated_as_filtered(self):
        """The default preset fills date_from/date_to, but that must not make the
        landing page look filtered — the form stays expanded and Clear all hides."""
        resp = self._get()
        self.assertTrue(resp.context["is_default_view"])
        self.assertFalse(resp.context["has_active_filters"])
        # any deviation from the default *is* a filtered view
        self.assertFalse(self._get(date_preset="30d").context["is_default_view"])
        self.assertFalse(self._get(filter_min_msgs="2").context["is_default_view"])
        self.assertFalse(
            self._get(date_from="2026-01-01", date_to="2026-01-31").context["is_default_view"])

    def test_context_column_removed(self):
        fields = [c["field"] for c in self._get().context["table_columns"]]
        self.assertNotIn("has_context", fields)
        # the row still carries context for the detail panel
        self.assertIn("has_context", self._get().context["sessions"][0])

    def test_date_preset_resolves_to_live_range(self):
        resp = self._get(date_preset="7d")
        today = timezone.now().date()
        self.assertEqual(resp.context["date_to"], today.isoformat())
        self.assertEqual(resp.context["date_from"],
                         (today - timezone.timedelta(days=6)).isoformat())

    def test_date_preset_all_clears_bounds(self):
        resp = self._get(date_preset="all")
        self.assertEqual((resp.context["date_from"], resp.context["date_to"]), ("", ""))
        # 'All' is a real choice, so it is saveable — but it draws no chip.
        self.assertEqual(
            json.loads(resp.context["current_filters_json"])["date_preset"], "all")
        chips = [" ".join(seg["t"] for seg in c) for c in resp.context["active_chips"]]
        self.assertFalse([c for c in chips if c.startswith("Date")])

    def test_bare_range_is_custom_and_not_favoritable(self):
        resp = self._get(date_from="2026-01-01", date_to="2026-01-31")
        self.assertEqual(resp.context["date_preset"], "custom")
        self.assertEqual(resp.context["date_from"], "2026-01-01")
        self.assertNotIn("date_preset",
                         json.loads(resp.context["current_filters_json"]))


@override_settings(CONSOLE_INDEX=READS_ON, DEBUG=False)
class FavoriteFullStateTests(TestCase):
    databases = {"default", "agents_pg"}

    def setUp(self):
        from agents.models import AgentConfig
        self.cfg = AgentConfig.objects.create(
            alias="a1", name="A1", workspace_id=WS, agent_id=ENGINE_ID,
        )
        self.client = Client()

    def _post_fav(self, body):
        return self.client.post(
            "/conversations/favorites/", data=json.dumps(body),
            content_type="application/json", HTTP_JWT_PAYLOAD=JWT,
        )

    def test_full_state_save_whitelist_and_legacy_mirror(self):
        resp = self._post_fav({
            "agent_id": str(self.cfg.pk), "name": "triage-wa",
            "filters": {
                "filter_tool_name": "selfcare_triage",
                "filter_channel": ["whatsapp", "voice"],
                "filter_min_user_msgs": "3",
                "filter_user_feedback": "1",
                "date_from": "2026-01-01",     # a resolved range is never saved
                "agent_id": "999",             # junk — stripped
                "evil": "x",                   # junk — stripped
            },
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["filters"], {
            "filter_tool_name": "selfcare_triage",
            "filter_channel": ["whatsapp", "voice"],
            "filter_min_user_msgs": "3",
            "filter_user_feedback": "1",
            # no date_preset was sent, so the favorite imposes no date bound
            "date_preset": "all",
        })
        self.assertNotIn("date_from", data["filters"])
        # legacy column mirrored for rollback safety
        self.assertEqual(data["filter_tool_name"], "selfcare_triage")

    def test_date_preset_is_saved_as_a_key(self):
        data = self._post_fav({
            "agent_id": str(self.cfg.pk), "name": "last-week",
            "filters": {"date_preset": "7d", "filter_tool_name": "t"},
        }).json()
        self.assertEqual(data["filters"]["date_preset"], "7d")

    def test_custom_range_preset_is_not_saveable(self):
        data = self._post_fav({
            "agent_id": str(self.cfg.pk), "name": "adhoc",
            "filters": {"date_preset": "custom", "filter_tool_name": "t"},
        }).json()
        # 'custom' is dropped by the whitelist; the payload falls back to 'all'
        # rather than pinning a range that would go stale — or silently
        # narrowing the favorite to the Today page default.
        self.assertEqual(data["filters"]["date_preset"], "all")

    def test_pre_date_rows_are_not_narrowed_to_today(self):
        """Both shapes seen in prod: a legacy row with filters={} that only has
        the 3 flat columns, and a newer row with a populated dict but no
        date_preset. Neither ever constrained dates, so both must resolve to
        'all' — defaulting them to Today would silently empty out favorites
        whose sessions predate today."""
        from conversations.models import FavoriteFilter
        from conversations.views import _favorite_payload

        legacy = FavoriteFilter.objects.create(
            workspace_id=WS, agent_pk=self.cfg.pk, name="Triage:Green",
            filter_tool_name="selfcare_triage",
            filter_tool_param_name="severity_level",
            filter_tool_param_value="Mild / self-limiting",
            filters={},
        )
        full = FavoriteFilter.objects.create(
            workspace_id=WS, agent_pk=self.cfg.pk, name="sample1",
            filter_tool_name="elicit_selection",
            filters={"filter_channel": ["web", "whatsapp"], "filter_max_msgs": "6",
                     "filter_tool_name": "elicit_selection", "filter_has_feedback": "1"},
        )

        legacy_filters = _favorite_payload(legacy)["filters"]
        self.assertEqual(legacy_filters["date_preset"], "all")
        # the flat columns are still synthesized into the dict
        self.assertEqual(legacy_filters["filter_tool_name"], "selfcare_triage")
        self.assertEqual(legacy_filters["filter_tool_param_value"], "Mild / self-limiting")

        full_filters = _favorite_payload(full)["filters"]
        self.assertEqual(full_filters["date_preset"], "all")
        self.assertEqual(full_filters["filter_channel"], ["web", "whatsapp"])
        self.assertEqual(full_filters["filter_max_msgs"], "6")

    def test_legacy_row_synthesizes_filters(self):
        from conversations.models import FavoriteFilter
        FavoriteFilter.objects.create(
            workspace_id=WS, agent_pk=self.cfg.pk, name="old",
            filter_tool_name="list_patients", filter_tool_param_name="page_no",
            filter_tool_param_value="0",
        )
        resp = self.client.get("/conversations/", {"agent_id": str(self.cfg.pk)},
                               HTTP_JWT_PAYLOAD=JWT)
        fav = resp.context["favorites"][0]
        self.assertEqual(fav["filters"], {
            "filter_tool_name": "list_patients",
            "filter_tool_param_name": "page_no",
            "filter_tool_param_value": "0",
        })

    def test_patch_rename_and_update_filters(self):
        from conversations.models import FavoriteFilter
        resp = self._post_fav({"agent_id": str(self.cfg.pk), "name": "orig",
                               "filters": {"filter_tool_name": "t1"}})
        fav_id = resp.json()["id"]

        # Rename
        resp = self.client.patch(
            f"/conversations/favorites/{fav_id}/",
            data=json.dumps({"name": "renamed"}),
            content_type="application/json", HTTP_JWT_PAYLOAD=JWT,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "renamed")

        # Update filters: cleaned + legacy columns re-mirrored
        resp = self.client.patch(
            f"/conversations/favorites/{fav_id}/",
            data=json.dumps({"filters": {"filter_tool_name": "t2",
                                         "filter_channel": ["web"],
                                         "date_from": "2026-01-01"}}),
            content_type="application/json", HTTP_JWT_PAYLOAD=JWT,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["filters"],
                         {"filter_tool_name": "t2", "filter_channel": ["web"]})
        row = FavoriteFilter.objects.get(pk=fav_id)
        self.assertEqual(row.filter_tool_name, "t2")

    def test_duplicate_name_rejected_case_insensitive(self):
        self._post_fav({"agent_id": str(self.cfg.pk), "name": "Triage",
                        "filters": {"filter_tool_name": "t1"}})
        resp = self._post_fav({"agent_id": str(self.cfg.pk), "name": "triage",
                               "filters": {"filter_tool_name": "t2"}})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.json()["error"])

        # PATCH rename onto an existing name is rejected too
        other = self._post_fav({"agent_id": str(self.cfg.pk), "name": "other",
                                "filters": {"filter_tool_name": "t3"}}).json()
        resp = self.client.patch(
            f"/conversations/favorites/{other['id']}/",
            data=json.dumps({"name": "TRIAGE"}),
            content_type="application/json", HTTP_JWT_PAYLOAD=JWT,
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_filters_rejected(self):
        resp = self._post_fav({"agent_id": str(self.cfg.pk), "name": "empty",
                               "filters": {"date_from": "2026-01-01"}})
        self.assertEqual(resp.status_code, 400)

    def test_view_parses_multi_channel_and_filters_qs(self):
        _mk_session(1)
        resp = self.client.get(
            "/conversations/",
            {"agent_id": str(self.cfg.pk), "filter_channel": ["web", "voice"],
             "filter_min_msgs": "2", "page": "1", "legacy": ""},
            HTTP_JWT_PAYLOAD=JWT,
        )
        self.assertEqual(resp.context["filter_channels"], ["web", "voice"])
        qs = resp.context["filters_qs"]
        self.assertIn("filter_channel=web", qs)
        self.assertIn("filter_channel=voice", qs)
        self.assertIn("filter_min_msgs=2", qs)
        self.assertNotIn("page=", qs)
        self.assertNotIn("legacy", qs)
        self.assertTrue(resp.context["has_active_filters"])


# Pinned to one region: the command loops over every configured region, and a
# local .env may configure a ZA whose databases this test may not touch.
@override_settings(REGIONS={"IN": {"pg_alias": "agents_pg", "mysql_alias": "default", "dynamo_region": "ap-south-1"}}, HOME_REGION="IN")
class SyncAnnotationFlagsTests(TestCase):
    databases = {"default", "agents_pg"}

    def test_flags_set_and_idempotent(self):
        from conversations.models import AnnotationForm, SessionAnnotation
        from core.models import WorkspaceFeature
        WorkspaceFeature.objects.get_or_create(workspace_id=WS)
        s1, s2 = _mk_session(1), _mk_session(2)
        form = AnnotationForm.objects.create(name="f", form_schema={})
        SessionAnnotation.objects.create(
            session_id=str(s1.session_id), annotation_form=form,
            oid="o", workspace_id=WS, values={"x": 1},
        )
        out = StringIO()
        call_command("sync_annotation_flags", stdout=out)
        self.assertIn("Flagged 1 sessions", out.getvalue())
        s1.refresh_from_db(); s2.refresh_from_db()
        self.assertTrue(s1.has_annotation)
        self.assertFalse(s2.has_annotation)
        out = StringIO()
        call_command("sync_annotation_flags", stdout=out)
        self.assertIn("Flagged 0 sessions", out.getvalue())


@override_settings(CONSOLE_INDEX=READS_ON)
class ListCallsTests(TestCase):
    databases = {"default", "agents_pg"}

    def _call(self, i, number="n-1", **over):
        return _mk_session(i, context_promoted={"integration_uuid": number, "call": {"v": 1}}, **over)

    def test_only_this_numbers_calls_newest_first(self):
        older, newer = self._call(5), self._call(1)
        self._call(2, number="n-2")
        _mk_session(3)  # a web chat
        out = list_calls(ENGINE_ID, "n-1")
        self.assertEqual([s.session_id for s in out["calls"]], [newer.session_id, older.session_id])

    def test_other_agents_and_archived_calls_are_left_out(self):
        self._call(1, agent_id="OTHER")
        self._call(2, archived=True)
        self.assertEqual(list_calls(ENGINE_ID, "n-1")["calls"], [])

    def test_paging(self):
        for i in range(1, 6):
            self._call(i)
        first = list_calls(ENGINE_ID, "n-1", page=1, page_size=2)
        last = list_calls(ENGINE_ID, "n-1", page=3, page_size=2)
        self.assertEqual((len(first["calls"]), first["has_next"], first["has_prev"]), (2, True, False))
        self.assertEqual((len(last["calls"]), last["has_next"], last["has_prev"]), (1, False, True))
        self.assertEqual(list_calls(ENGINE_ID, "n-1", page="junk")["page"], 1)
