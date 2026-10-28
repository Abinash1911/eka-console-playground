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
| Dataset KBs (doctor, facility, service, medication, lab) with CSV import | exists | dev-console `datasets/` |
| Document KB retrieval (Bedrock, Weaviate) | exists | echo retrievers, matrix `agent_utils.py` |
| Document KB ingestion (clinic uploads FAQs) | unknown | not found in dev-console, matrix or echo; console upload UI is stale |
| Triage tool | exists | echo `triage_tool.py` |
| Vitals retriever | exists | echo |

## Messaging
| Capability | Status | Source |
|---|---|---|
| Reminder scheduler (WhatsApp templates via jugaad) | partial | echo; used for checkup reminders only |
| Appointment / follow-up / vaccination reminder webhooks | exists | developer.eka.care |
| Nudges (per page text, delay, expiry) | exists | synapse-sdk embed + matrix endpoint |
| Human handoff | missing (search-level) | none found |

## Money
| Capability | Status | Source |
|---|---|---|
| Payment status by transaction ID | exists | developer.eka.care Payments API |
| Invoices and payments | partial | IPD (inpatient) billing APIs only |
| Prepaid vs postpaid read from doctor service | missing (search-level) | no code reads it; test in sandbox |
| Pay-in-chat (payment link) | missing | needs a gateway; unknown which |

## Widget (synapse-sdk)
| Capability | Status | Source |
|---|---|---|
| Floating, full page, side panel modes | exists | main |
| Centered mode (search bar + dialog) | built, not pushed | `centered-widget.zip` |
| Configurable floating size | PR open | synapse-sdk PR 214 |
| Skills (prompt packs with tool/KB deps) | exists | dev-console `Skill`, matrix `skills_runtime` |
