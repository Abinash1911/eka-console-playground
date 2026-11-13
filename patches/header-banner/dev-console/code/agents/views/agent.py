import base64
import json
import random
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.utils.text import slugify
from django.db.models import Q

from ..models import (
    AgentConfig,
    AgentKnowledgeBase,
    AgentTool,
    AgentVoiceConfig,
    FavouriteVoice,
    KnowledgeBase,
    NudgeCache,
    Integration,
    AgentIntegration,
    Tool,
    LLMModel,
    AgentLLM,
)
from agents.services.banner import clean_banner
from services.langfuse_service import create_or_update_prompt, get_prompt_versions
from core.logging import get_logger
from core.region import current_region
from ._utils import (
    _render_create_error,
    _prompt_id,
    _save_theme_image,
    _validate_theme_image_url,
    _get_available_llms,
    _serialize_agent_tool,
    _serialize_agent_llm,
)

logger = get_logger(__name__)

# WhatsApp coexistence: how long the bot stays quiet after the clinic replies
# from its phone. Minutes in the UI, seconds on the model; never over 2 hrs.
COEX_PAUSE_MIN_MINUTES = 15
COEX_PAUSE_MAX_MINUTES = 120


def _coexistence_pause_seconds(raw_minutes) -> int:
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError):
        minutes = COEX_PAUSE_MAX_MINUTES
    return max(COEX_PAUSE_MIN_MINUTES, min(COEX_PAUSE_MAX_MINUTES, minutes)) * 60


def agent_list(request):
    """Agents list page backed by AgentConfig table"""
    qs = AgentConfig.objects.filter(workspace_id=request.workspace_id)

    agents = []
    for cfg in qs.order_by("-updated_at"):
        agents.append(
            {
                "id": cfg.id,
                "name": cfg.name or cfg.alias,
                "alias": cfg.alias,
                "icon_url": (cfg.theme or {}).get("icon_img", ""),
                "date_created": cfg.created_at.isoformat() if cfg.created_at else None,
                "last_updated": cfg.updated_at.isoformat() if cfg.updated_at else None,
                "is_configurable": cfg.is_configurable,
            }
        )

    table_columns = [
        {"label": "Agents", "field": "name", "type": "avatar_text", "width": "w-1/4"},
        {
            "label": "Date created",
            "field": "date_created",
            "type": "text",
            "width": "w-1/4",
        },
        {
            "label": "Last updated",
            "field": "last_updated",
            "type": "text",
            "width": "w-1/4",
        },
        {"label": "Tools", "field": "tools", "type": "badges", "width": "w-1/5"},
    ]

    context = {
        "user_context": request.user_context,
        "current_page": "agents",
        "agents": agents,
        "table_columns": table_columns,
    }
    return render(request, "agents/list.html", context)


