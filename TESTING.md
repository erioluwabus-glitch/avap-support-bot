# Telegram Bot Test Plan

This document provides a step-by-step plan for testing all features of the AVAP Support Bot.

**Prerequisites:**
- The bot is running (either locally in polling mode or deployed on Render).
- You have access to the Telegram accounts for an admin and a regular student.
- You have created the required Telegram groups (Support, Assignments, Questions, Verification) and have their IDs.
- The environment variables (`.env` file) are correctly configured with the bot token, admin ID, and group IDs.

---

## 1. Admin Features

### 1.1. Add Student (Admin Pre-Registration)
1.  As the admin, go to the **Verification Group**.
2.  Send the command `/add_student`.
3.  The bot should prompt for the student's full name. Enter a valid name (e.g., "Test Student").
4.  The bot should prompt for the student's phone number. Enter a valid number (e.g., `+1234567890`).
5.  The bot should prompt for the student's email. Enter a valid email (e.g., `test.student@example.com`).
6.  **Expected Result**: The bot should confirm that the student has been added as "pending".

### 1.2. Manual Verification by Admin
1.  As the admin, send the command `/verify_student test.student@example.com` (using the email from the previous test).
2.  **Expected Result**: The bot should confirm that the student has been verified.

### 1.3. Remove Verified Student
1.  As the admin, you need the `telegram_id` of the verified student. For this test, since the student was manually verified and hasn't interacted with the bot, you can manually add their ID to the database or verify a real student account to get their ID. For this test plan, we will assume you have the `telegram_id`.
2.  Send the command `/remove_student <telegram_id>`.
3.  **Expected Result**: The bot should confirm that the student has been removed.

---

## 2. Student Verification Flow

1.  Using a non-admin student account, start a DM with the bot.
2.  Send `/start`. The bot should welcome you and show a "Verify Now" button.
3.  Click "Verify Now" or send `/verify`.
4.  The bot prompts for your full name. Enter the name you were pre-registered with ("Test Student").
5.  The bot prompts for your phone number. Enter the correct number (`+1234567890`).
6.  The bot prompts for your email. Enter the correct email (`test.student@example.com`).
7.  **Expected Result**: The bot should reply with "✅ Verified! Welcome to AVAP!" and show the main menu keyboard.

---

## 3. Student Features (DM-Only)

These tests should be performed from the verified student's account in a DM with the bot.

### 3.1. Submit Assignment
1.  Click the "Submit Assignment" button.
2.  The bot asks for the module number. Enter `1`.
3.  The bot asks for the media type. Click "Image".
4.  The bot asks you to send the image. Send a photo.
5.  **Expected Result**: The bot should reply "Boom! Submission received!". In the **Assignments Group**, a new message should appear with the submission details and a "📝 Grade" button.

### 3.2. Grading (Admin)
1.  As the admin, go to the **Assignments Group**.
2.  Click the "📝 Grade" button on the new submission message.
3.  **Expected Result**: The message should be edited to show a score selector (1-10).
4.  Click on a score (e.g., `8`).
5.  **Expected Result**: The message should be edited to ask if you want to add a comment.
6.  Click "Comment".
7.  **Expected Result**: The message should be edited to ask you to send the comment.
8.  Send a text message as a comment (e.g., "Good work!").
9.  **Expected Result**: The original message should be edited to "✅ Graded with comment.", and your comment message should be deleted.

### 3.3. Share Small Win
1.  From the student account, click the "Share Small Win" button.
2.  The bot asks for the content type. Click "Text".
3.  Send a text message (e.g., "I completed a difficult task!").
4.  **Expected Result**: The bot should reply "Awesome win shared!". In the **Support Group**, a new message should appear with the win details.

### 3.4. Check Status
1.  From the student account, click the "Check Status" button.
2.  **Expected Result**: The bot should show your completed modules (Module 1, score 8), your comments, and your total number of wins (1).

---

## 4. Group Features

### 4.1. Ask a Question (Group)
1.  From the student account, go to the **Support Group**.
2.  Send the command `/ask How do I do X?`.
3.  **Expected Result**: The bot should reply "Question sent! Our support team will get back to you.". In the **Questions Group**, a new message should appear with the question and an "Answer" button.

### 4.2. Answering a Question (Admin)
1.  As the admin, go to the **Questions Group**.
2.  Click the "Answer" button on the new question.
3.  The bot asks you to send the answer. Send a text message (e.g., "You can do X by doing Y.").
4.  **Expected Result**: The bot should reply "Answer sent to student." in the group. The student should receive a DM from the bot with the answer.

### 4.3. Other Commands in Group
1.  From the student account, in the **Support Group**, send `/start` or `/submit`.
2.  **Expected Result**: The bot should not respond to these commands in the group.

---

This concludes the test plan. Successful completion of all these steps indicates that the bot is working as expected.
