# avap_bot/handlers/__init__.py
"""Handler registry for avap_bot.

This module dynamically imports handler modules and calls their
`register_handlers(application)` function to attach handlers to the
python-telegram-bot Application object.
"""

import logging
from telegram.ext import Application
from . import admin, student, grading, tips, matching, admin_tools, questions

logger = logging.getLogger(__name__)

def register_all(application: Application):
    """
    Import each handler module and call its register_handlers(application)
    if that function exists. Modules that are missing or don't expose the
    function are skipped with a log message.
    """
    modules = [admin, student, questions, grading, tips, matching, admin_tools]
    
    for module in modules:
        try:
            if hasattr(module, 'register_handlers'):
                module.register_handlers(application)
                logger.debug(f"✅ Registered handlers from {module.__name__}")
        except Exception as e:
            logger.error(f"❌ Failed to register handlers from {module.__name__}: {str(e)}")
            raise