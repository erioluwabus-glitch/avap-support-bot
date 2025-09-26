# avap_bot/web/__init__.py
"""Web endpoints package exports."""

try:
    from .admin_endpoints import router as admin_router  # type: ignore
except Exception:
    # If web files are missing, keep module importable
    admin_router = None