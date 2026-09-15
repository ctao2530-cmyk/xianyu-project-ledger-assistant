"""Serialization boundary for customer timestamps stored as UTC in SQLite."""
from datetime import datetime, timezone


def utc_from_storage(value: datetime | None) -> datetime | None:
    """Restore SQLite's lost UTC marker; preserve already-aware instants."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
