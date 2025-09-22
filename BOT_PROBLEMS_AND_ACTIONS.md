# AVAP Bot — Problems and Actions Log

Version: 1.0.3 (living log)
Date: 2025-09-22

Purpose: Single source of truth listing every problem we’ve faced, evidence, root causes, actions taken, current status, and next steps. Keep this updated after each test/deploy.

---

## Index
- 1. Share Win (text/image/video)
- 2. Remove Student (confirm + identifier + Systeme.io)
- 3. Get Submission (lookup + schema)
- 4. Multi-language (/setlang)
- 5. AI FAQ Helper (similar question reuse)
- 6. Voice Transcription (Whisper + Sheets)
- 7. Google Sheets (gspread/credentials)
- 8. Render Deployment (Python, wheels, imports)
- 9. Grading (ConversationHandler)
- 10. Verify Student (Systeme.io resiliency)
- 11. Add Student (Systeme.io tagging)
- 12. Badging (3 wins + 3 submissions)
- 13. Daily Tips (scheduler)
- 14. Broadcast (admin)
- 15. Study Group Matching

Legend: Status = Pending / Fixed / To Validate / Monitoring

---

## 1) Share Win (text/image/video)
- Symptom: Text option not responding; uncertainty on media intake state.
- Evidence: User reports; earlier handler patterns didn’t include `filters.TEXT` in state.
- Root Cause: Conversation state patterns missing text handler; potential overlap with other handlers.
- Actions Taken:
  - Added `WIN_UPLOAD` handlers for `filters.TEXT`, `filters.PHOTO`, `filters.VIDEO` (DM-only).
  - Verified patterns for `win_type_callback`.
- Status: To Validate
- Next Steps: Full E2E test; confirm DB writes and Sheets logging.

## 2) Remove Student (confirm + identifier + Systeme.io)
- Symptom: "Confirm Removal" button not responding; require email/name instead of Telegram ID; ensure deprovision.
- Evidence: Callback not matched by pattern.
- Root Cause: Callback pattern mismatch; incomplete flow for flexible identifiers and Systeme.io operations.
- Actions Taken:
  - Fixed `CallbackQueryHandler` pattern to include `confirm_remove`.
  - Implemented enhanced flow: confirmation → reason capture → soft delete; Systeme.io helpers in place.
- Status: To Validate
- Next Steps: Validate tag removal/contact update in Systeme.io; DM notifications; Sheets entry of removal.

## 3) Get Submission (lookup + schema)
- Symptom: Runtime error: `sqlite3.OperationalError: no such column: content_type`.
- Evidence: Render logs showing exception in `/get_submission` query.
- Root Cause: Schema drift; older schema lacked `content_type` and `content` columns.
- Actions Taken:
  - Safe DB migration in `init_db()` to add missing columns.
  - Kept current `/get_submission <submission_id>`; plan username+module variant.
- Status: Fixed (migration); UX: Pending
- Next Steps: Add `/get_submission @username M1` lookup path; update docs/tests.

## 4) Multi-language (/setlang)
- Symptom: After setting French, replies still English.
- Evidence: User test.
- Root Cause: Translation utility present but not applied across all outgoing messages.
- Actions Taken:
  - Documented integration plan; translation utilities ready.
- Status: Pending
- Next Steps: Sweep handlers to route texts through `utils/translator.translate()` with `get_user_language()`.

## 5) AI FAQ Helper (similar question reuse)
- Symptom: Similar questions don’t reuse prior answers; drafts not verified due to time.
- Evidence: User test feedback.
- Root Cause: Similarity/caching not implemented; only base draft pipeline exists.
- Actions Taken:
  - Scheduling set; placeholders for OpenAI draft; plan for similarity (normalized text + ratio/cosine).
- Status: Pending
- Next Steps: Implement similarity index and reuse; unit tests; admin review flow.

## 6) Voice Transcription (Whisper + Sheets)
- Symptom: "Failed to transcribe" for Yoruba; unclear how to test; no Sheets logging.
- Evidence: User test feedback; placeholder `save_transcription_to_sheets`.
- Root Cause: Whisper call/format handling and Sheets write robustness not finalized.
- Actions Taken:
  - Voice handler wired; utils prepared.
- Status: Pending
- Next Steps: Harden `download_and_transcribe_voice` error paths; implement Sheets writer; add user guidance; re-test Yoruba.

## 7) Google Sheets (gspread/credentials)
- Symptom: Startup: "Google Sheets not configured or gspread not installed; skipping."
- Evidence: Startup logs.
- Root Cause: Missing packages or invalid/missing `GOOGLE_CREDENTIALS_JSON` or sharing.
- Actions Taken:
  - requirements.txt includes `gspread`, `google-auth`, `google-auth-oauthlib`.
  - Added configuration notes and checks.
