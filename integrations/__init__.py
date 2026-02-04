# Integrations package
# Import modules explicitly to avoid dependency issues

__all__ = ["GoogleSheetsClient", "CalcomClient"]

def __getattr__(name):
    """Lazy import to avoid loading unnecessary dependencies."""
    if name == "GoogleSheetsClient":
        from .google_sheets import GoogleSheetsClient
        return GoogleSheetsClient
    elif name == "CalcomClient":
        from .calcom import CalcomClient
        return CalcomClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
