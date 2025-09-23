# FINAL FIX - AVAP Support Bot

## Overview
This document details the issues, expected flows, root causes, problematic code areas, final fixes, and testing/debugging steps for the key features. It reflects the latest code on `main` and should be used as the single source of truth.

---

## 1) Verify Student + Systeme.io + Sheets

### Issue Description
- Sheets not updated during add student and verify flows.
- Systeme.io contact creation/tagging intermittently fails (422, non-JSON responses).

### Expected Flow
1. Admin adds student (name, email, phone) → row added to `Verifications` with status `Pending`.
2. Student verifies via DM → `verified_users` updated; `Verifications` row set to `Verified` with `telegram_id`.
3. Systeme.io: contact created/updated; verified tag applied and verified; admin notified on failures.

### Root Cause Analysis
- Sheets: inserts/upserts existed for some paths, but inconsistent and missing in others.
- Systeme.io: client expected JSON for all responses; GET /contacts sometimes returns 422; tags GET may return non-JSON.

### Primary Issue
- Inconsistent Sheets writes and brittle Systeme.io client.

### Problematic Code (before)
```python
# Sheets writes missing in some flows; systeme_api_request assumed JSON always
return await resp.json()
```

### Final Fixes
- Sheets:
  - Add row on add student to `Verifications`.
  - On student verify/admin verify, find rows by email and update status and telegram_id.
- Systeme.io client:
  - Safely handle non-JSON response; return ok with status/text when content-type isn’t JSON.
  - Tolerant contact search; proceed to creation if search fails.

### Technical Details
- File: `bot.py`
  - `systeme_api_request` handles content-type check; returns dict or ok/status.
  - Verify flows update Sheets in `Verifications` worksheet.

### Testing Steps
- Add student → check `Verifications` row added.
- Student verify → `Verifications` row updated with `Verified` and telegram_id.
- Simulate 422/429 → no crash; admin notified.

### Debugging Info
- Logs: look for `Systeme.io API request failed` and `Sheets sync failed` messages.

---

## 2) Submission + Grading + Sheets

### Issue Description
- Sheets not updated after submission and grading.

### Expected Flow
1. Student submits → `Submissions` row appended.
2. Grading → row updated to `Graded`, score/comment populated.

### Root Cause Analysis
- Missing append/update in some handlers.

### Final Fixes
- On submission: append to `Submissions` with core fields.
- On finalize grading: update row status/score/comment (search by `submission_id`), or append if not found.

### Technical Details
- File: `bot.py` → `submit_media_upload`, `finalize_grading`.

### Testing Steps
- Submit; confirm row in `Submissions`.
- Grade; confirm row updated.

### Debugging Info
- Logs prefix: `Failed to append submission to Sheets`, `Failed to update grading info in Sheets`.

---

## 3) Share Win + Sheets

### Issue Description
- Sheets not updated after shared win.

### Expected Flow
- Share win → `Wins` row appended.

### Final Fixes
- Append to `Wins` sheet with `win_id`, `username`, `telegram_id`, `type`, `content`, `created_at`.

### Technical Details
- File: `bot.py` → in `win_receive` after DB commit.

### Testing Steps
- Share each type (text/image/video where applicable) and confirm row in `Wins`.

---

## 4) FAQ Immediate Reuse

### Issue Description
- Repeat questions require manual re-answering.

### Expected Flow
- On `/ask`, if similar question exists in `faq_history`, suggest answer to user immediately; still forward to group.

### Final Fixes
- Added immediate reuse via `find_similar_faq` in `features/faq_ai_helper.py` before storing question.

### Technical Details
- Files: `utils/db_access.py` (faq_history, similarity), `features/faq_ai_helper.py` (immediate reuse).

### Testing Steps
- Ask a question similar to a previous one; bot shows the suggested answer instantly.

---

## 5) Remove Student

### Issue Description
- Confirm removal not working reliably; identifier matching flaky.

### Expected Flow
- `/remove_student` → selection/confirmation → reason → soft-delete; Sheets updated; Systeme.io deprovision; student notified.

### Final Fixes
- Fixed callback/state mapping; normalized identifier lookup (case-insensitive name); robust Systeme.io client usage.

### Technical Details
- File: `bot.py` → `remove_student_*`, `find_student_by_identifier`, `remove_systeme_contact`.

### Testing Steps
- Remove by email/name/ID; confirm deprovision and Sheets updated.

---

## 6) Multi-language (i18n)

### Issue Description
- Set language feature not reflected; bot replies in English.

### Expected Flow
- `/setlang <code>` stores language; subsequent key messages are translated.

### Final Fixes
- Use `reply_translated` for key messages (start, status, auth errors, usage hints, submit/status prompts, etc.).
- Confirm language is read from DB; `features/multilanguage.py` manages setting/reading.

### Technical Details
- Files: `bot.py` (extensive use of `reply_translated`), `features/multilanguage.py` (set/get language).

### Testing Steps
- `/setlang es`; run `/start` and `/status`; confirm messages in Spanish.

---

## 7) Persistence on Redeploy

### Issue Description
- Verified students wiped on redeploy.

### Expected Flow
- Data persists across redeploys.

### Final Fixes
- Default DB path to `/data/bot.db`; ensure directory exists on startup.

### Technical Details
- File: `bot.py` → `DB_PATH`, `init_db()`.

### Testing Steps
- Verify students; redeploy; confirm data is intact.

---

## Appendix: Problematic Code Summary (Before vs After)
- `systeme_api_request`: from strict `await resp.json()` to content-type aware handling.
- Missing Sheets appends/updates → now appended/updated across Submissions/Grading/Wins.
- i18n: switch to `reply_translated` in core flows.

