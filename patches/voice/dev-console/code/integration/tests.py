from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError

from integration import templates as client
from integration.schemas.templates import CreateTemplateRequest, TemplateSendRequest, variable_slots

BODY = {"type": "BODY", "text": "Hi {{1}}", "example": {"body_text": [["Asha"]]}}


def _create(header):
    return CreateTemplateRequest.model_validate(
        {"name": "eticket", "language": "en", "category": "UTILITY", "components": [header, BODY]}
    )


class MediaHeaderSchemaTests(SimpleTestCase):
    def test_media_header_needs_a_sample_handle(self):
        with self.assertRaisesRegex(ValidationError, "header_handle"):
            _create({"type": "HEADER", "format": "DOCUMENT"})
        _create({"type": "HEADER", "format": "DOCUMENT", "example": {"header_handle": ["4:abc"]}})

    def test_slots_report_the_media_header(self):
        slots = variable_slots({"components": [{"type": "HEADER", "format": "DOCUMENT"}, BODY]})
        self.assertEqual(slots, {"header": 0, "body": 1, "header_media": "document", "buttons": []})

    def test_send_builds_the_document_header(self):
        req = TemplateSendRequest.model_validate({
            "to": "919876543210", "template_name": "eticket", "params": ["Asha"],
            "header_media": {"type": "document", "link": "https://x/t.pdf", "filename": "ETicket.pdf"},
        })
        self.assertEqual(req.components()[0], {
            "type": "header",
            "parameters": [{"type": "document", "document": {"link": "https://x/t.pdf", "filename": "ETicket.pdf"}}],
        })

    def test_send_takes_one_kind_of_header(self):
        with self.assertRaises(ValidationError):
            TemplateSendRequest.model_validate({
                "to": "919876543210", "template_name": "eticket", "header_params": ["Dr. Rao"],
                "header_media": {"type": "image", "link": "https://x/y.png"},
            })


def _response(body):
    resp = MagicMock(ok=True, content=b"{}")
    resp.json.return_value = body
    return resp


@override_settings(INTERAKT_ISV_TOKEN="tok")
class UploadSampleTests(SimpleTestCase):
    @patch("integration.templates.requests.request")
    def test_session_then_multipart_upload_returns_the_first_handle(self, request):
        request.side_effect = [_response({"id": "upload:abc?sig=1"}), _response({"h": "4:first\n4:second"})]
        pdf = SimpleUploadedFile("ETicket.pdf", b"%PDF-1.4 sample", content_type="application/pdf")

        self.assertEqual(client.upload_sample("waba-1", pdf), "4:first")

        (open_args, open_kw), (send_args, send_kw) = request.call_args_list
        self.assertEqual(open_args, ("POST", f"{client.AMPED}/app/uploads"))
        self.assertEqual(open_kw["params"]["file_length"], len(b"%PDF-1.4 sample"))
        self.assertEqual(send_args, ("POST", f"{client.AMPED}/upload:abc?sig=1"))
        self.assertEqual(send_kw["headers"], {"x-access-token": "tok", "x-waba-id": "waba-1", "file_offset": "0"})
        self.assertEqual(send_kw["files"]["file"][0], "ETicket.pdf")

    @patch("integration.templates.requests.request")
    def test_unsupported_sample_is_rejected_before_upload(self, request):
        doc = SimpleUploadedFile("notes.txt", b"hi", content_type="text/plain")
        with self.assertRaises(client.TemplateError) as ctx:
            client.upload_sample("waba-1", doc)
        self.assertEqual(ctx.exception.kind, "rejected")
        request.assert_not_called()


@override_settings(DOOT_WEBHOOK_BASE_URL="https://doot.test")
class WebhookUrlCardTests(SimpleTestCase):
    def _context(self, provider):
        from integration import views
        from integration.models import Integration

        integ = Integration(provider=provider, channel="whatsapp", integration_type="whatsapp")
        request = MagicMock(user_context={}, workspace_id="ws-1")
        with patch.object(views, "_binding_context", return_value={}), \
                patch.object(views, "_credential_rows", return_value=[]), \
                patch.object(views, "render") as render:
            views._render(request, integ)
        return integ, render.call_args.args[2]

    def test_manual_provider_shows_uuid_url(self):
        integ, context = self._context("interakt")
        self.assertTrue(context["webhook_manual"])
        self.assertEqual(
            context["webhook_url"],
            f"https://doot.test/integration/v1/channel/whatsapp/messages/inbound/{integ.uuid}",
        )

    def test_interakt_tp_is_registered_for_you(self):
        _, context = self._context("interakt_tp")
        self.assertFalse(context["webhook_manual"])