def detail(request, pk):
    """Agent detail/configuration page — loads only minimal data on first render.
    Tab-specific data (Langfuse prompts, KB, tools, LLM, voice) is fetched lazily
    via the tab_data_* endpoints when each tab is first clicked.
    """
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)

    # Parse initial_message to get first message text and quick replies (General tab — free)
    initial_message = agent.initial_message or {}
    first_message_text = initial_message.get("text", "")
    suggestions = initial_message.get("suggestions") or []
    quick_replies = []
    for s in suggestions:
        if isinstance(s, str):
            if s:
                quick_replies.append({"label": s, "value": s})
        elif isinstance(s, dict):
            label = str(s.get("label", "") or s.get("value", "")).strip()
            value = str(s.get("value", "") or label).strip()
            if label:
                quick_replies.append({"label": label, "value": value})

    # Voice enabled flag — just a dict access on model field (free)
    voice_enabled = "voice" in (agent.allowed or [])

    # Widget embed code context (template partial handles the HTML layout)
    widget_agent_display = ""
    if agent.agent_id:
        widget_agent_display = agent.name or agent.alias

    session_context_str = ""
    context_pairs = []
    override_icon_url = ""
    if agent.playground_session_context:
        if isinstance(agent.playground_session_context, dict):
            if "context" in agent.playground_session_context or "override_icon_url" in agent.playground_session_context:
                ctx_data = agent.playground_session_context.get("context") or {}
                override_icon_url = agent.playground_session_context.get("override_icon_url", "")
                if isinstance(ctx_data, dict):
                    for k, v in ctx_data.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        context_pairs.append({"key": k, "value": val_str})
                    session_context_str = json.dumps(ctx_data)
            elif "context_key" in agent.playground_session_context:
                context_key = agent.playground_session_context.get("context_key", "")
                context_value = agent.playground_session_context.get("context_value", "")
                override_icon_url = agent.playground_session_context.get("override_icon_url", "")
                if context_key:
                    context_pairs.append({"key": context_key, "value": context_value})
                    session_context_str = json.dumps({context_key: context_value})
            else:
                for k, v in agent.playground_session_context.items():
                    val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    context_pairs.append({"key": k, "value": val_str})
                session_context_str = json.dumps(agent.playground_session_context)

    # Convert idle_session_expiry (seconds) → minutes for the UI; default 30 mins
    _idle_secs = agent.idle_session_expiry
    idle_expiry_minutes = (_idle_secs // 60) if _idle_secs else 30

    _pause_secs = agent.coexistence_pause_seconds
    coexistence_pause_minutes = (_pause_secs // 60) if _pause_secs else COEX_PAUSE_MAX_MINUTES

    # BYOA: active shared secrets in this workspace, for the attach picker
    from byoa.models import ByoaCredential
    shared_secrets = ByoaCredential.objects.filter(
        workspace_id=request.workspace_id,
        secret_type=ByoaCredential.SECRET_TYPE_BYOA,
        is_active=True,
    ).order_by("-created_at")

    context = {
        "user_context": request.user_context,
        "current_page": "agents",
        "agent": agent,
        "is_configurable": agent.is_configurable,
        "first_message_text": first_message_text,
        "quick_replies": quick_replies,
        "widget_agent_display": widget_agent_display,
        "session_context_str": session_context_str,
        "context_pairs": context_pairs,
        "override_icon_url": override_icon_url,
        "voice_enabled": voice_enabled,
        "idle_expiry_minutes": idle_expiry_minutes,
        "coexistence_pause_minutes": coexistence_pause_minutes,
        "shared_secrets": shared_secrets,
        "feedback_config_json": json.dumps(agent.feedback_config or None),
    }
    return render(request, "agents/detail.html", context)


@require_http_methods(["POST"])
def feedback_config_update(request, pk):
    """Save or clear the agent's feedback form config (stored as jsonb).

    Mirrors nudge_config_update: validates the JSON body with the FeedbackConfig
    Pydantic model and persists the normalized dump. `{"_delete": true}` clears it.
    """
    from pydantic import ValidationError

    from agents.schemas.feedback import FeedbackConfig

    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if data.get("_delete"):
        AgentConfig.objects.filter(pk=pk, workspace_id=request.workspace_id).update(
            feedback_config=None
        )
        return JsonResponse({"ok": True, "feedback_config": None})

    try:
        cfg = FeedbackConfig.model_validate(data)
    except ValidationError as e:
        return JsonResponse({"error": json.loads(e.json())}, status=400)

    stored = cfg.model_dump(exclude_none=True)
    AgentConfig.objects.filter(pk=pk, workspace_id=request.workspace_id).update(
        feedback_config=stored
    )
    return JsonResponse({"ok": True, "feedback_config": stored})


@require_http_methods(["GET"])
def tab_data_prompt(request, pk):
    """Lazy-load data for the Prompt tab: base prompt + (optional) voice prompt from Langfuse.

    Fetches AgentConfig + voice_config in a single query via select_related.
    """
    agent = get_object_or_404(
        AgentConfig.objects.select_related("voice_config"),
        pk=pk,
        workspace_id=request.workspace_id,
    )
    if not agent.is_configurable:
        return JsonResponse({"error": "forbidden"}, status=403)

    prompt_config = agent.prompt_config or {}
    prompt_variables = prompt_config.get("prompt_variables", {})

    system_prompt = ""
    prompt_latest_version = None
    prompt_production_version = None
    if agent.alias:
        prompt_id = prompt_config.get("name") or _prompt_id(
            agent.workspace_id, agent.alias
        )
        try:
            versions = get_prompt_versions(prompt_id)
            if versions.get("latest"):
                system_prompt = versions["latest"].get("prompt", "") or ""
                prompt_latest_version = versions["latest"].get("version")
            if versions.get("production"):
                prompt_production_version = versions["production"].get("version")
        except Exception:
            logger.warning("langfuse_fetch_failed_agent", id=agent.id)

    voice_prompt = ""
    voice_prompt_is_active = False
    voice_prompt_latest_version = None
    voice_prompt_production_version = None
    if agent.alias:
        try:
            vc = agent.voice_config
        except AgentVoiceConfig.DoesNotExist:
            vc = None
        active_voice_name = (vc.voice_prompt_config or {}).get("name") if vc else None
        archived_voice_name = (
            (vc.voice_prompt_config_archived or {}).get("name") if vc else None
        )
        voice_prompt_is_active = bool(active_voice_name)
        stored_voice_name = active_voice_name or archived_voice_name
        if stored_voice_name:
            try:
                voice_versions = get_prompt_versions(stored_voice_name)
                if voice_versions.get("latest"):
                    voice_prompt = voice_versions["latest"].get("prompt", "") or ""
                    voice_prompt_latest_version = voice_versions["latest"].get(
                        "version"
                    )
                if voice_versions.get("production"):
                    voice_prompt_production_version = voice_versions["production"].get(
                        "version"
                    )
            except Exception:
                logger.warning("langfuse_voice_fetch_failed_agent", id=agent.id)

    return JsonResponse(
        {
            "system_prompt": system_prompt,
            "prompt_variables": prompt_variables,
            "prompt_latest_version": prompt_latest_version,
            "prompt_production_version": prompt_production_version,
            "voice_prompt": voice_prompt,
            "voice_prompt_is_active": voice_prompt_is_active,
            "voice_prompt_latest_version": voice_prompt_latest_version,
            "voice_prompt_production_version": voice_prompt_production_version,
        }
    )


@require_http_methods(["POST"])
def save_prompt_tab(request, pk):
    """Save base prompt and (optionally) voice prompt. Persists frozen Langfuse names
    on the agent / voice_config so future lookups survive alias changes.
    Voice prompt uses an archive-and-restore pattern: if an archived name exists from
    a prior delete, reuse it instead of creating a new Langfuse prompt.
    """
    agent = get_object_or_404(
        AgentConfig.objects.select_related("voice_config"),
        pk=pk,
        workspace_id=request.workspace_id,
    )

    system_prompt = request.POST.get("system_prompt", "").strip()
    if not system_prompt:
        if (
            request.headers.get("HX-Request")
            or request.headers.get("Accept") == "application/json"
        ):
            return JsonResponse({"error": "System prompt cannot be empty"}, status=400)
        return HttpResponse("System prompt cannot be empty", status=400)

    try:
        prompt_variables = json.loads(request.POST.get("prompt_variables", "{}"))
    except json.JSONDecodeError:
        prompt_variables = {}

    # --- base prompt ---
    existing = agent.prompt_config or {}
    base_prompt_id = existing.get("name") or _prompt_id(agent.workspace_id, agent.alias)
    agent.prompt_config = {"name": base_prompt_id, "prompt_variables": prompt_variables}
    agent.save(update_fields=["prompt_config"])

    try:
        create_or_update_prompt(base_prompt_id, system_prompt, labels=["production"])
    except Exception as e:
        logger.warning("failed_save_langfuse_prompt_agent", id=agent.id, error=str(e))

    # --- voice prompt (independent of voice channel; controlled by checkbox in UI) ---
    voice_prompt = request.POST.get("voice_prompt", "").strip()
    if voice_prompt:
        try:
            vc = agent.voice_config
        except AgentVoiceConfig.DoesNotExist:
            vc = AgentVoiceConfig.objects.create(agent=agent)

        active = vc.voice_prompt_config or {}
        archived = vc.voice_prompt_config_archived or {}
        voice_prompt_id = active.get("name")
        if not voice_prompt_id:
            if archived.get("name"):
                # Restore archived → active; reuse the same Langfuse prompt name
                vc.voice_prompt_config = archived
                vc.voice_prompt_config_archived = {}
                voice_prompt_id = archived["name"]
            else:
                voice_prompt_id = _prompt_id(agent.workspace_id, f"{agent.alias}-voice")
                vc.voice_prompt_config = {"name": voice_prompt_id}

        try:
            create_or_update_prompt(
                voice_prompt_id, voice_prompt, labels=["production"]
            )
        except Exception as e:
            logger.warning("failed_save_langfuse_voice_prompt_agent", id=agent.id, error=str(e))

        vc.save(update_fields=["voice_prompt_config", "voice_prompt_config_archived"])

    if (
        request.headers.get("HX-Request")
        or request.headers.get("Accept") == "application/json"
    ):
        return JsonResponse({"success": True})
    return redirect(f"{reverse('agents:detail', args=[agent.id])}?tab=prompt")


@require_http_methods(["POST"])
def delete_voice_prompt(request, pk):
    """Archive active voice_prompt_config into voice_prompt_config_archived and clear active.
    Langfuse prompt itself is not deleted (Langfuse has no delete API); the archived name
    will be reused if the user re-enables the voice prompt later.
    """
    agent = get_object_or_404(
        AgentConfig.objects.select_related("voice_config"),
        pk=pk,
        workspace_id=request.workspace_id,
    )
    try:
        vc = agent.voice_config
    except AgentVoiceConfig.DoesNotExist:
        return JsonResponse({"success": True})

    if vc.voice_prompt_config:
        vc.voice_prompt_config_archived = vc.voice_prompt_config
        vc.voice_prompt_config = {}
        vc.save(update_fields=["voice_prompt_config", "voice_prompt_config_archived"])

    return JsonResponse({"success": True})


@require_http_methods(["GET"])
def tab_data_voice(request, pk):
    """Lazy-load data for the Voice tab: STT/TTS providers + configs + language.

    Tools (Tools tab) and voice LLM (LLM tab) are intentionally not returned here.
    """
    vc = AgentVoiceConfig.objects.filter(
        agent_id=pk,
        agent__workspace_id=request.workspace_id,
        agent__is_configurable=True,
    ).first()

    if vc is None:
        accessible = AgentConfig.objects.filter(
            pk=pk,
            workspace_id=request.workspace_id,
            is_configurable=True,
        ).exists()
        if not accessible:
            return JsonResponse({"error": "forbidden"}, status=403)

    voice_config_data = None
    if vc is not None:
        voice_config_data = {
            "stt_provider": vc.stt_provider,
            "tts_provider": vc.tts_provider,
            "stt_config": vc.stt_config or {},
            "tts_config": vc.tts_config or {},
            "voice_language": vc.voice_language or "",
        }

    favourite_voices = list(
        FavouriteVoice.objects.filter(workspace_id=request.workspace_id).values(
            "voice_id", "voice_name", "preview_url", "labels"
        )
    )

    return JsonResponse(
        {
            "voice_config": voice_config_data,
            "favourite_voices": favourite_voices,
        }
    )


@require_http_methods(["GET"])
def tab_data_knowledge(request, pk):
    """Lazy-load data for the Knowledge Base tab.

    Returns KBs grouped by `kb_type` so the UI can render five sections —
    Documents (RAG-style), Doctors / Facilities / Services / Rankings (dataset
    containers). The connect/disconnect endpoints are kb-type-agnostic.
    """
    if not AgentConfig.objects.filter(
        pk=pk, workspace_id=request.workspace_id
    ).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    # Pull the agent's KB attachments with the default-loaded flag in one query.
    connected_flags: dict[int, bool] = dict(
        AgentKnowledgeBase.objects
        .filter(agent_id=pk)
        .values_list("knowledge_base_id", "is_default_loaded")
    )

    # One workspace-scoped query, partition in Python by kb_type then by attached.
    rows = list(
        KnowledgeBase.objects
        .filter(workspace_id=request.workspace_id)
        .values("id", "name", "description", "kb_id", "kb_type")
        .order_by("kb_type", "kb_id")
    )

    # Stable section order — predefined types first, then any future ones.
    section_order = [
        ("document", "Documents"),
        ("doctor", "Doctors"),
        ("facility", "Facilities"),
        ("service", "Services"),
        ("ranking", "Rankings"),
    ]
    sections: dict[str, dict] = {
        key: {"key": key, "label": label, "connected": [], "available": []}
        for key, label in section_order
    }

    for row in rows:
        bucket = sections.get(row["kb_type"])
        if bucket is None:
            # Future kb_type not yet in section_order — fall through into a
            # synthetic section so the UI doesn't drop the row.
            bucket = sections.setdefault(
                row["kb_type"],
                {"key": row["kb_type"], "label": row["kb_type"].title(), "connected": [], "available": []},
            )
        is_connected = row["id"] in connected_flags
        target = bucket["connected"] if is_connected else bucket["available"]
        item = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "kb_id": row["kb_id"],
        }
        if is_connected:
            item["is_default_loaded"] = connected_flags[row["id"]]
        target.append(item)

    return JsonResponse({"kb_types": list(sections.values())})


@require_http_methods(["GET"])
def tab_data_tools(request, pk):
    """Lazy-load data for the Tools tab.

    connected: D-mode rows (primary attachments); voice: V-mode rows (voice-only
    additions). Both share the shape produced by ``_serialize_agent_tool``.
    available: unconnected tools usable by the agent (workspace or predefined).
    """
    if not AgentConfig.objects.filter(
        pk=pk, workspace_id=request.workspace_id
    ).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    agent_tools = AgentTool.objects.filter(
        agent_id=pk, mode__in=("D", "V"), tool__is_active=True
    ).select_related("tool")

    connected, voice = [], []
    d_tool_ids = set()
    for at in agent_tools:
        entry = _serialize_agent_tool(at)
        if at.mode == "D":
            connected.append(entry)
            d_tool_ids.add(at.tool_id)
        elif at.mode == "V":
            voice.append(entry)

    tool_type_display = dict(Tool.TOOL_TYPE_CHOICES)
    available = list(
        Tool.objects.filter(
            Q(is_predefined=True) | Q(workspace_id=request.workspace_id),
            is_active=True,
        )
        .exclude(id__in=d_tool_ids)
        .values("id", "name", "tool_type", "is_predefined")
    )
    for t in available:
        t["tool_type_display"] = tool_type_display.get(t["tool_type"], t["tool_type"])

    return JsonResponse(
        {
            "connected": connected,
            "voice": voice,
            "available": available,
        }
    )


@require_http_methods(["GET"])
def tab_data_llm(request, pk):
    """Lazy-load data for the LLM tab (default LLM + voice LLM override)."""
    if not AgentConfig.objects.filter(
        pk=pk, workspace_id=request.workspace_id
    ).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    llms_by_mode = {
        al.mode: al
        for al in AgentLLM.objects.select_related("llm").filter(
            agent_id=pk, mode__in=["D", "V"]
        )
    }

    return JsonResponse(
        {
            "current_llm_config": _serialize_agent_llm(llms_by_mode.get("D")),
            "voice_llm_config": _serialize_agent_llm(llms_by_mode.get("V")),
            "available_llms": _get_available_llms(),
        }
    )


@require_http_methods(["GET", "POST"])
def create(request):
    """Create a new agent via a minimal 3-field form.

    Collects name, welcome message, and system prompt. Everything else
    (LLM, knowledge, tools, theme, voice) is configured afterwards on the
    existing dashboard via per-tab PATCH endpoints.
    """
    if not request.user_context.get("features", {}).get("can_create_agent", True):
        return JsonResponse(
            {"error": "Agent creation is not enabled for this workspace"}, status=403
        )

    if request.method == "GET":
        return render(
            request,
            "agents/create.html",
            {
                "user_context": request.user_context,
                "current_page": "agents",
            },
        )

    name = request.POST.get("name", "").strip()
    welcome_message = request.POST.get("welcome_message", "").strip()
    system_prompt = request.POST.get("system_prompt", "").strip()

    if not name:
        return _render_create_error(
            request,
            "Please enter a name for your agent.",
            status=400,
            name=name,
            welcome_message=welcome_message,
            system_prompt=system_prompt,
        )

    if not system_prompt:
        return _render_create_error(
            request,
            "Please enter a system prompt for your agent.",
            status=400,
            name=name,
            welcome_message=welcome_message,
            system_prompt=system_prompt,
        )

    base = slugify(name)[:250] or "agent"
    alias = f"{base}-{random.randint(1000, 9999)}"
    if AgentConfig.all_objects.filter(
        workspace_id=request.workspace_id, alias=alias
    ).exists():
        return _render_create_error(
            request,
            "Could not generate a unique alias — please try again.",
            status=500,
            name=name,
            welcome_message=welcome_message,
            system_prompt=system_prompt,
        )

    prompt_id = _prompt_id(request.workspace_id, alias)
    raw_agent_id = f"{uuid.uuid4()}#{request.workspace_id}"
    agent_id = base64.b64encode(raw_agent_id.encode("utf-8")).decode("utf-8")

    agent = AgentConfig.objects.create(
        workspace_id=request.workspace_id,
        alias=alias,
        name=name,
        agent_id=agent_id,
        initial_message={"text": welcome_message, "suggestions": []},
        prompt_config={"name": prompt_id},
        allowed=["text", "file", "audio"],
        idle_session_expiry=3600,
        # An agent's data lives where its workspace's does; matrix reads this.
        agent_details={"region": current_region()},
    )

    try:
        create_or_update_prompt(prompt_id, system_prompt, labels=["production"])
    except Exception as e:
        logger.error("failed_save_initial_langfuse_prompt_agent", id=agent.id, error=str(e))
        # TODO: failure case to be informed to the user via a toast message on the redirect page , redirect to prompt page if it fails

    return redirect(f"{reverse('agents:detail', args=[agent.id])}?tab=general")


@require_http_methods(["POST"])
def update(request, pk):
    """Update an existing agent"""
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)

    alias = request.POST.get("name", "").strip()  # form field still named 'name'
    display_name = request.POST.get("display_name", "").strip()
    first_message = request.POST.get("first_message", "").strip()
    quick_replies_json = request.POST.get("quick_replies", "[]")

    try:
        quick_replies = json.loads(quick_replies_json)
    except json.JSONDecodeError:
        quick_replies = []

    normalized_quick_replies = []
    for reply in quick_replies:
        if isinstance(reply, str):
            if reply.strip():
                normalized_quick_replies.append({"label": reply.strip(), "value": reply.strip()})
        elif isinstance(reply, dict):
            label = str(reply.get("label", "") or reply.get("value", "")).strip()
            value = str(reply.get("value", "") or label).strip()
            if label:
                normalized_quick_replies.append({"label": label, "value": value})

    # Build initial_message structure
    initial_message = {
        "text": first_message,
        "suggestions": normalized_quick_replies,
    }

    effective_alias = alias if alias else agent.alias

    # Build theme JSON from appearance form fields
    theme_accent = request.POST.get("theme_accent", "").strip()
    theme_nudge_color = request.POST.get("theme_nudge_color", "").strip()
    theme_mode = request.POST.get("theme_mode", "light")
    theme_header_tinted = request.POST.get("theme_header_tinted", "") == "1"
    theme_allowed_json = request.POST.get("theme_allowed", "")
    title_img_file = request.FILES.get("title_img")
    background_img_file = request.FILES.get("background_img")
    assistant_icon_file = request.FILES.get("assistant_icon")
    try:
        allowed = (
            json.loads(theme_allowed_json)
            if theme_allowed_json
            else ["text", "file", "audio"]
        )
    except json.JSONDecodeError:
        allowed = ["text", "file", "audio"]

    theme = dict(agent.theme or {})
    # Remove legacy background color if present
    theme.pop("background", None)

    if theme_accent:
        theme["accent"] = theme_accent
    elif request.POST.get("clear_accent") == "1":
        theme.pop("accent", None)

    if theme_nudge_color:
        theme["nudge_color"] = theme_nudge_color
    elif request.POST.get("clear_nudge_color") == "1":
        theme.pop("nudge_color", None)

    theme["header_tinted"] = theme_header_tinted

    # Banner: one line under the widget header; no text clears it.
    if banner := clean_banner(request.POST.get("theme_banner")):
        theme["banner"] = banner
    else:
        theme.pop("banner", None)

    def _handle_image_field(theme_key, file, clear_flag, url_field, field_name):
        if clear_flag:
            theme.pop(theme_key, None)
        elif file:
            theme[theme_key] = _save_theme_image(
                request.workspace_id, agent.id, field_name, file
            )
        elif url := request.POST.get(url_field, "").strip():
            try:
                theme[theme_key] = _validate_theme_image_url(url)
            except ValueError:
                pass

    _handle_image_field(
        "title_img", title_img_file,
        request.POST.get("clear_title_img") == "1",
        "title_img_url", "title_img",
    )
    _handle_image_field(
        "background_img", background_img_file,
        request.POST.get("clear_background_img") == "1",
        "background_img_url", "background_img",
    )
    if theme.get("background_img"):
        theme["mode"] = theme_mode
    else:
        theme.pop("mode", None)

    icon_file = request.FILES.get("icon")
    _handle_image_field(
        "icon_img", icon_file,
        request.POST.get("clear_icon") == "1",
        "icon_img_url", "icon",
    )
    _handle_image_field(
        "assistant_icon", assistant_icon_file,
        request.POST.get("clear_assistant_icon") == "1",
        "assistant_icon_url", "assistant_icon",
    )

    agent.alias = effective_alias
    agent.name = display_name if display_name else agent.name
    agent.initial_message = initial_message
    agent.theme = theme
    agent.allowed = allowed

    # idle_session_expiry: UI sends minutes, store as seconds; clamp 30–360 mins
    try:
        idle_mins = int(request.POST.get("idle_session_expiry_minutes", 30))
    except (ValueError, TypeError):
        idle_mins = 30
    idle_mins = max(30, min(360, idle_mins))
    agent.idle_session_expiry = idle_mins * 60

    if "coexistence_pause_minutes" in request.POST:
        agent.coexistence_pause_seconds = _coexistence_pause_seconds(
            request.POST["coexistence_pause_minutes"]
        )

    # BYOA shared secret link: attach (valid active credential in this workspace)
    # or unlink (empty/invalid → clear the shared_secret_id key).
    ss_id = request.POST.get("shared_secret_id", "").strip()
    if ss_id:
        from byoa.models import ByoaCredential
        agent.shared_secret = ByoaCredential.objects.filter(
            id=ss_id,
            workspace_id=request.workspace_id,
            secret_type=ByoaCredential.SECRET_TYPE_BYOA,
            is_active=True,
        ).first()
    else:
        agent.shared_secret = None

    agent.save()

    return redirect(f"{reverse('agents:detail', args=[agent.id])}?tab=general")


