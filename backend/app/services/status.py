from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RuntimeStatus:
    listener: str = "starting"
    listener_detail: str | None = None
    realtime_delivery: str = "unknown"
    realtime_detail: str | None = None
    reconcile_recovered_total: int = 0
    last_reconcile_at: datetime | None = None
    last_event_at: datetime | None = None
