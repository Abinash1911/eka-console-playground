import hmac
import json

from django.conf import settings
from django.db import IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from ..models import AgentConfig, Integration, AgentIntegration, WABAOnboarding
from core.logging import get_logger
from pydantic import ValidationError
from integration import templates as template_client
from integration import webhooks as integration_webhooks
from integration.api.crud import parse_body
from integration.constants import CHANNEL_TELEPHONY
from integration.schemas.templates import CreateTemplateRequest, TemplateSendRequest, variable_slots
from ..services.credential_verifier import (
    verify_interakt_credentials,
    verify_turn_io_credentials,
    verify_netcore_credentials,
)

logger = get_logger(__name__)

# Providers whose numbers live on a WABA we can read directly from Meta Graph.
# interakt_tp numbers are onboarded via Embedded Signup, so Meta is still the
# source of truth for their status even though messaging routes through Interakt.
META_BACKED_PROVIDERS = ("interakt_tp", "meta")

# A phone number patients dial (Vobiz); it has its own form, not the WhatsApp credential one.
PHONE_PROVIDER = "vobiz"


def _credential_error(request, provider, error_message):
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": False, "error": error_message}, status=400)
    return render(
        request,
        "integrations/create_phone.html" if provider == PHONE_PROVIDER else "integrations/create_form.html",
        {
            "user_context": request.user_context,
            "current_page": "integrations",
            "provider": provider,
            "error": error_message,
            # What was typed, so a mistake does not mean starting over (never credentials).
            "form": (
                {key: request.POST.get(key, "") for key in ("name", "phone_number", "public_number")}
                if provider == PHONE_PROVIDER
                else {}
            ),
        },
    )


def _first_validation_error(exc: ValidationError) -> str:
    """The first problem in a pydantic error, in words a person can act on."""
    error = exc.errors()[0]
    field = str(error["loc"][0]).replace("_", " ") if error["loc"] else ""
    message = error["msg"].removeprefix("Value error, ")
    return f"{field}: {message}" if field else message


@require_http_methods(["GET"])
def integration_list(request):
    integrations = list(Integration.objects.filter(workspace_id=request.workspace_id))

    # Mark which rows should fetch live status from Meta. Decrypting credentials
    # here (rather than in the template) keeps the check to one pass and lets the
    # row stay quiet when the number ID is missing — e.g. a name-only WABA that
    # never got a real number.
    for integ in integrations:
        integ.has_meta_number = (
            integ.provider in META_BACKED_PROVIDERS
            and bool(integ.get_credentials().get("phone_number_id"))
        )

    return render(
        request,
        "integrations/list.html",
        {
            "user_context": request.user_context,
            "current_page": "integrations",
            "integrations": integrations,
        },
    )


@require_http_methods(["GET"])
def integration_number_status(request, pk):
    """
    Live WhatsApp number status read straight from Meta.

    Fetched lazily per row by the integrations list so a slow or failing Graph
    call never blocks the page, and only on page load — no polling.
    """
    from ..services.meta_graph import MetaGraphError, fetch_number_status

    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    creds = integ.get_credentials()

    if integ.provider not in META_BACKED_PROVIDERS:
        return JsonResponse(
            {"success": False, "error": "Not a Meta-backed integration."}, status=400
        )

    try:
        status = fetch_number_status(
            phone_number_id=creds.get("phone_number_id", ""),
            access_token=creds.get("access_token", ""),
        )
    except MetaGraphError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=502)

    return JsonResponse({"success": True, "status": status})


