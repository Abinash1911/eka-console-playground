"""Console pages for a channel integration: the account, and the product bound to it."""

import json
from typing import Optional, get_args

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from agents.models import AgentConfig
from core.constants import Product
from core.logging import get_logger
from console_index import reads as console_reads
from integration import calls as call_rows, test_call, webhooks
from integration.models import Integration, ProductIntegration
from integration.schemas import products as product_configs
from integration.schemas.products.utils import Callback

logger = get_logger(__name__)

# Products with a config schema.
BINDABLE = (Product.AGENT.value, Product.MESSENGER.value)

# Stand-in product_id for products bound once per workspace.
DEFAULT_PRODUCT_ID = "default"

# What a messenger binding is for; stored on ``metadata["usecase"]``.
USECASE_EKA_EMR = "eka_emr"
USECASE_EKASCRIBE = "ekascribe"
MESSENGER_USECASES = (
    (USECASE_EKA_EMR, "Eka EMR"),
    (USECASE_EKASCRIBE, "EkaScribe"),
)
DEFAULT_USECASE = USECASE_EKA_EMR

CALLBACK_LABELS = {
    "messages": "Messages callback",
    "status": "Status callback",
}
CALLBACK_HELP = {
    "messages": "Inbound messages from the user.",
    "status": "Delivery receipts for messages you send.",
}


def _slots(product: str) -> tuple:
    """The callback slots a product's config model declares, in order.

    Only fields that hold a ``Callback``: the config can carry other settings
    (the agent's ``handover``) that this form must neither show as a callback
    box nor overwrite.
    """
    schema = product_configs.config_for(product)
    if schema is None:
        return ()
    return tuple(
        name
        for name, field in schema.model_fields.items()
        if Callback in (field.annotation, *get_args(field.annotation))
    )


def _callback(url: str, headers: Optional[dict] = None) -> Optional[dict]:
    """A callback destination, or None for a blank url (the schema rejects empty urls)."""
    url = (url or "").strip()
    return {"url": url, "headers": headers or {}} if url else None


def _defaults(product: str) -> dict:
    if product == Product.AGENT.value:
        return {"status": _callback(settings.AGENT_STATUS_CALLBACK_URL)}
    if product == Product.MESSENGER.value:
        return {
            "messages": _callback(settings.MESSENGER_MESSAGES_CALLBACK_URL),
            "status": _callback(settings.MESSENGER_STATUS_CALLBACK_URL),
        }
    return {}


def _headers_from_post(request, prefix: str) -> dict:
    """Zip the header repeater's key/value lists; empty rows are dropped, nameless values rejected."""
    keys = request.POST.getlist(f"{prefix}_header_key")
    values = request.POST.getlist(f"{prefix}_header_value")

    headers = {}
    for key, value in zip(keys, values):
        key, value = key.strip(), value.strip()
        if key:
            headers[key] = value
        elif value:
            raise ValueError("a header has a value but no name")
    return headers


def _config_from_post(request, product: str) -> dict:
    # Field names are product-prefixed, so the hidden product's inputs are ignored.
    return {
        slot: _callback(
            request.POST.get(f"{product}_{slot}_url"),
            _headers_from_post(request, f"{product}_{slot}"),
        )
        for slot in _slots(product)
    }


# Returned by _handover_from_post when the form had no handover section at all.
KEEP_HANDOVER = object()

DEFAULT_HANDOVER_TIMEZONE = "Asia/Kolkata"
DEFAULT_RING_SECONDS = 30


def _handover_from_post(request):
    """The handover config the phone form describes, ``None`` to turn it off.

    Returns ``KEEP_HANDOVER`` when the form had no handover section (a WhatsApp
    number's form), so saving that form leaves any stored handover alone.
    Validation is left to the product config schema.
    """
    if not request.POST.get("handover_form"):
        return KEEP_HANDOVER
    if not request.POST.get("handover_enabled"):
        return None

    start = (request.POST.get("handover_start") or "").strip()
    end = (request.POST.get("handover_end") or "").strip()
    if bool(start) != bool(end):
        raise ValueError("Staff hours need both a start and an end, or neither.")

    handover = {
        "number": (request.POST.get("handover_number") or "").strip(),
        "ring_seconds": (request.POST.get("handover_ring_seconds") or "").strip()
        or DEFAULT_RING_SECONDS,
    }
    if start:
        handover["hours"] = {
            "start": start,
            "end": end,
            "timezone": (request.POST.get("handover_timezone") or "").strip()
            or DEFAULT_HANDOVER_TIMEZONE,
        }
    return handover


