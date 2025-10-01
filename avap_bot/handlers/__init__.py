# avap_bot/handlers/__init__.py
"""Handler registry for avap_bot.

This module dynamically imports handler modules and calls their
`register_handlers(application)` function to attach handlers to the
python-telegram-bot Application object.
"""

from importlib import import_module
import logging

logger = logging.getLogger(__name__)

# Add or remove module names here to match your repository files.
HANDLER_MODULES = [
    "admin",
    "student",
    "grading",
    "tips",
    "webhook",
    "matching",
    "admin_tools",
    "answer",
]

def register_all(application):
    """
    Import each handler module and call its register_handlers(application)
    if that function exists. Modules that are missing or don't expose the
    function are skipped with a log message.
    """
    for name in HANDLER_MODULES:
        fqname = f"avap_bot.handlers.{name}"
        try:
            mod = import_module(fqname)
        except ModuleNotFoundError:
            logger.warning("Handler module not found: %s (skipping)", fqname)
            continue
        except Exception:
            logger.exception("Failed to import handler module %s", fqname)
            continue

        if hasattr(mod, "register_handlers"):
            try:
                mod.register_handlers(application)
                logger.info("Registered handlers from %s", fqname)
            except Exception:
                logger.exception("Error registering handlers from %s", fqname)
        else:
            logger.warning("Module %s does not expose register_handlers(), skipping", fqname)