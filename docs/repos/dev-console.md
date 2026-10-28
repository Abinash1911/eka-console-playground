# dev-console (Django admin for agents)

Read from code at commit `ae25fd6` (main, Oct 2026). Django 5, Alpine/HTMX templates, Tailwind. Behind a gateway that sets a `jwt-payload` header (claims: `oid`, workspace `w-id`, region `r`); `JWTAuthenticationMiddleware` turns it into `request.workspace_id`. Internal routes (`/internal/`, `/console-index/`) rely on the network boundary, not a token.

## Databases (routers in `core/db_routers.py`)
- `default` MySQL: core, dashboard, users, conversation annotations (regional).
- `auth` MySQL: connect credentials, telephony.
- `agents_pg` PostgreSQL: **agents, datasets, byoa, integration, console_index.** **This is the same Postgres matrix reads for agent config** (`agent_configs`, `agent_tool_mapping`, `knowledge_base`, ...). So saving an agent in the console is what changes matrix behaviour, with no sync step.
- Per-region Postgres/MySQL/ClickHouse aliases via `core/region.py` (token claim `r`, codes like IN, ZA).

## What an agent is (`agents/models.py`)
`AgentConfig` (db table `agent_configs`): `agent_id` (base64 of `<uuid>#<workspace_id>`, the id matrix and the widget use), `alias` (slug), `name`, `theme` (accent, mode, icon, background...), `initial_message` (text + up to 4 suggestions), `prompt_config` (Langfuse prompt name), `allowed` (text/audio/file), `idle_session_expiry`, `nudge_config`, `feedback_config`, `custom_tools` (class paths), `agent_details` (region, never changed), `shared_secret` (BYOA).
Attached through mapping tables:
| Mapping | Notes |
|---|---|
| `AgentLLM` (`agent_llm_mapping`) | mode `D` default or `V` voice; temperature, max tokens, max iterations; per-agent encrypted credentials |
| `AgentTool` (`agent_tool_mapping`) | mode `D` all channels, `V` voice only, `W` widget only; `tool_include` (which MCP sub-tools), custom headers, `is_default_visible` (false = only loaded through a skill) |
| `AgentKnowledgeBase` | `is_default_loaded` (false = only via a skill) |
| `AgentSkill` | per-agent resolved tool/KB/dataset dependency ids |
| `AgentStorageIntegration`, `AgentVoiceConfig` | uploads storage; voice STT/TTS (console allows Deepgram, Sarvam, ElevenLabs; matrix's voice model only lists ElevenLabs [to verify]) |
`Tool`: `mcp_server` (config = url, headers, transport) or `custom` (config has a class path under `echo_agents.tools`); `is_predefined` ones are shared by all workspaces. `Skill`: description (20 to 50 words), `prompt_config` (a Langfuse prompt), `tool_deps` / `kb_deps` / `dataset_deps`; predefined skills may depend only on predefined tools and KBs.

## Prompts
`services/langfuse_service.py` creates and versions prompts in Langfuse. Prompt id for an agent is `{workspace_id}-{agent_name}`. Skill prompts use the same mechanism. Matrix and echo-sdk fetch them at run time.

## Ways in
- **Console UI** (`/agents/`, `/knowledge/`, `/tools/`, `/skills/`, `/voice/`, `/nudge/`, `/campaigns/`, `/datasets/`, `/conversations/`, `/analytics/`, `/reports/`, `/evals/`, `/byoa/`, `/users/`, `/settings/`, `/abdm/`, `/connect/ekascribe/`). Tabs on an agent load by HTMX (`tab-data/prompt|voice|knowledge|tools|llm|skills|storage`).
- **Agent write API** (`/api/agents/`): `POST` create, `PATCH /<pk>/` update, sub-resources `/<pk>/<attr>/`. Same request shape matrix used to accept (`agents/schemas/requests.py`: name, initial message, prompt, LLM config, MCP configs, knowledge bases, custom tool class paths, storage, theme, voice, allowed). JWT workspace scoped.
- **Internal** (`/internal/agents/<agent_id>/...`): `integration/` (doot reads WhatsApp credentials), `consent/` (doot records consent), `delete-user/` ("delete me": archives the user's patient-directory profiles), `config/` (snapshot for evals).
- **Integration API** (`/api/integrations/`, `/api/product-integrations/`, `/api/resolve/...`): channel accounts (WhatsApp numbers via Meta, Interakt, Interakt-TP, Netcore, Turn.io, Twilio) and bindings to products (`agent` or `messenger`). `resolve` returns decrypted credentials to internal services (doot). Message templates are proxied to Meta and not stored here.
- **Datasets API** (`https://api.eka.care/admin/datasets/v1/`, mounted above Django admin): list, write (CSV or JSON), delete, delete-all, export, search-status switch.

## Datasets: two different worlds
1. **Chat directory datasets: doctors, facilities, services.** Searched by agents through echo (`search_doctors`...). Linked to agents as knowledge bases of type doctor, facility, service (plus `ranking` rules). Stored in Postgres with full-text and trigram search.
2. **EMR formulary datasets: drugs, symptoms, diagnoses, lab tests, investigations, results, panels.** These feed **partner search** (the doctor-side EMR search), with a per-dataset "search enabled" switch and an Elasticsearch/medical-db sync for labs. They are **not** chat tools. (An earlier note in this harness called their absence in matrix a gap; that was wrong.)
Both use one schema-driven import pipeline (`datasets/schemas.py` is the single source of field shapes, `registry.py` maps slugs, `importer.py` does CSV validate then commit).
Default knowledge bases per workspace are created on demand (`agents/services/default_kbs.py`).

## Document knowledge bases (the FAQ kind)
Model stores provider (bedrock/weaviate/catalogue), provider id, name, description, `num_results`, source url. No upload or indexing code in this repo; the detail page's file-upload UI refers to fields that no longer exist. `conversations/views.py` knows how Weaviate and Bedrock sources are shaped when showing citations.

## Conversations dashboard
Source of truth is DynamoDB (matrix's `med-assist-session` and `-session-flow`). A Lambda (`infra/lambda/console_index_forwarder`) forwards DynamoDB Stream records to `POST /console-index/ingest/`, which projects them into `console_session` and `console_event` (Postgres, 3-month retention, monthly partitions, idempotent, rebuildable). `conversations/views.py` (1.6k lines) is the list, message viewer, translation (Gemini), annotations, favourite filters.

## Other pieces
- `analytics/`: usage and cost charts from ClickHouse; credit balance through the khata service; credit gate state machine.
- `reports/`: admin-defined ClickHouse SQL charts.
- `evals/`: runs MCP tool eval suites from Langfuse datasets (Celery), grades, reports.
- `abdm/`: ABDM facility onboarding and credentials. `ekascribe/`: EkaScribe configuration page.
- `byoa/`: shared secrets for partner login (matrix verifies partner tokens, doot mints them).
- `services/`: Trinity patient-directory client, Langfuse, auth API, NDHM, voice, API keys.
- `dashboard/`: home, API keys (create, long-lived tokens).
- Widget snippet and preview live in `templates/agents/detail.html` (Widget tab).

## Where to change what
| Goal | Place |
|---|---|
| New agent setting | `agents/models.py` + migration (`--database=agents_pg`), tab view in `agents/views/agent.py`, request schema, and matrix `agent_config_utils.py` if the runtime needs it |
| New dataset type | `datasets/schemas.py`, `registry.py`, `models.py`, KB type in `agents/models.py`, then matrix `config/tool.py` only if agents should search it |
| New channel provider | `integration/schemas/whatsapp/` + doot provider |
| New nudge or campaign behaviour | `agents/views/nudges.py`, `campaigns.py`, matrix nudge service |
