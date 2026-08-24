#!/usr/bin/env python3
"""Start the Xunying MCP server from any external Codex working directory."""
from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from backend.app.codex_mcp_server import mcp  # noqa: E402


if __name__ == "__main__":
    mcp.run(transport="stdio")
