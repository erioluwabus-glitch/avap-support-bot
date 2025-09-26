# avap_bot/services/__init__.py
"""Services package exports."""

# Import the common service accessors here so other modules can do:
# from avap_bot.services import get_supabase, init_supabase
try:
    from .supabase_service import init_supabase, get_supabase  # type: ignore
except Exception:
    # If the service file is missing or has import errors, keep module importable.
    init_supabase = None
    get_supabase = None