@require_http_methods(["GET", "POST"])
def integration_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        provider = request.POST.get("provider", "").strip()
        integration_type = request.POST.get("integration_type", "whatsapp").strip()

        if not name or not provider:
            if request.headers.get("HX-Request"):
                return JsonResponse(
                    {"success": False, "error": "Name and provider are required"},
                    status=400,
                )
            return render(
                request,
                "integrations/create_form.html",
                {
                    "user_context": request.user_context,
                    "current_page": "integrations",
                    "provider": provider,
                    "error": "Name and provider are required",
                },
            )

        if provider == "interakt":
            api_key = request.POST.get("api_key", "").strip()
            ok, err = verify_interakt_credentials(api_key)
            if not ok:
                return _credential_error(request, provider, err)
            credentials = {
                "api_key": api_key,
                "webhook_secret": request.POST.get("webhook_secret", "").strip(),
            }
        elif provider == "turn_io":
            bearer_token = request.POST.get("bearer_token", "").strip()
            ok, err = verify_turn_io_credentials(bearer_token)
            if not ok:
                return _credential_error(request, provider, err)
            credentials = {
                "bearer_token": bearer_token,
                "webhook_secret": request.POST.get("webhook_secret", "").strip(),
                # WABA template namespace — optional, required only to send templates
                # via Doot (Turn's On-Premise /v1/messages needs template.namespace).
                "namespace": request.POST.get("namespace", "").strip(),
            }
        elif provider == "netcore":
            bearer_token = request.POST.get("bearer_token", "").strip()
            ok, err = verify_netcore_credentials(bearer_token)
            if not ok:
                return _credential_error(request, provider, err)
            credentials = {
                "bearer_token": bearer_token,
                "webhook_secret": request.POST.get("webhook_secret", "").strip(),
            }
        elif provider == PHONE_PROVIDER:
            integration_type = CHANNEL_TELEPHONY
            credentials = {
                "phone_number": request.POST.get("phone_number", "").strip(),
                "public_number": request.POST.get("public_number", "").strip(),
            }
        else:
            if request.headers.get("HX-Request"):
                return JsonResponse(
                    {"success": False, "error": "Unsupported provider"}, status=400
                )
            return redirect("agents:integration_list")

        integ = Integration(
            workspace_id=request.workspace_id,
            name=name,
            integration_type=integration_type,
            provider=provider,
        )
        try:
            # Validates the blob against the provider's schema (a phone number must be E.164).
            integ.set_credentials(credentials)
            integ.save()
        except ValidationError as exc:
            return _credential_error(request, provider, _first_validation_error(exc))
        except IntegrityError:
            return _credential_error(
                request,
                provider,
                "This number is already registered in your workspace (it may have been deleted earlier).",
            )

        if request.headers.get("HX-Request"):
            return JsonResponse({"success": True, "id": integ.id})
        return redirect("agents:integration_detail", pk=integ.id)

    # GET — show provider picker or credential form if ?provider= is set
    provider = request.GET.get("provider", "")
    if provider == PHONE_PROVIDER:
        return render(
            request,
            "integrations/create_phone.html",
            {
                "user_context": request.user_context,
                "current_page": "integrations",
                "provider": provider,
            },
        )
    if provider in ("interakt", "turn_io", "netcore"):
        return render(
            request,
            "integrations/create_form.html",
            {
                "user_context": request.user_context,
                "current_page": "integrations",
                "provider": provider,
            },
        )
    return render(
        request,
        "integrations/create.html",
        {
            "user_context": request.user_context,
            "current_page": "integrations",
        },
    )


def _doot_message_webhook_url(agent_id: str) -> str:
    """Doot's agent-scoped inbound-message webhook for a linked agent."""
    base = getattr(settings, "DOOT_WEBHOOK_BASE_URL", "").rstrip("/")
    return f"{base}/wh/medassist?agent_id={agent_id}"