class VobizSchemaTests(SimpleTestCase):
    def test_number_is_normalised_and_is_the_account_identity(self):
        from integration import schemas

        creds, uid = schemas.validate("telephony", "vobiz", {"phone_number": "+91 80000-12345"})
        self.assertEqual(uid, "+918000012345")
        self.assertEqual(creds["phone_number"], "+918000012345")

    def test_numbers_without_a_country_code_are_rejected(self):
        from integration import schemas

        for bad in ("8000012345", "+0123456789", "+91", "call me"):
            with self.assertRaises(ValidationError, msg=bad):
                schemas.validate("telephony", "vobiz", {"phone_number": bad})
        with self.assertRaises(ValidationError):
            schemas.validate(
                "telephony", "vobiz", {"phone_number": "+918000012345", "public_number": "98765"}
            )

    def test_public_number_is_optional_and_visible(self):
        from integration import schemas

        creds, _ = schemas.validate(
            "telephony", "vobiz",
            {"phone_number": "+918000012345", "public_number": "+91 98765 43210"},
        )
        self.assertEqual(
            schemas.public("telephony", "vobiz", creds),
            {"phone_number": "+918000012345", "public_number": "+919876543210"},
        )

    def test_dialled_number_cannot_be_changed_by_an_update(self):
        from integration import schemas

        creds, _ = schemas.validate("telephony", "vobiz", {"phone_number": "+918000012345"})
        merged, uid = schemas.merge("telephony", "vobiz", creds, {"public_number": "+919876543210"})
        self.assertEqual(uid, "+918000012345")
        self.assertEqual(merged["public_number"], "+919876543210")
        with self.assertRaises(ValidationError):
            schemas.merge("telephony", "vobiz", creds, {"phone_number": "+918000099999"})

    def test_provider_must_belong_to_the_channel(self):
        from integration import schemas

        with self.assertRaises(schemas.UnsupportedProvider):
            schemas.validate("whatsapp", "vobiz", {"phone_number": "+918000012345"})
        with self.assertRaises(schemas.UnsupportedProvider):
            schemas.validate("telephony", "interakt", {"api_key": "k"})

    def test_create_request_accepts_a_telephony_number(self):
        from integration.schemas.requests import CreateIntegrationRequest

        req = CreateIntegrationRequest.model_validate({
            "name": "Clinic line", "channel": "telephony", "provider": "vobiz",
            "credentials": {"phone_number": "+918000012345"},
        })
        self.assertEqual(req.provider, "vobiz")
        with self.assertRaises(ValidationError):
            CreateIntegrationRequest.model_validate({
                "name": "Clinic line", "channel": "telephony", "provider": "vobiz",
                "credentials": {"phone_number": "nope"},
            })


@override_settings(DOOT_WEBHOOK_BASE_URL="https://doot.test", MATRIX_VOICE_BASE_URL="https://matrix.test/")
class TelephonyAnswerUrlTests(SimpleTestCase):
    def _integration(self, channel, provider):
        from integration.models import Integration

        return Integration(provider=provider, channel=channel, integration_type=channel)

    def test_a_telephony_number_points_at_matrix_by_uuid(self):
        from integration import webhooks

        integ = self._integration("telephony", "vobiz")
        self.assertEqual(
            webhooks.inbound_url(integ),
            f"https://matrix.test/reloaded/med-assist/voice/answer/{integ.uuid}",
        )

    def test_whatsapp_still_points_at_doot(self):
        from integration import webhooks

        integ = self._integration("whatsapp", "interakt")
        self.assertEqual(
            webhooks.inbound_url(integ),
            f"https://doot.test/integration/v1/channel/whatsapp/messages/inbound/{integ.uuid}",
        )

    def test_the_url_is_pasted_by_hand_into_vobiz(self):
        from integration import webhooks

        self.assertNotIn("vobiz", webhooks.PROGRAMMABLE_PROVIDERS)


