# Claims to confirm with a developer

Things read from code that we plan to build on. Mark each confirmed or corrected by a developer. Until then they are **partial** or **inference**, not facts.

| # | Claim | Confidence | Basis | Ask |
|---|---|---|---|---|
| 1 | No pipeline in any connected repo indexes clinic documents into Weaviate/Bedrock | partial | searched and read dev-console, matrix, echo, echo-sdk, doot | Who indexes the corpus, and with what code? |
| 2 | No code reads a doctor service's prepaid/postpaid flag | partial | searched mcp-sdk, remote-mcp, matrix, echo, doot, dev-console | Does the EMR API expose it? Where? |
| 3 | No list-prescriptions-by-patient API exists | partial | SDK clients and developer.eka.care index | Is there an endpoint? |
| 4 | Formulary datasets (drugs, labs, symptoms, diagnoses) serve EMR partner search only, not chat | verified (producer and consumer read) | dev-console `datasets/`, matrix `config/tool.py` | Confirm no plan to expose them to agents |
| 5 | Vitals and triage tools can be attached from the console as custom tools | inference | `Tool.tool_type=custom` + matrix `load_custom_tool`; UI not inspected | Does the console UI offer them? |
| 6 | Matrix voice config accepts only ElevenLabs while the console offers Deepgram and Sarvam | inference | model Literal vs console schema | Is that intended? |
| 7 | A hospital client's booking can return a payment step (Moolchand) but no link is built in our code | partial | `moolchand_client.py` | How do other hospitals handle payment? |
| 8 | Doot and scribesnap are the same service | verified | doot commit "scribesnap renamed to Doot" | none |
| 9 | Doot's Interakt signature check (`HMAC-SHA256(secret, raw body)`, header `Interakt-Signature: sha256=<hex>`) matches what Interakt really sends | partial | doot `interakt_provider.verify_signature`; Interakt guides via search (official pages not reachable) | A real case: an integration with the Interakt secret filled in got no events; the same API key with the secret empty worked. Is the stored secret wrong, or does the check differ from Interakt's signing? |
| 10 | The console has no way to see or edit a saved webhook secret | verified (console page read) | `integration/schemas/whatsapp/interakt.py` (Public is empty), `integration_update` changes name only | Should there be an edit path? |