@require_http_methods(["GET"])
def integration_detail(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    linked = AgentIntegration.objects.filter(integration=integ).select_related("agent").first()
    agents = AgentConfig.objects.filter(workspace_id=request.workspace_id, is_active=True).order_by("name")

    webhook_url = None
    if linked and linked.agent.agent_id and integ.integration_type == "whatsapp":
        webhook_url = _doot_message_webhook_url(linked.agent.agent_id)

    return render(
        request,
        "integrations/detail.html",
        {
            "user_context": request.user_context,
            "current_page": "integrations",
            "integration": integ,
            "linked_agent_rel": linked,
            "available_agents": agents,
            "webhook_url": webhook_url,
        },
    )


@require_http_methods(["POST"])
def link_agent(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    agent_id = request.POST.get("agent_id")
    agent = get_object_or_404(AgentConfig, pk=agent_id, workspace_id=request.workspace_id)
    AgentIntegration.objects.update_or_create(agent=agent, defaults={"integration": integ})

    # For interakt_tp, now that an agent is attached, point this number's incoming
    # WhatsApp messages at Doot's agent-scoped webhook via Interakt's override API.
    if integ.provider == "interakt_tp" and agent.agent_id:
        from agents.services.interakt_tp import configure_interakt_webhook
        creds = integ.get_credentials()
        configure_interakt_webhook(
            phone_number_id=creds.get("phone_number_id", ""),
            waba_id=creds.get("waba_id", ""),
            callback_uri=_doot_message_webhook_url(agent.agent_id),
            verify_token=settings.WHATSAPP_VERIFY_TOKEN,
        )
    return redirect("agents:integration_detail", pk=pk)


@require_http_methods(["POST"])
def unlink_agent(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    AgentIntegration.objects.filter(integration=integ).delete()
    return redirect("agents:integration_detail", pk=pk)


@require_http_methods(["POST"])
def integration_update(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    name = request.POST.get("name", "").strip()
    if name:
        integ.name = name
        integ.save(update_fields=["name", "updated_at"])
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True})
    return redirect("agents:integration_detail", pk=integ.id)


def _save_consent_pdf(workspace_id, agent_pk, file):
    """Store a consent PDF in the public bucket and return its permanent URL.

    Public + unsigned (cdn.eka.care, querystring_auth off) is a requirement, not a
    convenience: WhatsApp fetches the document header itself, so a presigned or
    expiring URL would break the consent message as soon as it lapsed.
    """
    from django.core.files.storage import storages

    storage = storages["public_media"]
    path = f"{workspace_id}/agents/consent/{agent_pk}/{file.name}"
    return storage.url(storage.save(path, file))


@require_http_methods(["POST"])
def consent_update(request, pk):
    """Save the first-time consent settings for the agent linked to this integration."""
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    rel = (
        AgentIntegration.objects.filter(integration=integ)
        .select_related("agent")
        .first()
    )
    if not rel:
        return redirect("agents:integration_detail", pk=pk)

    template = dict(rel.consent_template or {})
    template["text"] = request.POST.get("consent_text", "").strip()
    # Approved WhatsApp template sent on first contact (PDF header + Agree button).
    # doot sends this once, then falls back to plain Yes/No reminders.
    template["template_name"] = request.POST.get("consent_template_name", "").strip()
    template["language"] = request.POST.get("consent_language", "").strip()
    footer = request.POST.get("consent_footer", "").strip()
    decline = request.POST.get("consent_decline_text", "").strip()
    template["footer"] = footer
    template["decline_text"] = decline

    accept_label = request.POST.get("consent_accept_label", "").strip() or "Yes, I agree"
    decline_label = request.POST.get("consent_decline_label", "").strip() or "I disagree"
    template["suggestions"] = [
        {"label": accept_label, "value": "agree", "action": "accept"},
        {"label": decline_label, "value": "disagree", "action": "decline"},
    ]

    # Document: an uploaded PDF wins over a pasted URL; "remove" clears both.
    upload = request.FILES.get("consent_pdf")
    pasted_url = request.POST.get("consent_pdf_url", "").strip()
    if request.POST.get("consent_pdf_remove"):
        template.pop("document", None)
    elif upload:
        template["document"] = {
            "link": _save_consent_pdf(request.workspace_id, rel.agent.pk, upload),
            "filename": upload.name,
        }
    elif pasted_url:
        # WhatsApp fetches this itself, so anything but a plain https URL is useless.
        # Ignore a bad one rather than discard the rest of the form (the input also
        # carries an https-only pattern, so this is the backstop).
        if pasted_url.startswith("https://"):
            document = dict(template.get("document") or {})
            document["link"] = pasted_url
            document.setdefault("filename", pasted_url.rsplit("/", 1)[-1] or "Consent.pdf")
            template["document"] = document
        else:
            logger.warning("consent_pdf_url_rejected", pk=pk, url=pasted_url[:80])

    filename = request.POST.get("consent_pdf_filename", "").strip()
    if filename and template.get("document"):
        template["document"]["filename"] = filename

    rel.consent_req = bool(request.POST.get("consent_req"))
    rel.consent_version = request.POST.get("consent_version", "").strip()
    rel.consent_template = {k: v for k, v in template.items() if v}
    rel.save(update_fields=[
        "consent_req", "consent_version", "consent_template", "updated_at",
    ])

    logger.info(
        "consent_config_saved",
        integration=pk,
        agent=rel.agent.pk,
        required=rel.consent_req,
        version=rel.consent_version,
        has_doc=bool(rel.consent_template.get("document")),
    )
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True})
    return redirect("agents:integration_detail", pk=pk)


