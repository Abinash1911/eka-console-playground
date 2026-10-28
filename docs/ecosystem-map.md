# Ecosystem map

Status: matrix section is read from code (commit `6f56888`, Oct 2026). Other repos are still draft. Markers: **[read]** seen in code or docs, **[to verify]** not yet confirmed. A "[to verify]" line must not be used to answer "do we have X?".

## How the pieces fit

```
Visitor's browser
  synapse-sdk  (chat widget: core + widget + widget-embed)                        [read]
        | HTTPS + WebSocket / HTTP stream, header x-channel                        [read]
        v
  matrix  (FastAPI delivery layer: sessions, auth, agent config, runs the agent)   [read]
        | builds an echo GenericAgent per turn from the agent's DB config          [read]
        v
  echo  (agent library: tools, dataset search, KB retrievers, skills runtime)      [read in part]
        | MCP calls (headers carry session, agent, mobile, elicitation support)    [read]
        v
  eka-remote-mcp -> eka-mcp-sdk  (tools over Eka APIs)                             [read in part]
        v
  Eka APIs (api.eka.care)

  doot: WhatsApp bridge. matrix relays template sends to it                        [read in part]
  dev-console: clinics configure agents, skills, tools, datasets, KBs, nudges       [read in part]
```

## matrix (read)

**What it is.** A FastAPI app ("Eka AI Delivery Layer", port 8051). Routes live under the legacy `/reloaded/med-assist/...` prefix and a newer `/eka-agent/...` alias (same handlers; the new prefix needs ingress routing).

**Main endpoints** (`med_assist/router/`):
- `auth` token exchange (partner/guest and refresh)
- `session` create, get (with history, rehydrates from DynamoDB for logged-in users), list, delete (soft), feedback
- `web_socket` and `http_stream` chat transports; `tool_callback` for elicitation answers
- `agent-config/{agent_id}` public config (name, theme, allowed, nudge flag, initial message, feedback), optional campaign override
- `nudges` / `user-nudge`, `run-prompt` (category-selected LLM, streamed), `notifications` (relays WhatsApp templates to doot), `voice` + `voice_ws` (WebRTC and Vobiz telephony, ElevenLabs STT/TTS), `conversation_summary`, `bot` hosted pages, `agent_links/forever_wena` (a hosted full-screen widget page for one customer, pinned widget version, GTM funnel events)

**Auth** (`AUTH_CLIENT_CONTRACT.md`): `sess_token` (1h) and rotating `refresh_token` (30d). Guest or logged-in "user" level. Partner login uses a partner token (BYOA, signed with the agent's shared secret). Failure codes: 401 refresh, 403 re-exchange, 404 new session. Guest sessions that leave Redis are gone.

**Storage.**
- Redis: session cache (10 min idle), chat stream per session, per-run output stream, last-message context
- DynamoDB (regional): sessions, message flow, tool callbacks, refresh tokens
- PostgreSQL: agent config (`agent_configs` and mapping tables), nudge cache, campaigns, user context

**One chat turn** (`service/agents/agent_service.py`):
1. Rebuild conversation from the Redis chat stream.
2. Fetch the agent's prompt (prompt provider, Langfuse via echo) and session from cache.
3. Enrich the prompt: workspace grounding (cached prefix), user context, session context, campaign text, timezone.
4. Build tools: common (selection elicitation) + custom + MCP + knowledge-base tools. Skills are built from the agent's skill rows.
5. Run `GenericAgent` (skills activated by the LLM; activated skills are restored from the last-message context each turn).
6. Stream text/tool events through a Redis output stream to the client; save messages; generate a topic once; handle elicitation pauses (pills, cards).

**Agent config loading** (`utils/agent_config_utils.py`): one base row plus parallel queries for LLM, knowledge bases, tools, skills. MCP tools are discovered when the config is built (session creation) and cached; a server that fails discovery is dropped, and any skill that depends on it is dropped too.

**Knowledge bases at runtime.**
- Document KBs: matrix reads provider, provider id and metadata (tool name, description, optional `min_similarity`, `alpha`) and builds a Bedrock or Weaviate retriever tool. Weaviate uses the KB's own workspace as the tenant. Matrix does not index documents.
- Dataset KBs: only `doctor`, `facility`, `service` become tools (`search_doctors` etc. plus `search_result_details`, and specialization/city lists injected as prompt context). Any other dataset KB type is dropped with a warning ("invalid KB type").

**Nudges.** Agent has a `nudge_config`. `POST /nudges` returns a cached nudge for domain + path (exact match first, then wildcard rules like `/abc/*`; manual rules win by longest path), else, when `nudge_type` is `llm`, generates 3 to 5 short messages from the page's meta tags with Claude Haiku 4.5 and caches them for `ttl_hours`. Client expiry is capped at 24h. The response carries `delay`. Any other type returns no nudge.

**Channels.** `x-channel` is read into the request context. Elicitation UI (pills, cards) is suppressed for `voice`, `wa`, `whatsapp`.

**Things to know.**
- `websoket_flow.md` says agent config comes from DynamoDB in places; the code reads PostgreSQL. Trust the code.
- The same doc lists known issues (token expiry not breaking the loop; a possible token-randomness bug).
- Matrix imports echo (`echo`, `echo_agents`) for all agent behaviour.

## Other repos (draft)

| Repo | Owns | Read so far |
|---|---|---|
| synapse-sdk | Widget UI, embed loader, channel header | Display modes, size, centered mode, nudges |
| echo | Agent library: dataset search tools, Bedrock/Weaviate retrievers, reminder scheduler, triage | Tool lists, KB skill (search-level) |
| eka-mcp-sdk | MCP tools over Eka EMR APIs | Tool list, booking, prescriptions, records |
| eka-remote-mcp | Hosted MCP server, OAuth, Apollo/Sukino tools | README, tool names |
| dev-console | Django console: agents, skills, tools, knowledge, datasets, widget tab | Knowledge bases, skills model, widget tab |
| doot | WhatsApp bridge | Scheduler spec, tests (search-level) |

## Next reads (in order)
1. echo: dataset tools, elicitation, user context, prompts.
2. doot: WhatsApp flow end to end.
3. dev-console: nudges, campaigns, integrations.
4. matrix leftovers: `tool_callback`, `http_stream`, voice pipeline, BYOA, user context, `conversation_summary`.
5. developer.eka.care: full API index.
