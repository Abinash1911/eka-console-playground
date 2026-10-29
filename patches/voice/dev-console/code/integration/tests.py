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
