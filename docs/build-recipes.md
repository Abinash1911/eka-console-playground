# Build recipes

Short, ordered recipes for common additions, so the work starts at the right file. Each step names the repo. Verified against the code listed in `docs/repos/`.

## New tool for every hospital (e.g. "cancel with reason")
1. eka-mcp-sdk: method on `BaseEMRClient` and `EkaEMRClient`; service method; `@mcp.tool` in `tools/*.py` with annotations and a docstring that says when to use it.
2. Each hospital client in eka-remote-mcp that supports it implements the method (others return "not implemented").
3. Add the tool name to the workspace allowlist (`DEFAULT_EKAEMR_REMOTE_TOOLS` and the per-workspace overrides).
4. In dev-console the agent's MCP tool picks it up through discovery (re-discover or new session).
5. If the model should only use it in certain flows, mark the tool "not default visible" and list it in a skill.

## New tool for one hospital
Remote `tools/<hospital>_tools.py` + the hospital client; allowlist that workspace only.

## New skill
1. Write the prompt in Langfuse (what to do, in what order, which tools to call, what to ask first).
2. dev-console Skills page: name, a 20 to 50 word description (this is what makes the model load it), prompt name, tool/KB/dataset dependencies (predefined skills may only depend on predefined tools and KBs).
3. Attach it to the agent (dependencies must already be attached).
4. Test with a real session: the model loads it on a matching request.

## New card type in chat
echo/MCP tool returns the card with a new component name -> core enum -> widget `ChatMessage` render branch -> doot presenter (WhatsApp rendering) -> matrix needs nothing if the contract is unchanged.

## New widget option (like display mode or size)
Embed attribute and `init()` key -> `loadAndRender` -> widget `MedAssistConfig` -> `useChatWidget` -> `WidgetContainer`; README; tests; bundle budget. Console Widget tab snippet if clinics should set it.

## New agent setting
dev-console model field (+ migration `--database=agents_pg`), tab view and request schema; matrix SQL in `agent_config_utils.py` and runtime model if matrix must read it; widget if it affects UI (via public config).

## New directory dataset type searched by agents
dev-console dataset schema/model/registry + KB type; matrix `config/tool.py` mapping; echo SQL search tool (subclass `PgQueryTool`).

## Document knowledge ("clinic FAQs")
Needs: (1) an indexing job that writes records in the Weaviate schema (`text`, `kb_id`, `source_uri`, `filename`, `doc_title`, `category`, `subcategory`, `source_org`, `heading_path`, `page_start`, `page_end`) into the tenant (workspace) of a collection, (2) a `knowledge_base` row with provider `weaviate`, the collection as provider id, and metadata `name`/`description` (the tool text the model sees; optional `min_similarity`, `alpha`), (3) the KB attached to the agent. Step 1 has no home yet.

## New proactive WhatsApp message
Template approved at Meta -> registered in doot (`templates.yml` or integration `templates`) -> caller builds the message and schedules with Jugaad (or sends now) -> matrix `notifications` -> doot.

## New hospital
New `BaseEMRClient` implementation in eka-remote-mcp, entry in `workspace_client_dict`, tool allowlist, workspace id mapping, OTP/login flow inside the client, dev-console workspace with an agent that has the MCP server attached.