@require_http_methods(["POST"])
def integration_delete(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    AgentIntegration.objects.filter(integration=integ).delete()
    integ.delete()
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True})
    return redirect("agents:integration_list")


@require_http_methods(["POST"])
def connect_integration(request, pk):
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)
    integration_id = request.POST.get("integration_id")
    integ = get_object_or_404(
        Integration, pk=integration_id, workspace_id=request.workspace_id
    )
    AgentIntegration.objects.update_or_create(
        agent=agent, defaults={"integration": integ}
    )
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True})
    return redirect("agents:detail", pk=pk)


@require_http_methods(["POST"])
def disconnect_integration(request, pk):
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)
    AgentIntegration.objects.filter(agent=agent).delete()
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True})
    return redirect("agents:detail", pk=pk)


@require_http_methods(["GET"])
def his_emr_page(request):
    return render(
        request,
        "integrations/his_emr.html",
        {
            "user_context": request.user_context,
            "current_page": "his_emr",
        },
    )


# ---------------------------------------------------------------------------
# WhatsApp Embedded Signup + Interakt Tech Partner onboarding
# ---------------------------------------------------------------------------

@ensure_csrf_cookie
@require_http_methods(["GET"])
def whatsapp_onboard_page(request):
    return render(request, "integrations/whatsapp_onboard.html", {
        "user_context": request.user_context,
        "current_page": "integrations",
        "meta_app_id":      settings.META_APP_ID,
        "meta_config_id":   settings.META_CONFIG_ID,
        "meta_solution_id": settings.INTERAKT_SOLUTION_ID,
    })