class AgentHandoverConfigTests(SimpleTestCase):
    def _validate(self, config):
        from integration.schemas import products

        return products.validate("agent", config)

    def test_staff_number_is_normalised_and_the_rest_defaults(self):
        config = self._validate({"handover": {"number": "+91 99999-11111"}})
        self.assertEqual(
            config["handover"], {"number": "+919999911111", "hours": None, "ring_seconds": 30}
        )

    def test_hours_can_run_overnight_but_not_be_empty(self):
        config = self._validate({
            "handover": {"number": "+919999911111", "hours": {"start": "22:00", "end": "06:00"}}
        })
        self.assertEqual(config["handover"]["hours"]["timezone"], "Asia/Kolkata")
        with self.assertRaises(ValidationError):
            self._validate({
                "handover": {"number": "+919999911111", "hours": {"start": "09:00", "end": "09:00"}}
            })

    def test_bad_values_are_rejected(self):
        number = "+919999911111"
        bad = [
            {"number": "99999"},
            {"number": number, "ring_seconds": 5},
            {"number": number, "ring_seconds": 61},
            {"number": number, "hours": {"start": "9am", "end": "18:00"}},
            {"number": number, "hours": {"start": "09:00", "end": "25:00"}},
            {"number": number, "hours": {"start": "09:00", "end": "18:00", "timezone": "Mars/Base"}},
            {"number": number, "ring_to": "+911111111111"},
        ]
        for handover in bad:
            with self.assertRaises(ValidationError, msg=handover):
                self._validate({"handover": handover})

    def test_the_status_callback_still_works_alongside_it(self):
        config = self._validate({
            "status": {"url": "https://example.com/status"},
            "handover": {"number": "+919999911111"},
        })
        self.assertEqual(config["status"]["url"], "https://example.com/status")

    def test_a_binding_request_carries_it(self):
        from uuid import uuid4

        from integration.schemas.requests import CreateProductIntegrationRequest

        req = CreateProductIntegrationRequest.model_validate({
            "product": "agent", "product_id": "agent-1", "integration": str(uuid4()),
            "config": {"handover": {"number": "+91 99999 11111"}},
        })
        self.assertEqual(req.config["handover"]["number"], "+91 99999 11111")  # raw; normalised on save
        with self.assertRaises(ValidationError):
            CreateProductIntegrationRequest.model_validate({
                "product": "agent", "product_id": "agent-1", "integration": str(uuid4()),
                "config": {"handover": {"number": "nope"}},
            })


class CallbackSlotTests(SimpleTestCase):
    """The binding form lists a product's callback slots; other config settings are not callbacks."""

    def test_only_callback_fields_are_slots(self):
        from integration import views

        self.assertEqual(views._slots("agent"), ("status",))
        self.assertEqual(views._slots("messenger"), ("messages", "status"))
        self.assertEqual(views._slots("ekascribe"), ())

    def test_handover_does_not_become_a_callback_box(self):
        from integration import views

        config = {"status": None, "handover": {"number": "+919999911111"}}
        blocks = views._callback_blocks("agent", config)
        self.assertEqual([b["url_field"] for b in blocks], ["agent_status_url"])


def _post(data):
    from django.test import RequestFactory

    request = RequestFactory().post("/", data)
    request.workspace_id = "ws-1"
    request.user_context = {}
    return request