def _handover_form(binding: Optional[ProductIntegration]) -> dict:
    """What the handover section shows: the stored settings, or empty defaults."""
    stored = ((binding.config or {}).get("handover") if binding else None) or {}
    hours = stored.get("hours") or {}
    return {
        "enabled": bool(stored),
        "number": stored.get("number", ""),
        "start": hours.get("start", ""),
        "end": hours.get("end", ""),
        "timezone": hours.get("timezone", DEFAULT_HANDOVER_TIMEZONE),
        "ring_seconds": stored.get("ring_seconds", DEFAULT_RING_SECONDS),
    }


def _typed_handover(request) -> dict:
    """What was typed in the handover section, to show again beside an error."""
    return {
        "enabled": bool(request.POST.get("handover_enabled")),
        "number": request.POST.get("handover_number", ""),
        "start": request.POST.get("handover_start", ""),
        "end": request.POST.get("handover_end", ""),
        "timezone": request.POST.get("handover_timezone", DEFAULT_HANDOVER_TIMEZONE),
        "ring_seconds": request.POST.get("handover_ring_seconds", DEFAULT_RING_SECONDS),
    }


def _typed_extra(request) -> dict:
    return {"handover": _typed_handover(request)} if request.POST.get("handover_form") else {}


def _callback_blocks(product: str, config: Optional[dict]) -> list:
    """One form block per callback slot, prefilled from ``config``."""
    blocks = []
    for slot in _slots(product):
        destination = (config or {}).get(slot) or {}
        headers = destination.get("headers") or {}
        blocks.append(
            {
                "label": CALLBACK_LABELS.get(slot, f"{slot} callback".capitalize()),
                "help": CALLBACK_HELP.get(slot, ""),
                "url": destination.get("url", ""),
                "url_field": f"{product}_{slot}_url",
                "key_field": f"{product}_{slot}_header_key",
                "value_field": f"{product}_{slot}_header_value",
                "headers_json": json.dumps(
                    [
                        {"key": key, "value": value, "_id": index}
                        for index, (key, value) in enumerate(headers.items())
                    ]
                ),
                # Seeds the Alpine id counter so new rows don't collide.
                "headers_count": len(headers),
            }
        )
    return blocks


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = " ".join(str(part) for part in error["loc"])
    message = error["msg"].removeprefix("Value error, ")
    return f"{where}: {message}" if where else message


