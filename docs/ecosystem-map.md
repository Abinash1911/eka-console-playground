# Ecosystem map (index)

Read from code in October 2026. Start with `docs/how-it-fits.md` (end-to-end flows), then the repo note you need.

| Repo | Note | Read depth |
|---|---|---|
| dev-console | `docs/repos/dev-console.md` | models, APIs, datasets, integrations, conversations pipeline: read; analytics/reports/evals/abdm: overview |
| matrix | `docs/repos/matrix.md` | routes, auth, session, agent turn, config loading, nudges, tool callback: read; voice pipeline internals, summary/topic services: overview |
| echo + echo-sdk | `docs/repos/echo-and-echo-sdk.md` | agent loop, skills, tools, search, retrievers, scheduler: read; LLM providers, evals, audio internals, ag_ui: overview |
| eka-mcp-sdk + eka-remote-mcp | `docs/repos/mcp-layer.md` | tool catalogue, client factory, per-hospital clients, auth flow: read; each hospital API payload: not read |
| synapse-sdk | `docs/repos/synapse-sdk.md` | modes, flow, elicitation, embed: read; voice and file internals: overview |
| doot | `docs/repos/doot.md` | bridge flow, outbound, integration API: read; Scribe bot and PDF generation: skipped (EkaScribe, not chat) |

Also: `docs/capability-index.md` (what exists), `docs/build-recipes.md` (where to start for common builds), `docs/build-log.md` (history).

## Not found in any connected repo
- The job that indexes clinic documents into Weaviate/Bedrock.
- Anything that reads a doctor service's prepaid/postpaid setting, or creates a payment link in chat (Moolchand's booking returns "make payment"; the payment step is on the hospital side).
- A list-prescriptions-by-patient API.
- The external Scheduler service named in doot's scheduler spec (Jugaad is what echo and the MCP server call).

## Naming
doot = scribesnap (old name). "medassist", "matrix", "agent" appear in URLs and class names for the same chat system. `wid` = workspace id. `agent_id` = base64 of `<uuid>#<workspace_id>`.