## Appendix: Debugging Tips
- Enable Render logs; search for WARNING/ERROR lines included above.
- Toggle env vars carefully (Systeme.io tags/keys, Sheets credentials, default language).

---

## Latest Deployment Issues (2025-09-22) and How to Resolve

### A) Google Sheets Not Configured (Seen in logs)
- Symptom: `Google Sheets not configured - skipping sync` and no updates to Verifications/Submissions/Wins/FAQ.
- Root Cause: One or more of the required env vars was missing or not parseable.
- Required env vars (Render → Environment):
  - `GOOGLE_SHEET_ID` = the spreadsheet key (the long ID from the URL).
  - `GOOGLE_CREDENTIALS_JSON` = Service Account JSON. You can paste:
    - The raw JSON string, or
    - Base64-encoded JSON (now supported). If base64, set the env var to the base64 string.
- What to do (your side):
  1) Create a Google Cloud Service Account with Sheets access; download JSON.
  2) Share the target spreadsheet with the service account email.
  3) In Render, set the two env vars above; redeploy.
  4) Check startup logs for `Google Sheets connected`.

### B) Systeme.io 415/405 Errors
- Symptoms:
  - `415 Unsupported Media Type` on `/contacts/{id}`
  - `405 Method Not Allowed` on `/contacts/{id}/tags`
- Root Causes (API behavior):
  - Sending `Content-Type: application/json` on methods without a body.
  - Using PATCH where the endpoint expects PUT.
- Fixes implemented in code:
  - Set `Content-Type` only for POST/PUT/PATCH.
  - Use PUT for contact update and tag-add endpoints.
- What to check (your side):
  - `SYSTEME_API_KEY` is valid and active.
  - `SYSTEME_VERIFIED_STUDENT_TAG_ID` is correct and exists.
  - The contact/tag endpoints in your Systeme.io plan support these calls.
  - If tag listing returns non-JSON structures in your account, manual verification may be required.

### C) OpenAI Whisper 429 (Rate/Quota)
- Symptom: `openai.RateLimitError: insufficient_quota` and voice transcription fails.
- Root Cause: The OpenAI account has no remaining quota for Whisper.
- What to do (your side):
  - Add billing/credits to the OpenAI account or switch to a custom `WHISPER_ENDPOINT` (compatible API).
  - Set `OPENAI_API_KEY` in Render; confirm quota at OpenAI dashboard.
  - The code now fails gracefully if 429; transcription will resume once quota is available.

### D) Health Check 405 on HEAD
- Symptom: `HEAD /health 405` during boot.
- Explanation: The app defines GET /health and GET /; some Render probes use HEAD. This is harmless once the app is up and GET returns 200. If desired, change Render Health Check Path to `/` or `/health`.

### E) Quick Self-Validation Checklist (Post-Deploy)
1) Logs show: `Google Sheets connected` and no 415/405 errors for Systeme.io.
2) `/add_student` in verification group → row appears in `Verifications` as `Pending`.
3) Student `/start` → verify → row updates to `Verified` with `telegram_id`.
4) Submit assignment → row in `Submissions`; grade → row updates to `Graded` with score/comment.
5) Share win → row appended to `Wins`.
6) Voice (with quota) → transcription reply + “VoiceTranscriptions” sheet row.

---

## Latest Production Findings (2025-09-23)

Symptoms observed in logs and tests:
- Startup logged: "Google Sheets not configured or gspread not installed; skipping." and later "Google Sheets not configured - skipping sync" during verification/submission flows.
- Systeme.io tagging failed with 405 Method Not Allowed at `/contacts/{id}/tags`.
- Daily tips at 08:00 Africa/Lagos did not post.
- Verified users appeared to lose status after hours (re-asked to verify).

Root causes identified:
- Sheets: `init_gsheets()` required envs but there was no bootstrap to create worksheets/headers. Any feature trying to append/update before a worksheet exists would no-op. Also missing/invalid `GOOGLE_CREDENTIALS_JSON` or `GOOGLE_SHEET_ID` in environment causes the initial "not configured" message.
- Systeme.io: Tagging used PUT in `systeme_add_and_verify_tag` which triggers 405 for the tags endpoint on some plans; needs POST.
- Daily tips: Feature was scheduled, but ensure scheduling is invoked on startup and TIMEZONE/DAILY_TIP_HOUR envs are set.
- Verified persistence: DB path must be on persistent disk; default `/data/bot.db` is set and directory ensured.

Code edits applied (this commit):
- Sheets bootstrap: Added `ensure_default_worksheets()` and invoked it after `init_gsheets()` during startup to create `Verifications`, `Submissions`, `Wins`, `FAQ`, `VoiceTranscriptions` with headers.
- Systeme.io tag method: Switched tag add from PUT to POST in `systeme_add_and_verify_tag` to avoid 405.
- Daily tips: left logic intact; confirmed scheduling call path at startup; documented `TIMEZONE` and `DAILY_TIP_HOUR` envs.

Operational requirements (env):
- `GOOGLE_CREDENTIALS_JSON`: base64 or raw JSON of service account; share Sheet to service account email.
- `GOOGLE_SHEET_ID`: spreadsheet ID.
- `TIMEZONE`=`Africa/Lagos`, `DAILY_TIP_HOUR`=`8`.
- `DB_PATH`=`/data/bot.db` and persistent disk attached on Render.

Testing steps:
- Verify startup shows "Google Sheets connected" and no warnings; confirm worksheets auto-created.
- Run verification and submission flows; confirm new rows in respective worksheets.
- Tag add flow returns no 405 in logs; tag present in Systeme.io contact.
- At 08:00 WAT, confirm daily tip in support group; validate envs if absent.