class HandoverFormTests(SimpleTestCase):
    """The phone number page's handover section, read back into the binding config."""

    def _read(self, **data):
        from integration import views

        return views._handover_from_post(_post(data))

    def test_a_form_without_the_section_leaves_the_stored_handover_alone(self):
        from integration import views

        self.assertIs(self._read(product="agent"), views.KEEP_HANDOVER)

    def test_unticked_turns_it_off_whatever_else_was_typed(self):
        self.assertIsNone(self._read(handover_form="1", handover_number="+919999911111"))

    def test_ticked_with_a_number_uses_the_defaults(self):
        self.assertEqual(
            self._read(handover_form="1", handover_enabled="1", handover_number=" +91 99999 11111 "),
            {"number": "+91 99999 11111", "ring_seconds": 30},
        )

    def test_hours_come_with_a_timezone(self):
        handover = self._read(
            handover_form="1", handover_enabled="1", handover_number="+919999911111",
            handover_start="09:00", handover_end="18:00", handover_ring_seconds="20",
        )
        self.assertEqual(handover["hours"], {"start": "09:00", "end": "18:00", "timezone": "Asia/Kolkata"})
        self.assertEqual(handover["ring_seconds"], "20")  # validated and made an int by the schema

    def test_hours_need_both_ends_or_neither(self):
        with self.assertRaisesRegex(ValueError, "both a start and an end"):
            self._read(
                handover_form="1", handover_enabled="1", handover_number="+919999911111",
                handover_start="09:00",
            )

    def test_the_form_shows_stored_settings_or_empty_defaults(self):
        from integration import views

        binding = MagicMock(config={"handover": {
            "number": "+919999911111", "ring_seconds": 25,
            "hours": {"start": "09:00", "end": "18:00", "timezone": "Asia/Kolkata"},
        }})
        self.assertEqual(views._handover_form(binding), {
            "enabled": True, "number": "+919999911111", "start": "09:00", "end": "18:00",
            "timezone": "Asia/Kolkata", "ring_seconds": 25,
        })
        empty = views._handover_form(None)
        self.assertFalse(empty["enabled"])
        self.assertEqual((empty["timezone"], empty["ring_seconds"]), ("Asia/Kolkata", 30))
        self.assertFalse(views._handover_form(MagicMock(config={"status": None}))["enabled"])


