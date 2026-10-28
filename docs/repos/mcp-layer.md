# MCP layer: eka-mcp-sdk and eka-remote-mcp

Read from code: eka-mcp-sdk (public, `02a7397`) and eka-remote-mcp (`012545e`). These are the "hands" the chat agent uses to act on hospital and EMR systems. They are MCP servers (FastMCP) that matrix connects to as "tools" of type `mcp_server`.

## How the two fit
- **eka-mcp-sdk** (library, Python): the common tools, written against an abstract EMR client. Contains `register_doctor_tools(mcp)` (patients, appointments, doctors/clinics, prescriptions, records, CRM lead) and `register_abha_tools(mcp)`. Can run standalone (`eka_mcp_sdk.server`) with a client id and secret.
- **eka-remote-mcp** (hosted app at `mcp.eka.care`): imports the SDK, adds customer-specific tools and clients, OAuth for external MCP clients, usage metering, Jugaad scheduled requests. Deployed by pushing a `prod-x.y.z` git tag.

## The key idea: one tool, many hospital systems
Tools never call an API directly. Each tool resolves a **client for the caller's workspace** and calls the same method on it:
```
tool (book_appointment) -> ClientFactory.create_client(workspace_id) -> client.book_appointment_with_validation(...)
```
- The workspace id comes from the `x-eka-jwt-payload` header (matrix sets it; internal servers only).
- `settings.workspace_client_dict` maps workspace id to a client class path; default is `EkaEMRClient` (Eka EMR).
- Every client implements `BaseEMRClient` (patients, doctor discovery, slots, availability card, booking, appointments, prescriptions, records, CRM lead, service booking).
- **Which tools a workspace sees** is also configured: `workspace_tools_dict` (SDK middleware) and, in remote, `DEFAULT_EKAEMR_REMOTE_TOOLS` plus per-workspace overrides in `server.py`. A new tool is invisible until it is added to the allowlist for the workspaces that should have it.

## Clients (eka-remote-mcp `clients/`)
| Client | System | Notes |
|---|---|---|
| `EkaEMRRemoteClient` (default) | Eka EMR | adds mobile OTP login and UHID selection on top of the SDK's `EkaEMRClient` |
| `ApolloClient` | Apollo | doctor discovery, slots, booking; OTP in Redis; QuickUHID registration; CRM leads (fire-and-forget, cancelled if the user books) |
| `RFHClient` | RFH | OTP login, registration, booking, records/invoice flow via WSO2 gateway |
| `MoolchandClient` | Moolchand | OTP, booking; **booking returns "please make payment" (the hospital system issues the payment step; no link is built here)** |
| `EternalClient` | Eternal Hospital | Eka EMR booking with Eternal OTP and UHID lookup |
| `SukinoClient` | Sukino | service/package booking through PatientSelfService APIs, region -> center -> slot |
| `EkaPHRClient` | Eka PHR | patient and vitals APIs |

## Authentication inside a chat (all clients)
`authentication_elicitation` collects the mobile (or reads it from channel headers on WhatsApp), sends an OTP, verifies it (OTP kept in Redis per session), lists the patient's UHIDs as pills, and stores the choice in the session. Tools that need an authenticated user raise `AuthRedirectError`; `AuthRedirectMiddleware` (Apollo only) parks the original call, runs auth, then tells the model to retry the parked call.

## Tool catalogue
- **SDK, Eka EMR** (see `docs/capability-index.md`): patients (search, details, add, list, update, archive, by mobile, vitals, benefits), appointments (slots, dates, book, cancel, reschedule, complete, update, show/get basic and enriched), doctors/clinics (profile basic and comprehensive, business entities, services), availability cards (`doctor_availability_elicitation`, `service_availability_elicitation`), prescriptions (details by id), records (list, get, upload, delete), ABHA login (3 tools), CRM lead, assessments.
- **Apollo only:** `service_availability_elicitation` (with `user_hint`), `create_crm_lead_domestic`, `get_appointment`, `list_uhids`.
- **RFH only:** `get_medical_records` (invoice or document flow: type, case, document, delivered as a media card via S3 link), `list_uhids`.
- **Sukino only:** `validate_patient`, `sukino_service_availability_elicitation`, `sukino_book_service`, `sukino_create_lead`.
- Some SDK tools are registered but disabled on purpose (basic/enriched variants superseded).

## Tool conventions (what makes a good tool here)
- Annotated parameters and a docstring that tells the model when to use it and what to ask first; decorators `readonly_tool_annotations()` / `write_tool_annotations()`.
- Elicitation tools return a UI contract (`component`, `input`, `status: progress|success|failure`, `_meta.schema` for the next call); the chat client renders it and calls back (matrix tool callback, doot lists, widget cards).
- Never ask the user for mobile or UHID again once authenticated; use the session's.
- Duplicate-call guard (`get_deduplicator`) on writes.

## Scheduled requests (Jugaad)
`POST /internal/scheduled-request` is the callback Jugaad hits when a stored request fires. A tool can register a future HTTP call (URL, method, headers, body; auth header resolved at fire time) and later cancel it. Used by the CRM-lead push (cancelled when the user books) and the Eternal conversation email. Trusted-host check applies.

## Platform
- FastMCP server, `/health`, OAuth through `EkaCareProvider` (OIDC at accounts.eka.care) when `FASTMCP_SERVER_AUTH_EKACARE_*` env vars exist. Requests whose Host is internal (`.orbi.orbi`, `.eka.care`, except `mcp.eka.care`) skip OAuth (`trusted_host.py`).
- `UsageMiddleware` emits one usage event per tool call (Eka usage SDK).
- Per-workspace doctor, facility and service data for Apollo/RFH/Moolchand comes straight from dev-console's Postgres tables (`datasets_doctor`, `datasets_facility`, `datasets_service`) through `PGRepository`.

## Where to change what
| Goal | Place |
|---|---|
| Tool for every hospital | SDK `tools/*.py` + service + the `BaseEMRClient` method; implement in `EkaEMRClient` and each client |
| Tool for one hospital | remote `tools/<name>_tools.py` + its client; add to that workspace's allowlist |
| New hospital integration | new client implementing `BaseEMRClient`, register in `workspace_client_dict`, tool allowlist, workspace id mapping |
| New card/flow | elicitation response in a client method; keep the `_meta.schema` contract |
