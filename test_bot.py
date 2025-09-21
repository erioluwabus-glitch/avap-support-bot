#!/usr/bin/env python3
"""
Minimal test bot to debug the comment issue
"""
import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
GRADING_COMMENT = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Test Comment", callback_data="comment_type_text_123")]
    ])
    await update.message.reply_text("Click the button to test comment feature:", reply_markup=keyboard)

async def comment_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle comment type selection"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    data = query.data
    logger.info(f"Received callback data: {data}")
    
    if data.startswith("comment_type_"):
        parts = data.split("_")
        if len(parts) >= 4:
            comment_type = parts[2]
            sub_id = parts[3]
            logger.info(f"Comment type: {comment_type}, Sub ID: {sub_id}")
            
            context.user_data['grading_sub_id'] = sub_id
            context.user_data['grading_expected'] = 'comment'
            context.user_data['comment_type'] = comment_type
            
            await query.message.reply_text("Send your comment now:")
            return GRADING_COMMENT
        else:
            await query.answer("Invalid callback data")
            return ConversationHandler.END
    else:
        await query.answer("Unknown callback")
        return ConversationHandler.END

async def grading_comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle comment input"""
    logger.info(f"Received message: {update.message.text}")
    logger.info(f"User data: {context.user_data}")
    
    if context.user_data.get('grading_expected') != 'comment':
        logger.warning("Not expecting a comment")
        return
    
    comment_text = update.message.text
    sub_id = context.user_data.get('grading_sub_id')
    
    await update.message.reply_text(f"Comment received: {comment_text} for submission {sub_id}")
    
    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END

def main():
    """Main function"""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("BOT_TOKEN not set")
        return
    
    # Create application
    app = Application.builder().token(bot_token).build()
    
    # Create conversation handler
    grading_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(comment_type_callback, pattern="^comment_type_(text|audio|video)_")],
        states={
            GRADING_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, grading_comment_receive)]
        },
        fallbacks=[],
        per_message=False,
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(grading_conv)
    
    # Start bot
    print("Starting test bot...")
    app.run_polling()

if __name__ == "__main__":
    main()

