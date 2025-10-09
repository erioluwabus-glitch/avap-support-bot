"""
Admin handlers for student verification and management
"""
import os
import re
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode, ChatType

from avap_bot.services.supabase_service import (
    add_pending_verification, find_pending_by_email_or_phone,
    promote_pending_to_verified, remove_verified_by_identifier,
    find_verified_by_email_or_phone, find_verified_by_name
)
from avap_bot.services.sheets_service import append_pending_verification, update_verification_status, test_sheets_connection
from avap_bot.services.systeme_service import create_contact_and_tag, untag_or_remove_contact
from avap_bot.utils.validators import validate_email, validate_phone
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.chat_utils import should_disable_inline_keyboards
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

# Get cancel fallback handler, but handle case where it might be None
_cancel_fallback_handler = get_cancel_fallback_handler()

logger = logging.getLogger(__name__)

# Conversation states
ADD_NAME, ADD_PHONE, ADD_EMAIL = range(3)
REMOVE_IDENTIFIER, REMOVE_CONFIRM = range(2)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
VERIFICATION_GROUP_ID = int(os.getenv("VERIFICATION_GROUP_ID", "0"))


async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the add student conversation"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "👤 **Add New Student**\n\n"
        "Please provide the student's full name:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_NAME


async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle student name input"""
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Please provide a valid name (at least 2 characters).")
        return ADD_NAME
    
    context.user_data['student_name'] = name
    await update.message.reply_text(
        f"📱 **Phone Number**\n\n"
        f"Name: {name}\n"
        "Please provide the student's phone number:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_PHONE


async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle student phone input"""
    phone = update.message.text.strip()
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ Invalid phone number format. Please provide a valid phone number:"
        )
        return ADD_PHONE
    
    context.user_data['student_phone'] = phone
    await update.message.reply_text(
        f"📧 **Email Address**\n\n"
        f"Name: {context.user_data['student_name']}\n"
        f"Phone: {phone}\n"
        "Please provide the student's email address:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_EMAIL


async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle student email input and complete registration"""
    email = update.message.text.strip().lower()
    
    if not validate_email(email):
        await update.message.reply_text(
            "❌ Invalid email format. Please provide a valid email address:"
        )
        return ADD_EMAIL
    
    name = context.user_data['student_name']
    phone = context.user_data['student_phone']
    
    try:
        # IMPORTANT: Check for duplicates in both pending and verified tables
        # This prevents multiple students from using the same email or phone
        pending_by_email = find_pending_by_email_or_phone(email=email, phone=None)
        pending_by_phone = find_pending_by_email_or_phone(email=None, phone=phone)
        verified_by_email = find_verified_by_email_or_phone(email=email, phone=None)
        verified_by_phone = find_verified_by_email_or_phone(email=None, phone=phone)
        
        # Combine all potential duplicates
        all_existing = []
        if pending_by_email:
            all_existing.extend(pending_by_email)
        if pending_by_phone:
            all_existing.extend(pending_by_phone)
        if verified_by_email:
            all_existing.extend(verified_by_email)
        if verified_by_phone:
            all_existing.extend(verified_by_phone)
        
        if all_existing:
            # Get the first existing record for the error message
            existing_record = all_existing[0]
            duplicate_type = "email" if existing_record.get('email') == email else "phone number"
            
            await update.message.reply_text(
                f"❌ **Duplicate Detected!**\n\n"
                f"A student with this {duplicate_type} already exists:\n\n"
                f"📧 Email: {existing_record.get('email', 'N/A')}\n"
                f"📱 Phone: {existing_record.get('phone', 'N/A')}\n"
                f"👤 Name: {existing_record.get('name', 'N/A')}\n"
                f"📊 Status: {existing_record.get('status', 'N/A')}\n\n"
                f"⚠️ Each email and phone can only be used once to ensure unique student access.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Notify admin about duplicate attempt
            await notify_admin_telegram(
                context.bot,
                f"🚨 Duplicate student attempt blocked!\n"
                f"Attempted to add: {name} ({email}, {phone})\n"
                f"Conflicts with existing: {existing_record.get('name')} ({existing_record.get('email')})"
            )
            
            return ConversationHandler.END
        
        # Add to Supabase
        pending_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'status': 'verified'  # Create with verified status immediately
        }
        
        result = add_pending_verification(pending_data)
        if not result:
            raise Exception("Failed to add pending verification to Supabase")
        
        # Background tasks
        asyncio.create_task(_background_add_student_tasks(pending_data))
        
        # Send confirmation with verify button (check if inline keyboards should be disabled)
        if should_disable_inline_keyboards(update, allow_admin_operations=True):
            logger.info("Disabling inline keyboard for group chat")
            keyboard = None
        else:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Verify Now", callback_data=f"verify_{result['id']}")
            ]])

        await update.message.reply_text(
            f"✅ **Student Added Successfully!**\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Phone: {phone}\n"
            f"Status: Pending Verification\n\n"
            f"Click the button below to verify immediately:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard if keyboard else None
        )
        
        # Notify verification group
        if VERIFICATION_GROUP_ID and update.message.chat.id != VERIFICATION_GROUP_ID:
            await context.bot.send_message(
                VERIFICATION_GROUP_ID,
                f"🆕 **New Student Added**\n\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Phone: {phone}\n"
                f"Added by: {update.effective_user.first_name}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to add student: %s", e)
        error_message = f"❌ Failed to add student {name}.\nReason: {str(e)}"
        await notify_admin_telegram(context.bot, error_message)
        await update.message.reply_text(
            f"❌ Failed to add student. An error occurred and the admin has been notified."
        )
        return ConversationHandler.END


async def _background_add_student_tasks(pending_data: Dict[str, Any]):
    """Background tasks for adding student"""
    try:
        # Add to Google Sheets
        await run_blocking(append_pending_verification, pending_data)
        
        # Add to Systeme.io
        await run_blocking(create_contact_and_tag, pending_data)
        
    except Exception as e:
        logger.exception("Background add student tasks failed: %s", e)


async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verify now button click"""
    query = update.callback_query
    await query.answer()
    
    if not _is_admin(update):
        await query.edit_message_text("❌ Only admins can verify students.")
        return
    
    try:
        pending_id = query.data.split("_")[1]
        
        # Promote to verified (telegram_id will be None for admin verification until student does /start)
        verified_data = await promote_pending_to_verified(pending_id=pending_id, telegram_id=None)
        if not verified_data:
            await query.edit_message_text("❌ Failed to verify student.")
            return
        
        # Update Google Sheets
        await run_blocking(update_verification_status, verified_data['email'], 'Verified')

        # Note: Systeme.io contact already created with verified status when student was added
        
        # Send confirmation
        await query.edit_message_text(
            f"✅ **Student Verified!**\n\n"
            f"Name: {verified_data['name']}\n"
            f"Email: {verified_data['email']}\n"
            f"Telegram ID: {verified_data.get('telegram_id', 'Not set')}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify student if they have telegram_id
        if verified_data.get('telegram_id'):
            try:
                await context.bot.send_message(
                    verified_data['telegram_id'],
                    f"🎉 **Welcome to AVAP!**\n\n"
                    f"Your account has been verified. You can now use all bot features!\n"
                    f"Send /start to begin.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning("Could not notify student: %s", e)
        
    except Exception as e:
        logger.exception("Admin verify callback failed: %s", e)
        await query.edit_message_text("❌ Verification failed. Please try again.")


async def remove_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start remove student conversation"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🗑️ **Remove Student**\n\n"
        "Please provide student identifier (email, phone, or name):",
        parse_mode=ParseMode.MARKDOWN
    )
    return REMOVE_IDENTIFIER


async def remove_student_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle student identifier input"""
    identifier = update.message.text.strip()
    context.user_data['remove_identifier'] = identifier
    
    # Find student
    try:
        student = _find_student_by_identifier(identifier)
        if not student:
            await update.message.reply_text(
                f"❌ No student found with identifier: {identifier}"
            )
            return ConversationHandler.END
        
        context.user_data['student_to_remove'] = student

        # Check if inline keyboards should be disabled (when message comes from group)
        if should_disable_inline_keyboards(update, allow_admin_operations=True):
            logger.info("Disabling inline keyboard for group chat")
            keyboard = None
        else:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑️ REMOVE", callback_data="remove_confirm"),
                InlineKeyboardButton("❌ CANCEL", callback_data="remove_cancel")
            ]])

        await update.message.reply_text(
            f"⚠️ **Confirm Removal**\n\n"
            f"Student: {student['name']}\n"
            f"Email: {student['email']}\n"
            f"Phone: {student['phone']}\n"
            f"Telegram ID: {student.get('telegram_id', 'Not set')}\n\n"
            f"Are you sure you want to remove this student? This will also ban them from the support group.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard if keyboard else None
        )
        return REMOVE_CONFIRM
        
    except Exception as e:
        logger.exception("Failed to find student: %s", e)
        await update.message.reply_text("❌ Error finding student. Please try again.")
        return ConversationHandler.END


async def remove_student_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle remove confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "remove_cancel":
        await query.edit_message_text("❌ Removal cancelled.")
        context.user_data.clear()
        return ConversationHandler.END
    
    if not _is_admin(update):
        await query.edit_message_text("❌ Only admins can remove students.")
        return ConversationHandler.END
    
    try:
        identifier = context.user_data['remove_identifier']
        student = context.user_data['student_to_remove']
        
        if not student:
            await query.edit_message_text("❌ Student not found.")
            return ConversationHandler.END
        
        # Remove from all systems
        logger.info(f"Attempting to remove student with identifier: {identifier}")
        try:
            success = remove_verified_by_identifier(identifier)
            if not success:
                logger.error(f"Failed to remove student from Supabase: {identifier}")
                await query.edit_message_text(
                    f"❌ **Failed to remove student from database.**\n\n"
                    f"**Student:** {student.get('name', 'Unknown')}\n"
                    f"**Identifier:** {identifier}\n\n"
                    f"**Possible causes:**\n"
                    f"• Student not found in database\n"
                    f"• Database connection issue\n"
                    f"• Student already removed\n\n"
                    f"Please check the logs for more details or try again.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
        except Exception as e:
            logger.exception(f"Exception during student removal: {e}")
            await query.edit_message_text(
                f"❌ **Error removing student from database.**\n\n"
                f"**Student:** {student.get('name', 'Unknown')}\n"
                f"**Identifier:** {identifier}\n"
                f"**Error:** {str(e)}\n\n"
                f"Please try again or contact support.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        # Remove from Systeme.io and update Google Sheets
        if student and student.get('email'):
            await run_blocking(untag_or_remove_contact, student['email'], action="remove")
            await run_blocking(update_verification_status, student['email'], 'Removed')
        else:
            logger.warning(f"Could not update Systeme.io or Google Sheets for student because email is missing. Student data: {student}")
            await notify_admin_telegram(context.bot, f"Failed to update Systeme.io/Sheets for student {student.get('name')} (email missing).")

        # Ban from support group if ID is available
        if SUPPORT_GROUP_ID and student.get('telegram_id'):
            try:
                await context.bot.ban_chat_member(
                    chat_id=SUPPORT_GROUP_ID,
                    user_id=student['telegram_id']
                )
                logger.info(f"Banned user {student['telegram_id']} from support group {SUPPORT_GROUP_ID}.")
            except Exception as e:
                logger.error(f"Could not ban user {student['telegram_id']} from support group: {e}")
                # Non-fatal, so we just log it and continue
                await notify_admin_telegram(context.bot, f"Failed to ban {student.get('name')} from support group.")
        
        await query.edit_message_text(
            f"✅ **Student Removed Successfully**\n\n"
            f"Name: {student['name']}\n"
            f"Email: {student['email']}\n\n"
            f"They have been removed from all systems and banned from the support group.\n"
            f"Please revoke their course access manually.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify verification group
        if VERIFICATION_GROUP_ID:
            await context.bot.send_message(
                VERIFICATION_GROUP_ID,
                f"🗑️ **Student Removed**\n\n"
                f"Name: {student['name']}\n"
                f"Email: {student['email']}\n"
                f"Removed by: {update.effective_user.first_name}",
                parse_mode=ParseMode.MARKDOWN
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to remove student: %s", e)
        await query.edit_message_text("❌ Failed to remove student. Please try again.")
        return ConversationHandler.END


def _find_student_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """Find student by email, phone, or name in verified_users and pending_verifications tables."""
    # Try as email first
    if validate_email(identifier):
        results = find_verified_by_email_or_phone(email=identifier)
        if results:
            return results[0]

    # Try as phone
    if validate_phone(identifier):
        results = find_verified_by_email_or_phone(phone=identifier)
        if results:
            return results[0]

    # Try as name in verified users
    results = find_verified_by_name(identifier)
    if results:
        return results[0]

    # If not found in verified_users, try pending_verifications
    from avap_bot.services.supabase_service import find_pending_by_email_or_phone

    if validate_email(identifier):
        pending_results = find_pending_by_email_or_phone(email=identifier)
        if pending_results:
            return pending_results[0]

    if validate_phone(identifier):
        pending_results = find_pending_by_email_or_phone(phone=identifier)
        if pending_results:
            return pending_results[0]

    return None


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


async def test_sheets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Test Google Sheets connection (admin only)"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END

    try:
        success = await run_blocking(test_sheets_connection)
        if success:
            await update.message.reply_text("✅ Google Sheets connection test successful!")
        else:
            await update.message.reply_text("❌ Google Sheets connection test failed. Check logs for details.")
    except Exception as e:
        logger.exception("Sheets test command failed: %s", e)
        await update.message.reply_text(f"❌ Sheets test failed: {str(e)}")

    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handlers
fallbacks = [get_cancel_fallback_handler()] if get_cancel_fallback_handler() else []
add_student_conv = ConversationHandler(
    entry_points=[CommandHandler("addstudent", add_student_start, filters=filters.Chat(chat_id=VERIFICATION_GROUP_ID))],
    states={
        ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
        ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
        ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
    },
    fallbacks=fallbacks,
    per_message=False  # explicit
)

remove_student_conv = ConversationHandler(
    entry_points=[CommandHandler("remove_student", remove_student_start, filters=filters.Chat(chat_id=VERIFICATION_GROUP_ID))],
    states={
        REMOVE_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_student_identifier)],
        REMOVE_CONFIRM: [CallbackQueryHandler(remove_student_confirm, pattern="^remove_")],
    },
    fallbacks=fallbacks,
    per_message=False,  # explicit
    conversation_timeout=600
)


def register_handlers(application):
    """Register all admin handlers with the application"""
    # Add conversation handlers
    application.add_handler(add_student_conv)
    application.add_handler(remove_student_conv)

    # Add test command for Google Sheets
    application.add_handler(CommandHandler("test_sheets", test_sheets_handler))

    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(admin_verify_callback, pattern="^verify_"))
    application.add_handler(CallbackQueryHandler(remove_student_confirm, pattern="^remove_"))