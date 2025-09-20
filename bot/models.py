"""
Data models for the bot, including conversation states and keyboards.
"""

from telegram import ReplyKeyboardMarkup, KeyboardButton

# Conversation states
(
    ADD_STUDENT_NAME,
    ADD_STUDENT_PHONE,
    ADD_STUDENT_EMAIL,
    VERIFY_NAME,
    VERIFY_PHONE,
    VERIFY_EMAIL,
    SUBMIT_MODULE,
    SUBMIT_MEDIA_TYPE,
    SUBMIT_MEDIA_UPLOAD,
    GRADE_SCORE,
    GRADE_COMMENT_TYPE,
    GRADE_COMMENT_UPLOAD,
    WIN_TYPE,
    ASK_QUESTION,
    ANSWER_QUESTION,
    GRADE_USERNAME,
    GRADE_MODULE,
) = range(100, 117)


# Reply keyboards (DM-only)
MAIN_MENU_KEYBOARD = [
    [KeyboardButton("📤 Submit Assignment"), KeyboardButton("🎉 Share Small Win")],
    [KeyboardButton("📊 Check Status"), KeyboardButton("❓ Ask a Question")],
]

MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True, one_time_keyboard=False)