@require_http_methods(["POST"])
def initiate_whatsapp_onboard(request):
    """
    Receives the auth code from Meta's Embedded Signup JS callback.
    Exchanges it with Meta, creates a WABAOnboarding record, then calls
    Interakt tp-signup. The WABA_ONBOARDED webhook (async) finalises the flow.
    """
    from agents.services.interakt_tp import exchange_meta_code, call_interakt_tp_signup

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    auth_code = body.get("code", "").strip()
    if not auth_code:
        return JsonResponse({"success": False, "error": "Missing auth code"}, status=400)

    # Meta's own WA_EMBEDDED_SIGNUP session info, forwarded by the popup handler.
    # Authoritative about which WABA/number was just created — the token's view is not.
    client_waba_id         = str(body.get("waba_id") or "").strip()
    client_phone_number_id = str(body.get("phone_number_id") or "").strip()

    # Step 1: exchange code with Meta
    try:
        meta_data = exchange_meta_code(
            auth_code,
            client_waba_id=client_waba_id,
            client_phone_number_id=client_phone_number_id,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    waba_id         = meta_data["waba_id"]
    phone_number_id = meta_data["phone_number_id"]

    # Step 2: only treat as "already connected" if this number is onboarded in
    # THIS workspace AND its integration still exists (not soft-deleted). Otherwise
    # fall through and onboard fresh — so a deleted/other-workspace integration
    # never blocks re-onboarding or links to a dead (404) integration.
    existing = WABAOnboarding.objects.filter(
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        status=WABAOnboarding.STATUS_ONBOARDED,
        workspace_id=request.workspace_id,
        integration__is_active=True,
    ).first()
    if existing and existing.integration_id:
        return JsonResponse({
            "success":        True,
            "already_exists": True,
            "integration_id": existing.integration_id,
        })

    # Step 3: determine if this is an additional number on an existing WABA
    waba_already_onboarded = WABAOnboarding.objects.filter(
        waba_id=waba_id,
        status=WABAOnboarding.STATUS_ONBOARDED,
    ).exists()

    # Step 4: create WABAOnboarding record
    onboarding = WABAOnboarding(
        workspace_id    = request.workspace_id,
        waba_id         = waba_id,
        phone_number_id = phone_number_id,
        phone_number    = meta_data["phone_number"],
        phone_type      = meta_data["phone_type"],
        status          = WABAOnboarding.STATUS_PENDING,
    )
    onboarding.set_access_token(meta_data["access_token"])
    onboarding.save()

    # Step 5: call Interakt tp-signup
    # Pin the specific E.164 number only when adding another number to an
    # already-onboarded WABA; first-time onboarding registers the whole WABA.
    tp_phone_number = meta_data["phone_number"] if waba_already_onboarded else ""

    # A WABA can expose more than one ID, and Interakt validates against exactly
    # one of them. We lead with our best guess, then fall back to the token's
    # other candidates rather than stranding the customer in `failed` — the calls
    # are idempotent per WABA, so a wrong candidate just errors and we move on.
    attempts = [waba_id] + [c for c in meta_data["waba_id_candidates"] if c != waba_id]
    last_error = None
    signed_up = False
    for candidate in attempts:
        try:
            call_interakt_tp_signup(candidate, phone_number=tp_phone_number)
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "interakt_tp_signup_candidate_rejected",
                waba_id=candidate,
                onboarding_id=onboarding.pk,
                error=str(exc),
            )
            # Only a 4xx means "Interakt doesn't know this handle". On a 5xx the
            # handle may well be right, and trying the next candidate would
            # register a WABA the customer never chose — so give up instead.
            status = getattr(exc, "status_code", 0)
            if status and not 400 <= status < 500:
                break
            continue

        signed_up = True
        if candidate != waba_id:
            # Interakt accepted a different handle — make it the one we store, so
            # template and send calls key off the same ID their side registered.
            logger.warning(
                "waba_id_corrected_by_tp_signup",
                # not `from=` — reserved word; the pair reads fine as old/new
                old_waba_id=waba_id,
                new_waba_id=candidate,
                onboarding_id=onboarding.pk,
            )
            waba_id = candidate
            onboarding.waba_id = candidate
            onboarding.save(update_fields=["waba_id", "updated_at"])
        break

    if not signed_up:
        onboarding.status = WABAOnboarding.STATUS_FAILED
        onboarding.error_detail = str(last_error)
        onboarding.save(update_fields=["status", "error_detail", "updated_at"])
        return JsonResponse({"success": False, "error": str(last_error)}, status=400)

    logger.info(
        "waba_onboarding_initiated",
        workspace=request.workspace_id,
        waba_id=waba_id,
        candidates=meta_data["waba_id_candidates"],
        onboarding_id=onboarding.pk,
    )
    return JsonResponse({
        "success":       True,
        "onboarding_id": onboarding.pk,
        "status":        "pending",
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def interakt_waba_webhook(request):
    """
    Interakt fires WABA_ONBOARDED to this endpoint after their side of the
    onboarding is complete. Publicly accessible; authenticated via the
    `isv_name_token` field Interakt includes in the POST body.

    GET: Meta-style verification handshake — echo hub.challenge (checking
    hub.verify_token when WABA_WEBHOOK_VERIFY_TOKEN is configured) so the URL
    can be registered with Interakt/Meta.
    """

    # Verification handshake (GET) — echo the challenge to prove URL ownership.
    if request.method == "GET":
        mode      = request.GET.get("hub.mode")
        challenge = request.GET.get("hub.challenge", "")
        token     = request.GET.get("hub.verify_token", "")
        expected_token = getattr(settings, "WABA_WEBHOOK_VERIFY_TOKEN", "")
        if mode == "subscribe" and (not expected_token or token == expected_token):
            return HttpResponse(challenge, content_type="text/plain")
        logger.warning(
            "interakt_webhook_verify_failed",
            mode=mode,
            token_ok=token == expected_token,
        )
        return HttpResponse("Verification failed", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Interakt authenticates the callback with an `isv_name_token` in the request
    # body (there is no signature header). It's the same value as our ISV token.
    expected_token = settings.INTERAKT_ISV_TOKEN
    received_token = payload.get("isv_name_token", "")
    if expected_token:
        if not hmac.compare_digest(received_token, expected_token):
            logger.warning("interakt_webhook_invalid_isv_token")
            return JsonResponse({"error": "Invalid token"}, status=401)
    else:
        # Not configured — accept but flag, so onboarding isn't blocked.
        logger.warning("interakt_webhook_isv_token_not_configured")

    if payload.get("event") != "WABA_ONBOARDED":
        return JsonResponse({"status": "ignored"})

    waba_id         = payload.get("waba_id", "")
    phone_number_id = payload.get("phone_number_id", "")
    phone_number    = payload.get("phone_number", "")

    # Find matching pending onboarding record
    onboarding = (
        WABAOnboarding.objects
        .filter(waba_id=waba_id)
        .exclude(status=WABAOnboarding.STATUS_ONBOARDED)
        .order_by("-created_at")
        .first()
    )

    if onboarding and onboarding.status == WABAOnboarding.STATUS_ONBOARDED:
        return JsonResponse({"status": "already_onboarded"})

    workspace_id = onboarding.workspace_id if onboarding else ""
    if not workspace_id:
        logger.warning("interakt_webhook_no_pending_record", waba_id=waba_id)

    # The WABA_ONBOARDED payload usually omits phone_number — fall back to the
    # E.164 number captured from Meta at onboarding time so the UI shows the number.
    if not phone_number and onboarding:
        phone_number = onboarding.phone_number

    credentials = {
        "waba_id":         waba_id,
        "phone_number_id": phone_number_id,
        "phone_number":    phone_number,
        "phone_type":      onboarding.phone_type if onboarding else "real",
        "access_token":    onboarding.get_access_token() if onboarding else "",
    }

    integ = Integration(
        workspace_id     = workspace_id,
        name             = f"WhatsApp ({phone_number or waba_id})",
        integration_type = "whatsapp",
        provider         = "interakt_tp",
    )
    integ.set_credentials(credentials)
    integ.save()

    if onboarding:
        onboarding.status      = WABAOnboarding.STATUS_ONBOARDED
        onboarding.integration = integ
        if phone_number_id:
            onboarding.phone_number_id = phone_number_id
        if phone_number:
            onboarding.phone_number = phone_number
        onboarding.save(update_fields=[
            "status", "integration", "phone_number_id", "phone_number", "updated_at",
        ])

    # The webhook URL is keyed on integration.uuid, so it can be registered at onboarding.
    integration_webhooks.register(integ)

    logger.info(
        "waba_onboarded",
        waba_id=waba_id,
        integration_id=integ.pk,
        workspace_id=workspace_id,
    )
    return JsonResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# WhatsApp Template Management (interakt_tp integrations)
# ---------------------------------------------------------------------------

INTERAKT_AMPED = "https://amped-express.interakt.ai/api/v17.0"


def _interakt_headers(waba_id):
    return {
        "x-access-token": settings.INTERAKT_ISV_TOKEN,
        "x-waba-id":      waba_id,
        "Content-Type":   "application/json",
    }


@require_http_methods(["GET"])
def integration_templates(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    waba_id = integ.get_credentials().get("waba_id", "")

    templates = []
    error = None
    try:
        templates = template_client.list_templates(waba_id)
    except template_client.TemplateError as exc:
        error = exc.message
    # What each template's Send modal asks for: header/body values and dynamic buttons.
    for t in templates:
        t["slots_json"] = json.dumps(variable_slots(t))

    return render(request, "integrations/templates.html", {
        "user_context":  request.user_context,
        "current_page":  "integrations",
        "integration":   integ,
        "templates":     templates,
        "error":         error,
        "LANGUAGE_CHOICES": [
            ("en",    "English"),
            ("en_US", "English (US)"),
            ("en_GB", "English (UK)"),
            ("hi",    "Hindi"),
            ("mr",    "Marathi"),
        ],
        "CATEGORY_CHOICES": [
            ("UTILITY",        "Utility"),
            ("MARKETING",      "Marketing"),
            ("AUTHENTICATION", "Authentication"),
        ],
    })


@require_http_methods(["POST"])
def integration_template_media(request, pk):
    """Upload the create form's media header sample; returns Meta's header_handle."""
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"success": False, "error": "Choose a sample file for the header."}, status=400)
    try:
        handle = template_client.upload_sample(integ.get_credentials().get("waba_id", ""), upload)
    except template_client.TemplateError as exc:
        return JsonResponse({"success": False, "error": exc.message}, status=400)
    return JsonResponse({"success": True, "header_handle": handle})


@require_http_methods(["POST"])
@parse_body(CreateTemplateRequest)
def integration_create_template(request, body, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    waba_id = integ.get_credentials().get("waba_id", "")
    try:
        created = template_client.create_template(waba_id, body.model_dump())
    except template_client.TemplateError as exc:
        return JsonResponse({"success": False, "error": exc.message}, status=400)
    logger.info("template_created", waba_id=waba_id, name=body.name, language=body.language)
    return JsonResponse({"success": True, "id": created.get("id"), "status": created.get("status", "PENDING")})


@require_http_methods(["POST"])
@parse_body(TemplateSendRequest)
def integration_send_message(request, body, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    creds = integ.get_credentials()
    phone_number_id = creds.get("phone_number_id", "")
    waba_id         = creds.get("waba_id", "")

    template_obj = {"name": body.template_name, "language": {"code": body.language_code}}
    # Every header/body variable and dynamic button needs a value, else Meta
    # returns "(#132000) Number of parameters does not match".
    components = body.components()
    if components:
        template_obj["components"] = components

    import requests as req
    url     = f"{INTERAKT_AMPED}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                body.to,
        "type":              "template",
        "template":          template_obj,
    }
    resp = req.post(url, headers=_interakt_headers(waba_id), json=payload, timeout=15)
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {}

    if not resp.ok:
        msg = data.get("error", {}).get("message", "") or resp.text[:200] or f"Send failed (HTTP {resp.status_code})."
        logger.error(
            "interakt_send_failed",
            status=resp.status_code,
            body=resp.text[:300],
            waba=waba_id,
            phone=phone_number_id,
        )
        return JsonResponse({"success": False, "error": msg}, status=400)

    return JsonResponse({"success": True, "message_id": data.get("messages", [{}])[0].get("id", "")})


def _positional(values):
    """``["a", "b"]`` -> ``{"var1": "a", "var2": "b"}``; Doot maps varN to {{N}}."""
    return {f"var{i}": value for i, value in enumerate(values, 1)}


@require_http_methods(["POST"])
@parse_body(TemplateSendRequest)
def integration_send_via_doot(request, body, pk):
    """Send a template through the Doot wrapper (POST /send/template).

    Unlike integration_send_message (which calls Meta/Interakt directly), this
    routes through Doot's provider-agnostic, idempotent send — the same path
    the WhatsApp scheduler uses in production. The provider is the source of truth:
    the template name is sent as-is and header/body values as var1..varN, which
    Doot maps to {{1}},{{2}},...
    """
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)

    # Doot keys on agent_id; resolve the agent linked to this integration.
    link = integ.agent_links.select_related("agent").first()
    if not link or not link.agent or not link.agent.agent_id:
        return JsonResponse({
            "success": False,
            "error": "No agent is linked to this integration. Link an agent before testing via Doot.",
        }, status=400)
    agent_id = link.agent.agent_id

    import time
    import requests as req

    # Internal host (e.g. doot.orbi.orbi), NOT the public webhook base.
    base = getattr(settings, "DOOT_INTERNAL_URL", "").rstrip("/")
    if not base:
        return JsonResponse({"success": False, "error": "DOOT_INTERNAL_URL is not configured."}, status=500)

    # Unique per click; no phone number (the key is logged downstream).
    idem = f"console-test#{pk}#{body.template_name}#{int(time.time() * 1000)}"
    # Internal, network-trusted call (same convention as doot -> dev-console
    # integration fetch): a plain, direct request with no app-level auth header.
    headers = {"Content-Type": "application/json"}

    payload = {
        "agent_id":        agent_id,
        "to":              body.to,
        "template_id":     body.template_name,
        "language":        body.language_code,
        "template_params": _positional(body.params),
        "header_params":   _positional(body.header_params),
        "button_params":   [b.model_dump() for b in body.button_params],
        "header_media":    body.header_media.model_dump(exclude_none=True) if body.header_media else None,
        "idempotency_key": idem,
        "meta":            {"source": "console-test", "integration_pk": pk},
    }

    try:
        resp = req.post(f"{base}/send/template", headers=headers, json=payload, timeout=20)
    except Exception:
        logger.exception("doot_send_unreachable", pk=pk)
        return JsonResponse({"success": False, "error": "Could not reach Doot."}, status=502)

    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {}

    if not resp.ok or not data.get("sent"):
        reason = data.get("reason")
        if reason and data.get("detail"):
            reason = f"{reason} — {data['detail']}"
        reason = reason or resp.text[:200] or f"Send failed (HTTP {resp.status_code})."
        logger.error("doot_send_failed", pk=pk, status=resp.status_code, reason=reason)
        return JsonResponse({"success": False, "error": f"Doot: {reason}"}, status=400)

    return JsonResponse({
        "success":    True,
        "message_id": data.get("provider_message_id", ""),
        "provider":   data.get("provider", ""),
        "via":        "doot",
    })
