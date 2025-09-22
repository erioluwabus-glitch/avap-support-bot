# AVAP Bot Update Documentation

Version: 1.0.2
Date: 2025-09-22

## Overview
This document consolidates current features, recent fixes, known gaps, exact testing steps, deployment notes, and admin help. Use this as the single source of truth for validating the bot end-to-end.

## Executive Summary (Problems • Actions • Results)
- Problems observed (from live tests and logs):
  - Share Win: "Text" option previously not responding; media intake reliability concerns.
  - Remove Student: "Confirm Removal" button not responding; needs email/name lookup not Telegram ID.
  - Get Submission: Command expected username + module, but code used submission_id; also runtime error: no such column: content_type.
  - Multi-language: `/setlang` saved but outgoing messages still English; translation not applied globally.
  - AI FAQ Helper: Similar-question reuse not working; unanswered draft pipeline unverified due to time.
  - Voice Transcription: User tried Yoruba; got "Failed to transcribe voice message"; unclear testing path; Sheets not logging.
  - Google Sheets: Startup log shows it’s skipped due to missing config or packages.
  - Render deploy: Python 3.13 incompatibilities (SQLAlchemy), setuptools/wheel missing, missing Application imports.
- Actions taken so far:
  - Fixed many syntax/indentation issues; consolidated grading into a single ConversationHandler.
  - Corrected callback patterns for Remove Student and Share Win; registered all feature handlers; added missing imports.
  - Added DB migration to ensure `submissions.content_type` and `submissions.content` columns exist (fixes `/get_submission` error).
  - Implemented admin-only `/help` command listing all features and commands.
  - Pinned Python to 3.11.10 (`runtime.txt`), pinned `sqlalchemy==2.0.43`, added `setuptools` and `wheel` to requirements.
  - Added `gspread` and Google auth packages to requirements.
- Results right now:
  - Bot builds and starts on Render; schedulers initialize; webhook endpoint ready.
  - Broadcast reported working. Grading flow refactor is in place.
  - `/get_submission` crash resolved via migration. `/help` available to admins.
  - Still to validate: Share Win all media types; multi-language on all outgoing messages; AI FAQ similar-answer reuse; voice transcription and Sheets logging; remove student full Systeme.io deprovisioning; get submission by username+module.

## Admin Help Summary
Send `/help` (admin only) to see key commands in Telegram. It lists core, admin, and student commands with notes.

## Recent Fixes
- Added safe DB migration to ensure `submissions.content_type` and `submissions.content` columns exist to fix runtime error in `/get_submission`.
- Implemented admin-only `/help` command listing all features and commands.
- Daily Tips and FAQ schedulers are initialized during startup with logs.

## Detailed Problem Log and Status
1) Share Win (text/image/video)
   - Problem: "Text" option previously did not respond. Reliability for all media types uncertain.
   - Action: Updated conversation handlers and patterns; ensured `WIN_UPLOAD` accepts `filters.TEXT`, `filters.PHOTO`, `filters.VIDEO` in DM.
   - Current Result: Needs re-test end-to-end to confirm state transitions and DB writes.

2) Remove Student (confirm + identifier)
   - Problem: "Confirm Removal" button didn’t respond; user wants email/name, not Telegram ID. Should deprovision from Systeme.io and bot.
   - Action: Fixed callback pattern to match `confirm_remove`; implemented enhanced flow with reason capture; soft delete + Systeme.io hooks present.
   - Current Result: Button now wired; full deprovision (Systeme.io tag removal + notifications) needs validation.

3) Get Submission (username + module vs submission_id)
   - Problem: Admin UX prefers lookup by username+module; runtime error encountered: `no such column: content_type`.
   - Action: Added migration for `content_type` and `content` columns; retained current command using submission_id.
   - Current Result: Crash fixed; UX improvement (username+module) planned next.

4) Multi-language (`/setlang`)
   - Problem: After setting French, responses remained English; translation not applied globally.
   - Action: Translator utilities exist; need to route all outgoing messages through translation with user’s preferred language.
   - Current Result: Pending integration sweep across handlers.

5) AI-powered FAQ Helper (similar-question reuse)
   - Problem: Similar questions are not auto-answered using previous answers.
   - Action: Base AI draft flow added; need similarity matching (e.g., normalized text + cosine/ratio) and answer reuse cache.
   - Current Result: Pending implementation and tests.

6) Voice Transcription (Whisper + Sheets)
   - Problem: "Failed to transcribe" seen for Yoruba; unclear test path; Sheets not logging.
   - Action: Voice handler present; `download_and_transcribe_voice` and `save_transcription_to_sheets` need robustness and clearer errors.
   - Current Result: Pending robusting, better messages, and Sheets configuration.