def _trigger_emr_templates(
    request, integ: Integration, binding: ProductIntegration
) -> None:
    """Fire-and-forget the EMR templates lambda; a failure is logged, never shown.

    The lambda keys off the caller's JWT ``b-id``, so it gets the request's
    payload in an API Gateway style ``body``.
    """
    jwt_payload = request.user_context
    if not jwt_payload.get("b-id"):
        logger.error(
            "emr_templates_lambda_skipped",
            integration_id=integ.pk,
            binding_uuid=str(binding.uuid),
            error="jwt payload has no b-id",
        )
        return
    payload = {"body": json.dumps({"jwt_payload": jwt_payload})}
    try:
        import boto3

        boto3.client(
            "lambda", region_name=settings.EMR_TEMPLATES_LAMBDA_REGION
        ).invoke(
            FunctionName=settings.EMR_TEMPLATES_LAMBDA,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
    except Exception as exc:
        logger.error(
            "emr_templates_lambda_failed",
            integration_id=integ.pk,
            binding_uuid=str(binding.uuid),
            error=str(exc) or type(exc).__name__,
        )
        return
    logger.info(
        "emr_templates_lambda_invoked",
        integration_id=integ.pk,
        binding_uuid=str(binding.uuid),
    )


def _credential_rows(integ: Integration) -> list:
    """Label/value pairs from ``public_credentials``, so secrets never reach the template."""
    labels = {
        "waba_id": "WABA ID",
        "phone_number_id": "Phone number ID",
        "phone_number": "Phone number",
        "phone_type": "Number type",
        "account_sid": "Account SID",
        "from_number": "Sender",
        "namespace": "Template namespace",
    }
    return [
        (labels.get(key, key.replace("_", " ").capitalize()), value)
        for key, value in integ.public_credentials().items()
        if value
    ]


def _test_call(integ: Integration, binding, agent) -> dict:
    rows = test_call.checks(binding, agent)
    return {
        "checks": rows,
        "ready": test_call.ready(rows),
        "number": test_call.number_to_ring(integ.public_credentials()),
    }


def _binding_context(request, integ: Integration) -> dict:
    binding = ProductIntegration.objects.filter(integration=integ).first()

    bound_agent = None
    if binding and binding.product == Product.AGENT.value:
        bound_agent = AgentConfig.objects.filter(
            agent_id=binding.product_id, workspace_id=request.workspace_id
        ).first()

    # The bound product shows its stored config; the other shows settings defaults.
    callback_blocks = {
        product: _callback_blocks(
            product,
            binding.config
            if binding is not None and binding.product == product
            else _defaults(product),
        )
        for product in BINDABLE
    }

    return {
        "binding": binding,
        "is_phone": integ._channel == Integration.CHANNEL_TELEPHONY,
        "handover": _handover_form(binding),
        "test_call": _test_call(integ, binding, bound_agent),
        "bound_agent": bound_agent,
        "agents": AgentConfig.objects.filter(
            workspace_id=request.workspace_id, is_active=True
        ).order_by("name"),
        "callback_blocks": callback_blocks,
        "messenger_product_id": (
            binding.product_id
            if binding is not None and binding.product == Product.MESSENGER.value
            else DEFAULT_PRODUCT_ID
        ),
        "messenger_usecases": MESSENGER_USECASES,
        "messenger_usecase": (
            (binding.metadata or {}).get("usecase", DEFAULT_USECASE)
            if binding is not None and binding.product == Product.MESSENGER.value
            else DEFAULT_USECASE
        ),
    }


def _render(request, integ: Integration, error: str = "", **extra):
    context = {
        "user_context": request.user_context,
        "current_page": "integrations",
        "integration": integ,
        "credential_rows": _credential_rows(integ),
        # Providers we can't point at doot ourselves; the user pastes this URL.
        "webhook_url": webhooks.inbound_url(integ),
        "webhook_manual": integ.provider not in webhooks.PROGRAMMABLE_PROVIDERS,
        "error": error,
        **_binding_context(request, integ),
        **extra,
    }
    return render(request, "integrations/detail.html", context)


@require_http_methods(["GET"])
def detail(request, pk):
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    return _render(request, integ)


@require_http_methods(["GET"])
def calls(request, pk):
    """Calls answered on a phone number, from the console index."""
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    if integ._channel != Integration.CHANNEL_TELEPHONY:
        raise Http404("Only phone numbers have calls")
    binding = ProductIntegration.objects.filter(
        integration=integ, product=Product.AGENT.value
    ).first()
    agent = (
        AgentConfig.objects.filter(agent_id=binding.product_id, workspace_id=request.workspace_id).first()
        if binding
        else None
    )
    page = {"calls": [], "page": 1, "has_next": False, "has_prev": False}
    if agent:
        page = console_reads.list_calls(agent.agent_id, str(integ.uuid), request.GET.get("page", 1))
    rows = [call_rows.present(s) for s in page["calls"]]
    return render(request, "integrations/calls.html", {
        "user_context": request.user_context,
        "current_page": "integrations",
        "integration": integ,
        "is_phone": True,
        "bound_agent": agent,
        "rows": rows,
        "stats": call_rows.stats(rows),
        "page": page,
    })


@require_http_methods(["POST"])
def bind_product(request, pk):
    """Connect a product, or update the connected one's callbacks.

    Switching to a different product requires Disconnect first, since the
    binding uuid is the caller's handle and must not be repointed.
    """
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)

    product = (request.POST.get("product") or "").strip()
    if product not in BINDABLE:
        return _render(request, integ, error="Pick a product to connect.")

    if integ._channel == Integration.CHANNEL_TELEPHONY and product != Product.AGENT.value:
        return _render(request, integ, error="A phone number connects to an agent.")

    existing = ProductIntegration.objects.filter(integration=integ).first()
    if existing is not None and existing.product != product:
        return _render(
            request,
            integ,
            error=(
                f"This number is connected to {existing.get_product_display()}. "
                f"Disconnect it first — anything sending through it will stop, "
                f"which is the point."
            ),
        )

    if product == Product.AGENT.value:
        agent = AgentConfig.objects.filter(
            pk=request.POST.get("agent"), workspace_id=request.workspace_id
        ).first()
        if agent is None:
            return _render(request, integ, error="Pick an agent to connect.")
        if not agent.agent_id:
            return _render(
                request,
                integ,
                error=f"{agent.name} has no agent ID yet, so it cannot be connected.",
            )
        product_id = agent.agent_id
        usecase = None
    else:
        product_id = (
            request.POST.get("product_id") or ""
        ).strip() or DEFAULT_PRODUCT_ID
        usecase = (request.POST.get("usecase") or "").strip() or DEFAULT_USECASE
        if usecase not in dict(MESSENGER_USECASES):
            return _render(request, integ, error="Pick a usecase.")

    try:
        raw_config = _config_from_post(request, product)
        if product == Product.AGENT.value:
            handover = _handover_from_post(request)
            if handover is KEEP_HANDOVER:
                handover = ((existing.config or {}).get("handover")) if existing else None
            raw_config["handover"] = handover
        config = product_configs.validate(product, raw_config)
    # ValidationError subclasses ValueError, so it must be caught first.
    except ValidationError as exc:
        return _render(request, integ, error=_first_error(exc), **_typed_extra(request))
    except ValueError as exc:
        return _render(request, integ, error=str(exc), **_typed_extra(request))

    if existing is not None:
        binding = existing
        binding.config = config
        update_fields = ["config", "updated_at"]
        if usecase is not None:
            binding.metadata = {**(binding.metadata or {}), "usecase": usecase}
            update_fields.append("metadata")
        binding.save(update_fields=update_fields)
        created = False
    else:
        binding = ProductIntegration.objects.create(
            integration=integ,
            product=product,
            product_id=product_id,
            config=config,
            metadata={"usecase": usecase} if usecase is not None else {},
        )
        created = True

    # Move numbers still on the old agent-scoped webhook to the uuid one; no-op otherwise.
    webhooks.register(integ)

    # EkaScribe has no setup step yet.
    if usecase == USECASE_EKA_EMR:
        _trigger_emr_templates(request, integ, binding)

    logger.info(
        "product_bound_from_console" if created else "product_config_updated",
        integration_id=integ.pk,
        product=product,
        product_id=product_id,
        usecase=usecase,
        workspace_id=request.workspace_id,
    )
    return redirect("agents:integration_detail", pk=integ.pk)


@require_http_methods(["POST"])
def toggle_product(request, pk):
    """Pause or resume the binding; unlike Disconnect, the uuid survives."""
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    binding = ProductIntegration.objects.filter(integration=integ).first()
    if binding is None:
        return _render(request, integ, error="Nothing is connected to this number.")

    binding.is_active = (request.POST.get("state") or "") == "enable"
    binding.save(update_fields=["is_active", "updated_at"])
    logger.info(
        "product_binding_enabled" if binding.is_active else "product_binding_disabled",
        integration_id=integ.pk,
        binding_uuid=str(binding.uuid),
    )
    return redirect("agents:integration_detail", pk=integ.pk)


@require_http_methods(["POST"])
def unbind_product(request, pk):
    """Disconnect: deletes the binding and invalidates its uuid."""
    integ = get_object_or_404(Integration, pk=pk, workspace_id=request.workspace_id)
    deleted, _ = ProductIntegration.objects.filter(integration=integ).delete()
    logger.info(
        "product_unbound_from_console", integration_id=integ.pk, removed=deleted
    )
    return redirect("agents:integration_detail", pk=integ.pk)
