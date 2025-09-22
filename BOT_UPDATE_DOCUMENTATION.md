# AVAP Bot Update Documentation

Version: 1.0.2
Date: 2025-09-22

## Overview
This document consolidates current features, recent fixes, known gaps, exact testing steps, deployment notes, and admin help. Use this as the single source of truth for validating the bot end-to-end.

## Admin Help Summary
Send `/help` (admin only) to see key commands in Telegram. It lists core, admin, and student commands with notes.

## Recent Fixes
- Added safe DB migration to ensure `submissions.content_type` and `submissions.content` columns exist to fix runtime error in `/get_submission`.
- Implemented admin-only `/help` command listing all features and commands.
- Daily Tips and FAQ schedulers are initialized during startup with logs.

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


