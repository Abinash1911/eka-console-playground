# Project: WhatsApp agent + Eka Scribe (Diabetica digital clinic)

Separate from the voice and carousel work. Goal: connect the WhatsApp agent (patient side) with Eka Scribe (doctor side) so a diabetes clinic can run paperless, patient-first, outcome-oriented care. Customer context: Diabetica, "Digital Clinic Patient Journey" deck (13 slides, Health OS).

## Status (2026-11-03)
Discovery. No code. Next: discuss the open questions in `gap-map.md`, decide what Scribe builds, then slice patches. Repos to read before building: eka-care Scribe repos (not yet read), doot, matrix, echo, dev-console, developer.eka.care APIs. Confidence of the API table: read from developer.eka.care on 3 Nov 2026, not tested.

## The journey (from the deck)
Three promises: paperless, patient first, outcome oriented. Diabetes is managed over years, so what happens between visits matters as much as the visit.

| # | Step | What happens | Who does it |
|---|---|---|---|
| 1 Contact | Patient books on WhatsApp; agent offers slots; appointment lands in the doctor's queue; confirmation and reminder | Agent, EMR |
| 2 Before | Short intake (symptoms, medicines, diet); old lab reports and prescriptions uploaded and read into values (HbA1c, lipids); doctor opens one summary | Agent, Scribe record |
| 3 Arrival | Desk checks in against the booking; enters weight, BP, glucose; live queue | Desk, Scribe (no agent step) |
| 4 Consult | Doctor starts Scribe; it drafts note and prescription using intake, reports, vitals, past visits; doctor confirms | Scribe (no agent step) |
| 5 Plan | Digital prescription, diet chart and advice in one plan; follow-up and repeat tests booked; plan sent on WhatsApp and saved in the patient app | Scribe, then agent sends |
| 6 Between | Reminders on WhatsApp with replies recorded; patient logs glucose, weight, BP; out-of-target values flagged; patient asks about own reports | Agent, Scribe record |
| 7 Review | HbA1c, glucose, weight, BP as trends vs last targets; plan adjusted and documented; clinic-wide view | Scribe (no agent step) |

Clinic adoption order in the deck: 1) queue and WhatsApp booking, 2) Scribe in the consult room, 3) records and reports online, 4) trackers and trend reviews.

## Decisions so far (from the discussion notes on the diagram)
- Out of scope: documenting the plan change at review (step 7); clinic-wide view across patients (step 7).
- Mobile number is always required for patient communication; if absent, identify by UHID or generate one.
- Diet chart and advice can go through the EMR's attach-documents feature for now.

## Source files (not stored here)
The deck and the diagram are customer and internal material: kept out of this repo. Originals: `Diabetica_Digital_Clinic_Patient_Journey_1.pptx` and the "Scribe handoffs and the Eka APIs behind each step" diagram (shared in chat 2026-11-03). Everything needed is transcribed in this folder.
