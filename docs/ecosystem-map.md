# Ecosystem map

Status: first draft. Each statement is marked **[read]** (seen in code or docs) or **[to verify]**. Fill in repo by repo; do not trust a [to verify] line.

## How the pieces fit (draft)

```
Visitor's browser
  synapse-sdk  (chat widget: core + widget + widget-embed)        [read]
        | HTTP / WebSocket, header x-channel (widget, web, side_panel, center)   [read]
        v
  matrix  (chat backend: sessions, agent config, runs the agent)   [read in part]
        | builds tools per agent from DB config                    [read]
        v
  echo  (agent library: tools, dataset search, KB retrievers)      [read in part]
        | MCP calls
        v
  eka-remote-mcp -> eka-mcp-sdk  (tools over Eka APIs: appointments, patients, records, prescriptions)  [read]
        v
  Eka APIs (api.eka.care)                                          [read]

  doot: WhatsApp bridge to matrix                                  [read in part]
  dev-console: where clinics configure agents, skills, tools, datasets, knowledge bases, widget snippet  [read]
```

## Repos

| Repo | Owns | Read so far |
|---|---|---|
| synapse-sdk | Widget UI, embed loader, channel header | Display modes, size, centered mode, nudges (fully for those areas) |
| matrix | Sessions, agent config from DB, builds KB/dataset/MCP tools | `agent_utils.py`, config loading (search-level for the rest) |
| echo | Agent library: dataset search tools, Bedrock/Weaviate retrievers, reminder scheduler, triage | Tool lists, KB skill (search-level for the rest) |
| eka-mcp-sdk | MCP tools over Eka EMR APIs | Tool list and booking/prescription/records clients |
| eka-remote-mcp | Hosted MCP server, OAuth, Apollo/Sukino tools | README and tool names |
| dev-console | Django console: agents, skills, tools, knowledge, datasets, widget tab | Knowledge bases, skills model, widget tab |
| doot | WhatsApp bridge | Scheduler spec, tests (search-level only) |

## Data and auth [to verify]
- dev-console: MySQL (default, auth) and PostgreSQL (`agents_pg`) per its CLAUDE.md.
- matrix sessions: DynamoDB; agent config in PostgreSQL; KBs in Weaviate/Bedrock.

## Next reads (in order)
1. matrix: session creation, channels, how agent config reaches echo.
2. echo: dataset tools, elicitation, user context.
3. doot: WhatsApp flow end to end.
4. dev-console: nudges, campaigns, integrations.
5. developer.eka.care: full API index.
