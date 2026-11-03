# Handoffs and API gaps per step

Legend: ✔ documented API exists, ◐ exists with a caveat, ✗ no API found. Scribe boxes: **to build** (red in the diagram) or **partly there** (amber). Source: developer.eka.care read on 3 Nov 2026, **not tested**, label **partial** (docs read, no calls made).

## 1 Contact: agent ↔ EMR → Scribe doctor's queue (to build)
Handoffs: agent sends mobile number; EMR returns linked patients; agent sends chosen patient + slot; EMR returns booked slot; EMR sends the appointment to Scribe's queue.
- ✔ GET `/dr/v1/business/patients/search?mobile=` (patients on a number)
- ✔ POST `/dr/v1/patient` (add another person; needs gender and dob or age)
- ✔ GET `/dr/v1/doctor/{id}/clinic/{id}/appointment/slot` (open slots)
- ✔ POST `/dr/v1/appointment` (book; no reason field, use notes)
- ✔ Webhooks `appointment.created`, reminders; register via POST `/notification/v1/connect/webhook/subscriptions`
- ◐ Search by mobile: unclear if every profile shares the number
- Discussion: if no mobile number, identify by UHID or generate one; always keep a mobile number; which doctor: does the patient choose or do we offer?

## 2 Before: agent → Scribe patient record (partly there)
Handoff: intake answers + report files.
- ✔ POST `/mr/api/v1/docs` (store a report; patient OID in `X-Pt-Id`)
- ✔ POST `/mr/api/v2/docs?task=smart&dt=ir` (parse a lab report)
- ✔ GET `/mr/api/v1/docs/{id}/result` (values, units, LOINC)
- ◐ Prescriptions are not parsed, only lab reports
- ✗ Intake form: no API found; Assessment APIs may fit, to confirm
- ◐ Doctor summary: Scribe `context` document (POST `/voice/api/v1/documents`); shown to the doctor?
- Discussion: where to store intake and past reports; what the summary contains (intake alone or past reports too); where to show it in the Scribe interface.

## 3 Arrival: no agent handoff; queue and vitals (to build)
- ◐ GET `/dr/v1/appointment` shows status CK (checked in) and PA (parked)
- ✗ Mark checked in: no documented API (change-status shows NS only)
- ✔ PATCH `/trackers/api/v1/vitals/{txn_id}` (write; glucose shown, weight and BP unconfirmed)
- ✗ Read vitals: no API
- ✔ Webhook label `vital_submitted` on the appointment
- Discussion: how is vital intake done today; leave as is or change?

## 4 Consult: no agent handoff; Scribe consult (partly there)
- ✔ POST `/voice/v1/sessions` (patient_details, templates, language)
- ✔ POST `/voice/v1/sessions/{id}/audio/{n}`, or a WebSocket stream
- ✔ POST `/voice/v1/sessions/{id}/end`; GET `/voice/v1/sessions/{id}`
- ✔ List Templates; PATCH session; Upload Transcript; Get Session History
- ✔ POST `/dr/v1/appointment/{id}/complete`
- ◐ No context or appointment field on create: carry `appointment_id` and context in `additional_data`
- Discussion: template prompting needed for Diabetica's longitudinal care.

## 5 Plan: Scribe plan (to build) → agent
Handoff: confirmed plan (Rx, diet chart, follow-up, tests) to the agent.
- ✔ GET `/dr/v1/prescription/{id}` (medicines, lab tests, advices, follow-up date)
- ✔ Webhook `prescription.created` gives `prescription_url` for the agent to send
- ✔ PUT `/dr/v1/appointment/{id}/follow-up/confirm`; POST `/dr/v1/appointment` for a new one
- ◐ Diet chart: only free-text advices, no diet field
- ✗ Test orders: no API, only lab tests inside the prescription
- ✗ One combined plan document: no API
- Discussion: use the EMR's attach-documents feature (or the doctor's tool) for the diet chart and advice; need a workflow/agentic flow for follow-up reminders and repeat tests; if the patient does not book at the desk, the agent can book it on WhatsApp.

## 6 Between: agent ↔ Scribe readings and record (to build)
Handoffs: agent sends replies + readings; Scribe sends reminder times, targets, patient record.
- ✔ GET `/dr/v1/prescription/{id}` for reminder timings; follow-up reminder webhook
- ✔ PATCH `/trackers/api/v1/vitals/{txn_id}` (patient readings)
- ✔ GET `/mr/api/v1/docs` (list records, metadata only)
- ◐ Record Q&A: prescriptions and parsed reports readable, vitals not
- ✗ Read readings, set targets, flag out-of-target: no API
- ✗ WhatsApp channel: the Notify API is app push only
- Discussion: is fetching vitals readings required? Flagging out-of-target is only possible in Scribe's record section, so all data the WhatsApp agent collects must go into records, and be fetched from there and shown in Scribe. Answering patients' questions on their records means reading all their reports: could be expensive.

## 7 Review: no agent handoff; Scribe review (to build)
- ✗ Trends of HbA1c, glucose, weight, BP: no vitals read API; lab values only per parsed report
- ✗ Last targets: no API
- ✔ Plan change: a new Scribe session and prescription (steps 4 and 5 APIs)
- ✗ Clinic-wide view: Get Appointments is 7-day windows only
- Out of scope: documenting the plan change; clinic-wide view across patients.

## Open questions to settle first (ranked by what blocks building)
1. Where do WhatsApp-collected readings and intake live (Scribe record section?), and which API writes them? (steps 2, 6, 7)
2. Mark-as-checked-in and read-vitals APIs: build or work around? (step 3)
3. Who sets and stores targets, and who flags out-of-target? (steps 6, 7)
4. Diet chart and combined plan: attach-documents for now? (step 5)
5. Cost of record Q&A over all reports (step 6).
6. Doctor choice and UHID rules at booking (step 1).