7) Google Sheets
   - Problem: Startup logs: "Google Sheets not configured or gspread not installed; skipping."
   - Action: Requirements updated; add checks; document configuration.
   - Current Result: Needs environment configuration and sheet sharing to enable logging.

## Google Sheets Not Recording
Logs show: "Google Sheets not configured or gspread not installed; skipping." Ensure:
- `gspread`, `google-auth`, `google-auth-oauthlib` installed (requirements updated).
- `GOOGLE_CREDENTIALS_JSON` is set with valid service account JSON.
- The service account email has Editor access to the target sheet.

## Feature Matrix and How to Test
- Verification: `/start` → Verify Now → enter name/phone/email → check Systeme.io and Sheets.
- Add Student: `/add_student` flow → verify DB and Systeme.io.
- Remove Student: `/remove_student <email|name>` → Confirm → Reason → check soft delete, Systeme.io, and DM.
- Submit Assignment: DM → "📤 Submit Assignment" → choose module → choose type (text/image/video/audio) → send → verify DB and Sheets.
- Grade: `/get_submission <submission_id>` → follow inline steps.
- Share Win: DM → "🎉 Share Small Win" → choose type → send → verify DB and Sheets.
- Ask/Answer: `/ask` (group or DM) → verify forwarding and answer flow.
- Badging: After 3 wins + 3 submissions → verify achiever tag and status.
- Daily Tips: Scheduler posts 08:00 WAT to support group; `/add_tip` to seed tips.
- AI FAQ Helper: Unanswered question triggers draft after timeout; verify in group and DM.
- Broadcast: `/broadcast <message>` (admin) → verify throttled DMs.
- Multi-language: `/setlang <code>` → verify responses translated.
- Voice Transcription: Send voice; verify text response and Sheets log.
- Group Matching: `/match` join → `/match_status` to view/admin controls.

## Known Gaps Needing Attention
- Share Win: Ensure all three input types are accepted reliably in DM state.
- Answer Similarity: Improve similar-question matching and reuse previous answers.
- Remove Student: Ensure email/name lookup works for all cases and Systeme.io tag removal.
- Get Submission: Future change to lookup by username + module.
- Multi-language: Ensure translation applied to all outgoing texts via utils translator.
- Voice Transcription: Ensure Whisper call and Google Sheets logging are robust.

## Failed Results (What didn’t work yet)
- Similar question auto-answer: not triggered; no prior answer reuse observed.
- Multi-language propagation: messages still English after `/setlang`.
- Voice transcription: failed for a Yoruba test; needs verification of Whisper and language handling.
- Remove Student full deprovision: pending validation for Systeme.io and notifications.
- Share Win full coverage: needs validation for text, image, and video on the same run.

## Environment Variables
- ADMIN_IDS, BOT_TOKEN, WEBHOOK_SECRET, SUPPORT_GROUP_ID, QUESTIONS_GROUP_ID
- SYSTEME_IO_API_KEY, SYSTEME_VERIFIED_STUDENT_TAG_ID
- OPENAI_API_KEY, WHISPER_ENDPOINT
- UNANSWER_TIMEOUT_HOURS, DAILY_TIP_HOUR, DEFAULT_LANGUAGE, DAILY_TIPS_TO_DMS, MATCH_SIZE
- GOOGLE_CREDENTIALS_JSON, GOOGLE_SHEETS_SPREADSHEET

## Deployment Notes (Render)
- Python runtime pinned via `runtime.txt` to 3.11.10.
- Requirements pin for SQLAlchemy and addition of gspread/auth packages.
- After deploy, set webhook via exposed endpoint if not auto-set.

## Testing Checklist
Use `COMPLETE_FEATURE_CHECKLIST.md` for full step-by-step tests. Prioritize:
1) Verification and Sheets
2) Submit/Grade flows
3) Share Win
4) Ask/Answer and AI drafts
5) Badging
6) Daily Tips
7) Broadcast
8) Multi-language
9) Voice Transcription
10) Group Matching

## Troubleshooting
- If a callback button does not respond, confirm ConversationHandler patterns and ensure `per_message=False` is acceptable for your flow.
- For DB errors, confirm schema migrations in startup logs and check `bot.db` with a SQLite viewer.
- For Sheets, confirm credentials env var is valid JSON and sheet sharing is correct.

## Next Actions Proposed
- Finalize multi-language integration on all outbound messages.
- Strengthen FAQ similarity matching and caching of answers.
- Improve `/get_submission` to support username + module lookup.
- Add admin command to re-sync a student with Systeme.io.

## Open Questions (For Your Suggestions)
- Multi-language coverage: which message groups to prioritize for translation first?
- FAQ similarity: acceptable threshold and tie-breaking rules when multiple similar answers exist?
- Voice transcription: languages to explicitly support and the desired sheet fields?
- Remove Student: confirmation copy and default deprovisioning policy (soft-delete vs full delete)?



