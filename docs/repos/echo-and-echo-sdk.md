# echo (echo-agents) and echo-sdk (echo)

Read from code: echo `676ddb8` (package `echo_agents` v0.3.10), echo-sdk `78c1048` (package `echo`, public). Both Python, async-first, Pydantic v2, orjson, optional deps guarded. Both say: never commit without explicit confirmation.

## Split of responsibility
| echo-sdk (`echo`) = framework | echo (`echo_agents`) = Eka domain |
|---|---|
| `BaseAgent`, `GenericAgent` and the agent loop; streaming events | search tools over Eka datasets, KB retriever tools, triage, vitals, pharmacy flow |
| `BaseTool`, `ControlFlow`, MCP client (`MCPTool`, connection manager), elicitation base | `SelectionElicitationTool`, `NearestPharmacyElicitationTool` |
| LLM providers (Anthropic, Bedrock, OpenAI, Gemini, OpenAI-compatible) behind `get_llm(LLMConfig)` | Intent classifier agent (YAML persona) and sub-intent retriever (Chroma) |
| Skills (`Skill`, `SkillRuntimeConfig`, `load_skill`/`unload_skill`) | User-context service, reminder scheduler, notification builder |
| Prompts (`AgentPrompt`, `PromptConfig`, Langfuse and file providers) | `heuristics/` zero-token classifier; `agent_memory/scribe` (doctor prescribing memory for EkaScribe, not chat) |
| `PgQueryTool` + Postgres client (`echo.databases.postgres`), Weaviate connector, audio transcription (Gemini, Sarvam, Eka), evals (Langfuse) | |

## echo-sdk: how the pieces work
- **Agent loop** (`agents/base.py`): builds the system prompt (persona + task cached prefix, then volatile context incl. time) and the tool list each turn; calls the LLM; runs tools; loops up to `max_iterations`. A tool result's `ControlFlow` decides what happens: `CONTINUE` (feed back), `INTERRUPT` (state changed; recompute prompt/tools and re-invoke, internal tools only), `PAUSE` (stop and show the user, used by elicitation). `Observability.SILENT` hides internal tool events.
- **Tools**: subclass `BaseTool` with `name`, `description`, `input_schema`, `async run(**kwargs)`. Hidden parameters (user id, workspace id, session id, channel, session context) arrive through `tool_context`, never through the schema the model sees. Return `str`, `dict` or `ToolOutput(result, meta)`; elicitation tools return `ElicitationDetails`.
- **Skills**: `instructions` text comes from a Langfuse prompt (`task.description`). In `llm` mode the prompt lists `<available_skills>` (name and description); the model calls `load_skill`; tool visibility = `base_tool_names` + active skills' tools + meta tools.
- **Prompts**: provider chosen by `ECHO_PROMPT_PROVIDER` (langfuse default, file for local). `PromptConfig(name, version, prompt_variables)`.
- **LLM config**: provider, model, temperature, max tokens, max iterations; provider-specific reasoning/thinking settings; prompt caching (`cache_messages`, `cache_ttl`).
- **Knowledge**: `get_knowledge_base(config)` returns a connector; Weaviate connector is read-only hybrid search (multi-tenant collection, `kb_id` filter, shared clients per cluster). Records must carry `text`, `kb_id`, `source_uri`, `filename`, `doc_title`, category fields, `heading_path`, page range. Indexing is a separate pipeline (not in any connected repo).
- **PgQueryTool**: a tool defined by a SQL string with named parameters, bound to a workspace and KB at construction; results are rows. All echo dataset search tools are built on it, so a new dataset search is mostly SQL plus a description.

## echo: the search tools
- `search_doctors` / `search_facilities` / `search_services` (`tools/datasets/`): Postgres full-text and trigram ranking. Doctor ranking: filters (city, facility id, gender, name when alone) drop rows; specialization, query text, area, name-with-anchor only reorder. Relevance (match quality) and effective priority (business curation plus campaign boost) are separate and combine only in ORDER BY (`FLOOR(rel*10)*70 + priority`). Up to 30 lean rows; `search_result_details(doctor_id|facility_id|service_id)` returns full detail.
- Prompt grounding: matrix injects `<available_cities>` and `<available_specializations>` so the model uses real values.
- Data rules that decide result quality: `aliases` = name variants only, `keywords` = synonyms and conditions, `specialization` = canonical lowercase label (comma separated; `&` breaks matching).
- Campaigns: ranking rules boost priority for matching query keywords.

## echo: other tools and services
| Item | Behaviour |
|---|---|
| `retrieve_clinical_guidelines` (Weaviate), `retrieve_knowledge` (Bedrock) | Return formatted passages plus `meta.sources` (for citation links). Weaviate gates on cosine similarity (default 0.45, tunable per KB), says "no relevant guidance" instead of guessing, and says "could not be reached" on failure |
| `selfcare_triage` | Severity + time urgency + pathway map to red/orange/green; also schedules a WhatsApp checkup reminder (not on WhatsApp channel) |
| `retrieve_patient_vitals` | Reads protobuf vitals from the device ingestion service by user oid and returns `{test: {date: "value unit interpretation"}}` |
| `nearest_pharmacy_elicit` | Customer-specific voucher flow: pills for city if no location, cards of nearest pharmacies, tap issues a voucher through a partner API, registers the patient and a placeholder appointment in the EMR, returns a media card. Shows how a multi-step elicitation uses `_meta.schema` |
| `elicit_selection` | Pills (single) or multi-select; one question at a time |
| Reminder scheduler | Registers a delayed replay of an HTTP call with Jugaad (`jugaad.eka.care/reminder/schedule/`), generic (endpoint, body, trigger times) |
| Notification builder | Builds a WhatsApp template message and hands it to matrix `send-template` (which relays to doot) |
| User context | Postgres `matrix_user_context` reads/writes (matrix prefers the patient directory, Postgres as fallback) |

## How a new custom tool reaches an agent
1. Write a `BaseTool` subclass under `echo_agents/tools/` (and export it lazily).
2. In dev-console, create a Tool of type `custom` whose config `class` is `module.ClassName` (path under `echo_agents.tools`) and attach it to the agent (optionally hidden unless a skill loads it).
3. Matrix instantiates it with no arguments each turn (`load_custom_tool`). Anything the tool needs must come from `tool_context` or environment, not constructor arguments.
Dataset-style tools (constructed with workspace and KB ids) are instead wired in matrix `config/tool.py`.

## Where to change what
| Goal | Place |
|---|---|
| Change how the loop, skills or tool contract behave | echo-sdk |
| New dataset search or ranking change | echo `tools/datasets/` + `.claude/docs/doctor_search.md` rules |
| New LLM provider or model option | echo-sdk `llm/` |
| New knowledge-base retriever | echo `tools/` using an echo-sdk connector |
| Change agent wording | Langfuse prompt (no code) |
