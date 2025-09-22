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
