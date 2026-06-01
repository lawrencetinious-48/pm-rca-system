from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Return UTC now as a naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