- Status: Pending
- Next Steps: Set `GOOGLE_CREDENTIALS_JSON` (valid JSON), share sheet with service account (Editor), set `GOOGLE_SHEETS_SPREADSHEET`.

## 8) Render Deployment (Python, wheels, imports)
- Symptom: Build failures (SQLAlchemy pin, setuptools/wheel missing), NameError: Application not defined.
- Evidence: Render logs.
- Root Cause: Python 3.13 incompatibilities; missing build tooling; missing imports.
- Actions Taken:
  - `runtime.txt` pinned to Python 3.11.10.
  - requirements: `sqlalchemy==2.0.43`, `setuptools`, `wheel`.
  - Added missing `Application` imports in feature modules.
- Status: Fixed; Monitoring
- Next Steps: Monitor future deploys; keep pins updated.

## 9) Grading (ConversationHandler)
- Symptom: Comments not acknowledged; assignment not graded in early tests.
- Evidence: User report; earlier fragmented handlers.
- Root Cause: Handler conflicts and state management issues.
- Actions Taken:
  - Refactored into a single `ConversationHandler` with explicit states and media handlers.
- Status: To Validate (user later reported working)
- Next Steps: Re-run tests including audio/video comments; confirm DB updates and notifications.

## 10) Verify Student (Systeme.io resiliency)
- Symptom: Duplicates/tagging failures/latency possible.
- Evidence: Prior behavior/feedback.
- Root Cause: Non-async calls, no dedupe, limited retries.
- Actions Taken:
  - Async `aiohttp` helpers with retries and contact-by-email checks; tagging verification; admin notify on failures.
- Status: To Validate
- Next Steps: Live tests for duplicate prevention and tag verification; send activation link.

## 11) Add Student (Systeme.io tagging)
- Symptom: Some contacts not added/tagged reliably.
- Evidence: User feedback.
- Root Cause: Same as verify flow resiliency.
- Actions Taken:
  - Use shared Systeme.io helpers; structured retries and verification.
- Status: To Validate
- Next Steps: Test add + tag; check Sheets/DB consistency.

## 12) Badging (3 wins + 3 submissions)
- Symptom: Criteria enforcement uncertain.
- Evidence: User feedback/request.
- Root Cause: Counters and checks not consistently triggered.
- Actions Taken:
  - Hooked badge checks into win and submission flows; added achiever list command.
- Status: To Validate
- Next Steps: Simulate users to 3+3 threshold; validate tag application and status display.

## 13) Daily Tips (scheduler)
- Symptom: Not verified due to time.
- Evidence: User feedback; logs show job scheduled.
- Root Cause: Time-based verification pending.
- Actions Taken:
  - Scheduler jobs registered for 08:00 WAT; `/add_tip` admin command present.
- Status: To Validate
- Next Steps: Force-run job for testing or wait for schedule; verify group and optional DM.

## 14) Broadcast (admin)
- Symptom: Works.
- Evidence: User confirmation.
- Root Cause: N/A
- Actions Taken:
  - Implemented with throttling and error handling.
- Status: Monitoring
- Next Steps: None.

## 15) Study Group Matching
- Symptom: Not fully validated.
- Evidence: Time constraints.
- Root Cause: Pending tests.
- Actions Taken:
  - Matching queue and pairing logic implemented; admin status command added.
- Status: To Validate
- Next Steps: Add 2–3 users; verify pairing and notifications.

---

## Global Next Steps
1) Complete multi-language sweep on all outgoing messages.
2) Implement FAQ similarity + answer reuse cache; add tests.
3) Finish Whisper transcription robustness and Sheets logging.
4) Add `/get_submission @username M#` path; update docs.
5) Validate Remove Student end-to-end with Systeme.io and Sheets.

## Validation Log (to be filled during tests)
- Date/Tester:
  - Scenario:
  - Result:
  - Notes:

---

## Environment/Config Checklist
- GOOGLE_CREDENTIALS_JSON (valid JSON)
- GOOGLE_SHEETS_SPREADSHEET (name or key)
- ADMIN_IDS (comma-separated)
- SYSTEME_IO_API_KEY, SYSTEME_VERIFIED_STUDENT_TAG_ID
- OPENAI_API_KEY, WHISPER_ENDPOINT
- UNANSWER_TIMEOUT_HOURS, DAILY_TIP_HOUR, DEFAULT_LANGUAGE, DAILY_TIPS_TO_DMS, MATCH_SIZE


