# Claims to confirm with a developer

Things read from code that we plan to build on. Mark each confirmed or corrected by a developer. Until then they are **partial** or **inference**, not facts.

| # | Claim | Confidence | Basis | Ask |
|---|---|---|---|---|
| 1 | No pipeline in any connected repo indexes clinic documents into Weaviate/Bedrock | partial | searched and read dev-console, matrix, echo, echo-sdk, doot | Who indexes the corpus, and with what code? |
| 2 | No code reads a doctor service's prepaid/postpaid flag | partial | searched mcp-sdk, remote-mcp, matrix, echo, doot, dev-console | Does the EMR API expose it? Where? |
| 3 | No list-prescriptions-by-patient API exists | partial | SDK clients and developer.eka.care index | Is there an endpoint? |
| 4 | Formulary datasets (drugs, labs, symptoms, diagnoses) serve EMR partner search only, not chat | verified (producer and consumer read) | dev-console `datasets/`, matrix `config/tool.py` | Confirm no plan to expose them to agents |
| 5 | Vitals and triage tools can be attached from the console as custom tools | inference | `Tool.tool_type=custom` + matrix `load_custom_tool`; UI not inspected | Does the console UI offer them? |
| 6 | Matrix voice config accepts only ElevenLabs while the console offers Deepgram and Sarvam | verified (both ends read: matrix `VoiceAgentConfig` Literal["elevenlabs"], dev-console `VoiceAgentConfig` allows three) | matrix `models/agent_config.py`, dev-console `agents/schemas/voice.py` | Is it intended? What does a call do if Sarvam is saved (not read)? |
| 7 | A hospital client's booking can return a payment step (Moolchand) but no link is built in our code | partial | `moolchand_client.py` | How do other hospitals handle payment? |
| 8 | Doot and scribesnap are the same service | verified | doot commit "scribesnap renamed to Doot" | none |
| 9 | Doot's Interakt signature check matches what Interakt sends | verified (live test 2026-10-29: new integration with the copied secret received and answered messages) | doot `interakt_provider.verify_signature` | none; the first integration's saved secret was wrong |
| 10 | The console has no way to see or edit a saved webhook secret | verified (console page read) | `integration/schemas/whatsapp/interakt.py` (Public is empty), `integration_update` changes name only | Should there be an edit path? |
| 11 | Voice: no human handover exists (phone transfer or chat inbox) | partial (search of 8 repos for handover/transfer/escalate + full read of the voice call flow) | matrix `service/voice/pipeline.py`, `router/voice.py` | Does Vobiz support forwarding a live call? How does the Messenger inbox connect to agents? |
| 12 | Voice: caller ID is saved in the session but never used to identify the patient or sent to tools; the `voice` header sent to the tool server is read by nothing found | verified in matrix (grep of `med_assist`), partial for the tool repos (search only) | matrix `router/voice.py`; `utils/agent_utils.py`; eka-remote-mcp | Confirm no tool server reads it |
| 13 | Voice: dev-console stores a separate voice prompt (`voice_prompt_config`) that matrix never reads | verified by search (no match in all of matrix; dev-console writes it) | dev-console `agents/models.py`; matrix `utils/agent_config_utils.py` | Intended? Which prompt do calls use? (the chat prompt plus fixed medical-assistant voice rules) |
| 14 | Voice: telephony looks dormant (open `/answer`, unauthenticated socket, "if telephony is revived" comments, console telephony channel is a stub) | partial (code comments, no production data) | matrix `router/voice.py`, `router/voice_ws.py`; dev-console `integration/schemas/__init__.py` | Is Vobiz live in production? |
