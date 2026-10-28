# How it all fits (end-to-end flows)

One page to read before building anything. Repo detail is in `docs/repos/`. Everything here was read from code (October 2026).

## The cast
| System | One line |
|---|---|
| **dev-console** | Where clinics configure agents. Writes to Postgres; also hosts the datasets API, integrations, conversations dashboard |
| **matrix** | The chat backend. Reads the same Postgres, runs the agent every turn, owns sessions/tokens/history |
| **echo-sdk / echo** | The agent engine (loop, skills, prompts, LLMs) and Eka's own tools (dataset search, retrievers, triage) |
| **eka-mcp-sdk / eka-remote-mcp** | Tools that act on hospital and EMR systems (booking, patients, records), one client per hospital |
| **synapse-sdk** | The website widget (embed + React UI + core) |
| **doot** | WhatsApp: translates messages to and from matrix, sends templates |
| **Langfuse** | Prompts (agent and skill text) |
| **Trinity** | Patient directory (identity/profile). **Jugaad**: delayed HTTP callbacks. **Weaviate/Bedrock**: document search. **Eka EMR APIs**: the actual patient data |

## 1. Configuring an agent (clinic side)
Console UI (or `/api/agents/`) writes `agent_configs` + mapping rows (LLM, tools, knowledge bases, skills, storage, voice) in Postgres, and creates the prompt in Langfuse (`{workspace_id}-{agent_name}`). Nothing is pushed to matrix: matrix reads the same tables on the next session.
The embed snippet in the console's Widget tab carries only the `agent-id` and display options.

## 2. A web chat turn
1. Widget loads agent config (`GET agent-config/{agent_id}`, public: theme, initial message, allowed, nudge flag).
2. Token exchange: no partner token = guest, partner token = logged-in user (identity = patient oid from Trinity). Receives `sess_token` (1h) and `refresh_token`.
3. `POST session` -> session id; connect by WebSocket or HTTP stream.
4. User message -> matrix saves it (Redis + DynamoDB), builds an echo `GenericAgent`: prompt from Langfuse, enriched with user context, campaign and timezone; tools = `elicit_selection` + custom + MCP + KB tools; skills the model may load.
5. The model calls tools. MCP tools go to eka-remote-mcp with identity headers; there the **workspace's client** talks to the hospital or EMR API. Dataset tools query Postgres. Document tools query Weaviate/Bedrock.
6. Text streams back; a tool that needs the user (pills, cards, OTP) **pauses** the turn and sends a card.
7. The user's answer goes to the **tool callback** (straight to the tool, no LLM) which returns the next card or result; the model continues when the flow completes (`send_to_llm`).

## 3. A WhatsApp turn
User message -> provider webhook -> doot (verify, dedupe, consent gate, session choice) -> same matrix endpoints with `x-channel` for WhatsApp, authenticated by a BYOA token minted from the agent's shared secret with the phone as identity -> streamed reply -> doot renders text, buttons, lists and numbered options and resolves the user's tap locally when it can (calls the tool callback, or sends a marker such as `[SELECTION: x]` for the model).
Matrix tells MCP servers the channel cannot render cards (`x-eka-supports-elicitation: false`) so tools return plain text.

## 4. Proactive messages
Anything that must happen later (reminders, nudges days after a chat) is a **template** message: a caller (echo or an MCP tool) builds `{agent_id, to, template_id, params, idempotency_key}`; Jugaad stores the request and replays it; matrix `notifications` relays to doot `send/template`; doot maps the template id to the provider's template and sends. WhatsApp only allows free text within 24h of the user's last message, so the opener must be a template; the user's reply reopens the session (doot resumes the session the template came from).

## 5. Nudges (website)
Embed asks matrix `POST nudges` with the page URL and meta tags. Matrix returns a cached manual rule (wildcards allowed) or generates 3 to 5 messages with Haiku and caches them. Response carries `delay` and `expiry`; the embed shows a popup (or, in our centered-mode branch, the text in the search bar).

## 6. Knowledge
- **Directory data** (doctors, facilities, services): clinic uploads CSV/JSON in dev-console -> Postgres -> echo SQL search tools (ranked) attached automatically when the dataset KB is attached to the agent.
- **Documents** (FAQ, guidelines): a knowledge-base row (provider, collection id, tool name and description in metadata) -> matrix builds a Weaviate/Bedrock retriever tool. Indexing the documents is done by a pipeline that is not in any connected repo (the record schema it must write is known).
- **EMR formularies** (drugs, labs, symptoms, diagnoses): partner search in the doctor-side EMR; not chat tools.

## 7. Identity
Guest: random id, no history after expiry. Logged in: partner token (BYOA) or Eka connect-auth token -> patient oid. In hospital workspaces (Apollo, RFH, Moolchand, Sukino, Eternal) the MCP client runs its own **mobile OTP login inside the chat** and lets the user pick a UHID, stored in the session.

## 8. Where a setting lives
| Setting | Stored | Read by |
|---|---|---|
| Agent name, theme, initial message, allowed, nudge config, feedback form | `agent_configs` | matrix public config, widget |
| Prompt text (agent, skills) | Langfuse | echo-sdk via matrix |
| LLM choice, temperature, credentials | `agent_llm_mapping` | matrix |
| Tools, MCP sub-tool selection, headers | `tools`, `agent_tool_mapping` | matrix (discovers MCP tools once per session) |
| Which tools each workspace sees on the shared MCP server | `workspace_tools_dict` / `DEFAULT_EKAEMR_REMOTE_TOOLS` | MCP server |
| Which hospital client a workspace uses | `workspace_client_dict` | MCP server |
| Skills and their dependencies | `skills`, `agent_skill_mapping` | matrix -> echo-sdk |
| WhatsApp numbers and bindings | `integration` tables | doot via dev-console resolve API |
| Consent text and version | agent integration config | doot |
| Region of an agent's data | `agent_details.region` | matrix, console |
| Partner login secret | BYOA credential | matrix, doot |

## 9. Boundaries worth remembering
- Matrix never writes agent config; dev-console never runs the agent.
- A tool is a hand, a skill is training: a skill is a prompt that tells the model when and how to use named tools. Tools hidden from the default set appear only after a skill loads.
- Elicitation is a contract (`component`, `input`, `status`, `_meta.schema`) shared by MCP tools, echo tools, matrix, the widget and doot. A new card type touches all of them.
- WhatsApp templates must be approved by Meta before use.
