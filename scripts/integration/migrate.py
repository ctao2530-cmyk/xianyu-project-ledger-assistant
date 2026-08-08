from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings
from backend.app.database import Database


def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    database.create_all()
    print("Unified SQLite schema is current.")


if __name__ == "__main__":
    main()