@require_http_methods(["POST"])
def delete(request, pk):
    """Delete an agent"""
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)

    agent.delete()

    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True, "message": "Agent deleted successfully"})

    return redirect("agents:list")


@require_http_methods(["POST"])
def save_session_context(request, pk):
    """Save playground session context to agent config."""
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)
    session_context_raw = request.POST.get("session_context", "[]").strip()

    # Handle override icon upload/URL:
    clear_override_icon = request.POST.get("clear_override_icon") == "1"
    override_icon_file = request.FILES.get("override_icon")
    override_icon_url = request.POST.get("override_icon_url", "").strip()

    # Determine final override icon URL
    final_icon_url = ""
    current_context = agent.playground_session_context or {}
    if not isinstance(current_context, dict):
        current_context = {}
    current_icon_url = current_context.get("override_icon_url", "")

    if clear_override_icon:
        final_icon_url = ""
    elif override_icon_file:
        final_icon_url = _save_theme_image(
            request.workspace_id, agent.id, "playground_override_icon", override_icon_file
        )
    elif override_icon_url:
        try:
            final_icon_url = _validate_theme_image_url(override_icon_url)
        except ValueError:
            final_icon_url = current_icon_url
    else:
        final_icon_url = current_icon_url

    base_url = f"{reverse('agents:detail', args=[pk])}?tab=widget"

    try:
        context_pairs = json.loads(session_context_raw)
    except (json.JSONDecodeError, TypeError):
        context_pairs = []

    context_dict = {}
    for pair in context_pairs:
        k = pair.get("key", "").strip()
        v = pair.get("value", "")
        if isinstance(v, str):
            v_stripped = v.strip()
            if (v_stripped.startswith("{") and v_stripped.endswith("}")) or (v_stripped.startswith("[") and v_stripped.endswith("]")):
                try:
                    v = json.loads(v_stripped)
                except (json.JSONDecodeError, ValueError):
                    v = v_stripped
            else:
                v = v_stripped
        if k:
            context_dict[k] = v

    if context_dict or final_icon_url:
        agent.playground_session_context = {
            "context": context_dict,
            "override_icon_url": final_icon_url,
        }
    else:
        agent.playground_session_context = None

    agent.save(update_fields=["playground_session_context"])
    return redirect(base_url)