class BindPhoneNumberTests(SimpleTestCase):
    """Connecting a phone number to an agent from the console."""

    def setUp(self):
        from types import SimpleNamespace

        from integration import views

        self.views = views
        self.integ = SimpleNamespace(
            pk=7, workspace_id="ws-1", _channel="telephony", channel="telephony", provider="vobiz"
        )
        self.agent = SimpleNamespace(pk=3, agent_id="agent-1", name="Front desk")
        patches = [
            patch.object(views, "get_object_or_404", return_value=self.integ),
            patch.object(views, "AgentConfig"),
            patch.object(views, "ProductIntegration"),
            patch.object(views, "webhooks"),
            patch.object(views, "_render", return_value="rendered"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        _, self.agent_config, self.binding, _, self.render = mocks
        self.agent_config.objects.filter.return_value.first.return_value = self.agent
        self.binding.objects.filter.return_value.first.return_value = None

    def _bind(self, **data):
        return self.views.bind_product(_post({"product": "agent", "agent": "3", **data}), pk=7)

    def test_connecting_with_handover_stores_it_normalised(self):
        self._bind(
            handover_form="1", handover_enabled="1", handover_number="+91 99999 11111",
            handover_start="09:00", handover_end="18:00",
        )
        config = self.binding.objects.create.call_args.kwargs["config"]
        self.assertEqual(config["handover"]["number"], "+919999911111")
        self.assertEqual(config["handover"]["hours"]["end"], "18:00")
        self.assertEqual(config["handover"]["ring_seconds"], 30)
        self.assertIsNone(config["status"])

    def test_connecting_without_ticking_stores_no_handover(self):
        self._bind(handover_form="1")
        self.assertIsNone(self.binding.objects.create.call_args.kwargs["config"]["handover"])

    def test_saving_a_form_with_no_handover_section_keeps_what_was_stored(self):
        existing = MagicMock(product="agent", config={"handover": {"number": "+919999911111"}})
        self.binding.objects.filter.return_value.first.return_value = existing
        self._bind()
        self.assertEqual(existing.config["handover"]["number"], "+919999911111")
        existing.save.assert_called_once()

    def test_unticking_removes_it(self):
        existing = MagicMock(product="agent", config={"handover": {"number": "+919999911111"}})
        self.binding.objects.filter.return_value.first.return_value = existing
        self._bind(handover_form="1")
        self.assertIsNone(existing.config["handover"])

    def test_a_bad_number_shows_the_error_and_what_was_typed(self):
        self._bind(handover_form="1", handover_enabled="1", handover_number="99999")
        error = self.render.call_args.kwargs
        self.assertIn("handover number", error["error"])
        self.assertEqual(error["handover"]["number"], "99999")
        self.assertTrue(error["handover"]["enabled"])
        self.binding.objects.create.assert_not_called()

    def test_half_filled_hours_show_an_error(self):
        self._bind(
            handover_form="1", handover_enabled="1", handover_number="+919999911111",
            handover_end="18:00",
        )
        self.assertIn("both a start and an end", self.render.call_args.kwargs["error"])

    def test_a_phone_number_cannot_be_a_messenger(self):
        self.views.bind_product(_post({"product": "messenger"}), pk=7)
        self.assertEqual(self.render.call_args.kwargs["error"], "A phone number connects to an agent.")
        self.binding.objects.create.assert_not_called()

    def test_a_whatsapp_number_can_still_be_a_messenger_and_has_no_handover(self):
        self.integ._channel = "whatsapp"
        self.views.bind_product(_post({"product": "messenger", "usecase": "ekascribe"}), pk=7)
        config = self.binding.objects.create.call_args.kwargs["config"]
        self.assertNotIn("handover", config)


class CreatePhoneNumberTests(SimpleTestCase):
    """Registering a phone number from the console."""

    def setUp(self):
        from agents.views import integrations as views

        self.views = views
        patches = [
            patch.object(views, "render", return_value="rendered"),
            patch("integration.models.Integration.save", autospec=True),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.render, self.save = mocks
        # A saved row has an id; the redirect to its page needs one.
        self.save.side_effect = lambda integ, *args, **kwargs: setattr(integ, "id", 11)

    def _create(self, **data):
        return self.views.integration_create(
            _post({"name": "Front desk", "provider": "vobiz", "phone_number": "+91 80000-12345", **data})
        )

    def test_a_valid_number_is_saved_as_a_telephony_integration(self):
        response = self._create(public_number="+91 98765 43210")
        self.save.assert_called_once()
        integ = self.save.call_args.args[0]
        self.assertEqual((integ.integration_type, integ.provider), ("telephony", "vobiz"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/integrations/11/"))

    def test_the_number_is_normalised_and_keys_the_account(self):
        self._create(public_number="+91 98765 43210")
        integ = self.save.call_args.args[0]
        self.assertEqual(integ.integration_uid, "+918000012345")
        self.assertEqual(integ.get_credentials()["public_number"], "+919876543210")

    def test_a_clinic_number_without_a_country_code_is_refused_too(self):
        self._create(public_number="98765 43210")
        self.assertIn("public number", self.render.call_args.args[2]["error"])
        self.save.assert_not_called()

    def test_a_number_without_a_country_code_shows_an_error_and_keeps_the_form(self):
        self._create(phone_number="80000 12345")
        template, context = self.render.call_args.args[1], self.render.call_args.args[2]
        self.assertEqual(template, "integrations/create_phone.html")
        self.assertIn("phone number", context["error"])
        self.assertEqual(context["form"]["phone_number"], "80000 12345")
        self.assertEqual(context["form"]["name"], "Front desk")
        self.save.assert_not_called()

    def test_a_number_registered_twice_says_so(self):
        from django.db import IntegrityError

        self.save.side_effect = IntegrityError("duplicate")
        self._create()
        self.assertIn("already registered", self.render.call_args.args[2]["error"])

    def test_the_phone_form_is_offered(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/", {"provider": "vobiz"})
        request.workspace_id, request.user_context = "ws-1", {}
        self.views.integration_create(request)
        self.assertEqual(self.render.call_args.args[1], "integrations/create_phone.html")


def _stub_engine():
    """Real console templates, with a bare base layout (the real one reads the database)."""
    from django.conf import settings
    from django.template import Engine

    stub = "{% block breadcrumbs %}{% endblock %}{% block content %}{% endblock %}{% block extra_js %}{% endblock %}"
    return Engine(
        loaders=[
            ("django.template.loaders.locmem.Loader", {"base.html": stub}),
            ("django.template.loaders.filesystem.Loader", [str(settings.BASE_DIR / "templates")]),
        ],
        libraries={"ui_components": "core.templatetags.ui_components"},
    )


class PhoneNumberPageTests(SimpleTestCase):
    """What the number's page shows, rendered from the real template."""

    def _page(self, **overrides):
        from types import SimpleNamespace as NS
        from uuid import uuid4

        from django.template import Context

        integration = NS(
            pk=7, name="Front desk", provider="vobiz", get_provider_display="Vobiz", uuid=uuid4()
        )
        context = {
            "csrf_token": "x", "integration": integration, "credential_rows": [], "webhook_manual": True,
            "webhook_url": "https://matrix.test/answer/abc", "is_phone": True, "binding": None,
            "bound_agent": None, "agents": [NS(pk=3, name="Front desk agent")],
            "callback_blocks": {"agent": [{"label": "Status callback", "url": "", "url_field": "agent_status_url",
                                           "key_field": "k", "value_field": "v", "headers_json": "[]",
                                           "headers_count": 0}], "messenger": []},
            "handover": {"enabled": True, "number": "+919999911111", "start": "09:00", "end": "18:00",
                         "timezone": "Asia/Kolkata", "ring_seconds": 30},
            "messenger_product_id": "default", "messenger_usecases": [], "messenger_usecase": "",
            **overrides,
        }
        return _stub_engine().get_template("integrations/detail.html").render(Context(context))

    def test_a_phone_number_offers_the_agent_and_handover_only(self):
        html = self._page()
        self.assertIn("Answer calls with an agent", html)
        self.assertIn("Hand over to a person", html)
        self.assertIn('name="handover_number"', html)
        self.assertIn('value="+919999911111"', html)
        self.assertIn("Answer URL", html)
        self.assertNotIn("Messenger", html)
        self.assertNotIn("Status callback", html)

    def test_a_whatsapp_number_is_unchanged(self):
        html = self._page(is_phone=False)
        self.assertIn("Messenger", html)
        self.assertIn("Status callback", html)
        self.assertNotIn("Hand over to a person", html)
        self.assertIn("Webhook URL", html)

    def test_the_agent_page_is_linked_for_voice_settings(self):
        from types import SimpleNamespace as NS

        html = self._page(bound_agent=NS(pk=3, name="Front desk agent"))
        self.assertIn("voice, language and greeting", html)
        self.assertIn('href="/agents/3/"', html)

    def test_the_create_page_keeps_what_was_typed(self):
        from django.template import Context

        html = _stub_engine().get_template("integrations/create_phone.html").render(
            Context({"csrf_token": "x", "error": "phone number: bad",
                     "form": {"name": "Front desk", "phone_number": "80000", "public_number": ""}})
        )
        self.assertIn("phone number: bad", html)
        self.assertIn('value="80000"', html)
        self.assertIn('value="Front desk"', html)

    def test_the_provider_picker_offers_a_phone_number(self):
        from django.template import Context

        html = _stub_engine().get_template("integrations/create.html").render(Context({"csrf_token": "x"}))
        self.assertIn("?provider=vobiz", html)
        self.assertIn("Inbound calls via Vobiz", html)


class CallRowTests(SimpleTestCase):
    """How a saved call summary reads on the Calls page."""

    def _row(self, call=None, **over):
        from datetime import datetime, timezone
        from types import SimpleNamespace as NS
        from uuid import uuid4

        from integration import calls

        promoted = {"call": call} if call is not None else {}
        return calls.present(NS(
            session_id=uuid4(), context_promoted=promoted,
            created_at=datetime(2026, 10, 29, 9, 30, tzinfo=timezone.utc), **over,
        ))

    def _call(self, **over):
        return {"v": 1, "duration_s": 131, "ended_by": "caller_hung_up", "user_turns": 4,
                "handover": "none", "tools": ["book_appointment"], "caller": "+91xxxxxx3210", **over}

    def test_a_normal_call(self):
        row = self._row(self._call())
        self.assertEqual(
            (row["duration"], row["outcome"], row["tone"], row["ended"], row["caller"], row["tools"]),
            ("2:11", "Answered by agent", "ok", "Caller hung up", "+91xxxxxx3210", ["book_appointment"]),
        )

    def test_outcomes(self):
        cases = [
            ({"user_turns": 0}, "No conversation"),
            ({"user_turns": 0, "handover": "transferred"}, "No conversation"),
            ({"handover": "transferred", "ended_by": "transferred"}, "Handed over"),
            ({"handover": "failed"}, "Handover failed"),
            ({"handover": "declined"}, "Outside staff hours"),
            ({"ended_by": "error"}, "Error"),
        ]
        for over, label in cases:
            with self.subTest(over=over):
                self.assertEqual(self._row(self._call(**over))["outcome"], label)

    def test_a_session_without_a_summary_does_not_break_the_page(self):
        row = self._row(None)
        self.assertEqual(
            (row["duration"], row["caller"], row["ended"], row["recorded"], row["outcome"]),
            ("—", "Unknown", "—", False, "Not recorded"),
        )

    def test_unknown_values_show_a_dash_not_an_error(self):
        row = self._row(self._call(ended_by="from_the_future", handover="???", duration_s="x"))
        self.assertEqual((row["ended"], row["handover"], row["duration"]), ("—", "—", "—"))

    def test_stats_cover_the_rows_shown(self):
        from integration import calls

        rows = [self._row(self._call(duration_s=60, handover="transferred")),
                self._row(self._call(duration_s=120)), self._row(self._call(duration_s=180)),
                self._row(self._call(duration_s=0, handover="transferred"))]
        self.assertEqual(calls.stats(rows), {"calls": 4, "handed_over_pct": 50, "avg_length": "1:30"})
        self.assertIsNone(calls.stats([]))


class CallsPageTests(SimpleTestCase):
    def _page(self, rows, **over):
        from types import SimpleNamespace as NS

        from django.template import Context

        from integration import calls

        context = {
            "csrf_token": "x", "integration": NS(pk=7, name="Front desk"), "bound_agent": NS(pk=3),
            "rows": rows, "stats": calls.stats(rows),
            "page": {"page": 2, "has_next": True, "has_prev": True}, **over,
        }
        return _stub_engine().get_template("integrations/calls.html").render(Context(context))

    def _rows(self):
        return [CallRowTests()._row(CallRowTests()._call(handover="transferred"))]

    def test_rows_stats_and_link_to_the_conversation(self):
        rows = self._rows()
        html = self._page(rows)
        for text in ("Handed over", "2:11", "+91xxxxxx3210", "book_appointment", "100%", "Older"):
            self.assertIn(text, html)
        self.assertIn(f"?filter_session_id={rows[0]['session_id']}", html)

    def test_no_calls_and_no_agent_say_what_to_do(self):
        self.assertIn("No calls yet", self._page([]))
        self.assertIn("No agent answers this number yet", self._page([], bound_agent=None))

    def test_the_number_page_has_both_tabs(self):
        html = PhoneNumberPageTests()._page()
        self.assertIn("/calls/", html)
        self.assertNotIn("/calls/", PhoneNumberPageTests()._page(is_phone=False))


class TestCallCardTests(SimpleTestCase):
    def _binding(self, active=True, handover=None):
        from types import SimpleNamespace as NS

        return NS(is_active=active, config={"handover": handover} if handover else {})

    def test_ready_needs_an_agent_and_an_active_connection(self):
        from types import SimpleNamespace as NS

        from integration import test_call

        agent = NS(pk=1)
        self.assertFalse(test_call.ready(test_call.checks(None, None)))
        self.assertFalse(test_call.ready(test_call.checks(self._binding(), None)))
        self.assertFalse(test_call.ready(test_call.checks(self._binding(active=False), agent)))
        self.assertTrue(test_call.ready(test_call.checks(self._binding(), agent)))

    def test_handover_is_optional(self):
        from types import SimpleNamespace as NS

        from integration import test_call

        agent = NS(pk=1)
        self.assertIsNone(test_call.checks(self._binding(), agent)[2][1])
        self.assertIs(test_call.checks(self._binding(handover={"number": "+919999911111"}), agent)[2][1], True)

    def test_rings_the_public_number_when_there_is_one(self):
        from integration import test_call

        self.assertEqual(test_call.number_to_ring({"phone_number": "+918000012345", "public_number": "+919876543210"}), "+919876543210")
        self.assertEqual(test_call.number_to_ring({"phone_number": "+918000012345", "public_number": ""}), "+918000012345")
        self.assertIsNone(test_call.number_to_ring({}))

    def _card(self, ready, number="+918000012345"):
        from types import SimpleNamespace as NS

        from integration import test_call

        rows = test_call.checks(self._binding() if ready else None, NS(pk=1) if ready else None)
        return PhoneNumberPageTests()._page(test_call={"checks": rows, "ready": ready, "number": number})

    def test_card_offers_the_call_only_when_ready(self):
        self.assertIn('href="tel:+918000012345"', self._card(True))
        html = self._card(False)
        self.assertNotIn("tel:", html)
        self.assertIn("An agent is connected", html)
        self.assertIn("cannot check Vobiz", html)

    def test_whatsapp_numbers_have_no_test_card(self):
        self.assertNotIn("Test this number", PhoneNumberPageTests()._page(is_phone=False))
