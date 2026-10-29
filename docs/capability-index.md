# Capability index

Question it answers: "do we already have X?" Status: **exists**, **partial**, **missing**, **unknown**. Source says where it was seen. Update when you learn more; "missing" needs a file-level read, not a search.

## Patient actions (MCP tools, eka-mcp-sdk)
| Capability | Status | Source |
|---|---|---|
| Book / cancel / reschedule appointment | exists | `appointment_tools.py` |
| Video or audio consult booking (creates video link) | exists | `eka_emr_client.py` (VIDEO mode via Horus) |
| Slots and available dates | exists | `appointment_tools.py` |
| Patient search, add, update, vitals, benefits | exists | `patient_tools.py` |
| Medical records: list, get, upload, delete | exists | `records_tools.py` |
| Prescription details (by prescription ID) | partial | `prescription_tools.py`; no list-by-patient found |
| Doctor / clinic profile, services | exists | `doctor_clinic_tools.py` |
| ABHA login (OTP) | exists | `abha_tools.py` |
| CRM lead | exists | `extra_tools.py` |

## Search and knowledge (echo + matrix)
| Capability | Status | Source |
|---|---|---|
| Doctor / facility / service search, city and specialization lists | exists | echo `tools/datasets/` |
| Dataset KBs (doctor, facility, service) as agent tools | exists | matrix `config/tool.py` (`_DATASET_TOOL_CLASSES`) |
| Formulary datasets: drugs, symptoms, diagnoses, lab tests/investigations/results/panels | exists, not for chat | dev-console `datasets/`: serve doctor-side EMR partner search (with a search switch and an Elasticsearch sync for labs), not agent tools; matrix correctly ignores them |
| Document KB retrieval (Bedrock, Weaviate) | exists | echo retrievers, matrix `agent_utils.py` |
| Document KB ingestion (clinic uploads FAQs) | unknown | echo-sdk says a "separate pipeline" indexes the corpus; not found in dev-console, matrix, echo or echo-sdk; console upload UI is stale. Record schema it must write is known (see ecosystem map) |
| Triage tool (also sends a checkup reminder) | exists | echo `triage_tool.py`; attach as a custom tool [to verify] |
| Patient vitals retriever | exists in echo, not wired by default | echo `patient_vitals_retriever.py`; matrix only auto-adds `elicit_selection`; needs a custom-tool row [to verify] |
| Multi-step card/pills flows with callbacks (template for booking or payment cards) | exists | echo `pharmacy_tool.py`, `selection_tool.py` |

## Messaging
| Capability | Status | Source |
|---|---|---|
| Delayed callbacks via Jugaad (generic scheduler) | exists | echo `reminder_scheduler.py`; only the checkup reminder uses it today |
| Appointment / follow-up / vaccination reminder webhooks | exists | developer.eka.care |
| Nudges: manual per-page rules (wildcards) | exists | matrix `nudge_utils.py` (`source = manual`) |
| Nudges: LLM-generated from page meta tags (Haiku 4.5), cached | exists | matrix `nudge_service.py` (`nudge_type = llm`) |
| Nudge popup / centered-bar text | exists | synapse-sdk embed |
| Send a WhatsApp template (relay to doot) | exists | matrix `POST notifications` |
| Human handoff | missing (search-level) | none found |

## Money
| Capability | Status | Source |
|---|---|---|
| Payment status by transaction ID | exists | developer.eka.care Payments API |
| Invoices and payments | partial | IPD (inpatient) billing APIs only |
| Prepaid vs postpaid read from doctor service | not found | no code in any connected repo reads it |
| Pay-in-chat (payment link) | not found | Moolchand client returns "make payment to confirm" from the hospital system; no link builder or gateway call in any connected repo |

## Widget (synapse-sdk)
| Capability | Status | Source |
|---|---|---|
| Floating, full page, side panel modes | exists | main |
| Centered mode (search bar + dialog) | built, not pushed | `centered-widget.zip` |
| Configurable floating size | PR open | synapse-sdk PR 214 |
| Skills (LLM-activated prompt packs; instructions live in Langfuse; tools hidden until loaded) | exists | echo-sdk `skills/`, dev-console `Skill`, matrix `agent_service.py` |

## Platform (matrix)
| Capability | Status | Source |
|---|---|---|
| Guest and logged-in sessions, partner (BYOA) login, token refresh | exists | matrix auth, `AUTH_CLIENT_CONTRACT.md` |
| History recovery for logged-in users | exists | matrix `GET session?messages=true` |
| Voice (WebRTC in browser, Vobiz phone line), ElevenLabs STT/TTS, 10 Indian-language codes mapped, same agent/tools as chat, transcript saved | exists | matrix `voice`, `voice_ws`, `service/voice/` |
| Voice: human handover (phone or chat) | missing (partial: search + flow read) | none found; see claims-to-confirm 11 |
| Voice: caller ID used to identify the patient | missing (verified in matrix) | number saved in session only; claims 12 |
| Voice: Sarvam / Deepgram speech | console only, not in matrix | claims 6 |
| Run a named prompt on a category LLM | exists | matrix `run-prompt` |
| Campaigns (override opening message / prompt by `campaign_id`) | exists | matrix `campaign_utils.py` |
| Elicitation (pills, cards) except on voice / WhatsApp | exists | matrix `ELICITATION_UNSUPPORTED_CHANNELS` |
| Per-region data storage | exists | matrix `common/storage` |

## Not chat (echo)
| Capability | Status | Source |
|---|---|---|
| Doctor prescribing memory (EkaScribe suggestions) | exists | echo `agent_memory/scribe` |

## MCP / platform mechanics
| Capability | Status | Source |
|---|---|---|
| One tool, per-hospital client (Eka EMR, Apollo, RFH, Moolchand, Eternal, Sukino) | exists | eka-mcp-sdk `ClientFactory`, eka-remote-mcp `clients/` |
| Per-workspace tool allowlist | exists | `workspace_tools_dict`, `DEFAULT_EKAEMR_REMOTE_TOOLS` |
| In-chat mobile OTP login + UHID pick | exists | each client's `authentication_elicitation` |
| Custom tools attachable from the console (class path under `echo_agents.tools`) | exists | dev-console `Tool.tool_type=custom`, matrix `load_custom_tool` |
| Agent create/update through an API | exists | dev-console `/api/agents/` |
| WhatsApp number management and templates through an API | exists | dev-console `/api/integrations/`, `/api/product-integrations/`, templates |
| Scheduled HTTP request from a tool (Jugaad) | exists | eka-remote-mcp `scheduled_request.py` |
| Consent gate on WhatsApp | exists | doot `consent.py` |
| Resume a chat after a template message | exists | doot `template_session.py` |
| Voice agent (WebRTC, telephony) | exists | matrix `service/voice/` |
| Per-agent data region | exists | `agent_details.region`, matrix regions |