def prompts(request):
    """Prompts management page"""
    context = {
        "user_context": request.user_context,
        "current_page": "agents",
    }
    return render(request, "agents/prompts.html", context)


def configs(request):
    """Agent configurations page"""
    context = {
        "user_context": request.user_context,
        "current_page": "agents",
    }
    return render(request, "agents/configs.html", context)


@require_http_methods(["GET"])
def tab_data_channel(request, pk):
    agent = get_object_or_404(AgentConfig, pk=pk, workspace_id=request.workspace_id)
    linked = None
    try:
        ai = AgentIntegration.objects.select_related("integration").get(
            agent=agent, integration__is_active=True
        )
        linked = {
            "id": ai.integration.id,
            "name": ai.integration.name,
            "provider": ai.integration.provider,
        }
    except AgentIntegration.DoesNotExist:
        pass

    workspace_integrations = [
        {"id": i.id, "name": i.name, "provider": i.provider}
        for i in Integration.objects.filter(workspace_id=request.workspace_id)
    ]
    from django.conf import settings

    base = getattr(settings, "DOOT_WEBHOOK_BASE_URL", "").rstrip("/")
    webhook_url = (
        f"{base}/wh/medassist?agent_id={agent.agent_id}" if agent.agent_id else None
    )

    return JsonResponse(
        {
            "linked_integration": linked,
            "workspace_integrations": workspace_integrations,
            "webhook_url": webhook_url,
        }
    )
