#!/usr/bin/env python3
"""Print reviewable project Hook and MCP setup without writing configuration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTER = PROJECT_ROOT / "scripts" / "integration" / "codex_hook_reporter.py"
MCP_RUNNER = PROJECT_ROOT / "scripts" / "integration" / "run_codex_mcp.py"
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def capability() -> dict[str, object]:
    command = "/Applications/ChatGPT.app/Contents/Resources/codex"
    try:
        version = subprocess.run(
            [command, "--version"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
        features = subprocess.run(
            [command, "features", "list"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        hooks = any(line.split()[:1] == ["hooks"] and "stable" in line for line in features.splitlines())
    except (OSError, subprocess.SubprocessError):
        version, hooks = "unavailable", False
    return {"codex_version": version, "official_hooks_available": hooks}


def hooks_config(project_id: str, task_key: str | None) -> dict[str, object]:
    env_prefix = f"XUNYING_PROJECT_ID={json.dumps(project_id)}"
    if task_key:
        env_prefix += f" XUNYING_TASK_KEY={json.dumps(task_key)}"
    command = f"{env_prefix} {json.dumps(str(PYTHON))} {json.dumps(str(REPORTER))}"
    handler = {"type": "command", "command": command, "async": True, "timeout": 10}
    end_handler = {"type": "command", "command": command, "timeout": 3}
    return {
        "description": "Optional Xunying external Codex activity sync. Review with /hooks before trust.",
        "hooks": {
            "SessionStart": [{"hooks": [handler]}],
            "PostToolUse": [{"hooks": [handler]}],
            "PermissionRequest": [{"hooks": [handler]}],
            "Stop": [{"hooks": [handler]}],
            "SessionEnd": [{"hooks": [end_handler]}],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate review-only Xunying Codex MCP/Hook configuration"
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--task-key")
    args = parser.parse_args()
    result = {
        "capability": capability(),
        "writes_performed": False,
        "mcp_add_command": [
            "/Applications/ChatGPT.app/Contents/Resources/codex",
            "mcp",
            "add",
            "xunying",
            "--",
            str(PYTHON),
            str(MCP_RUNNER),
        ],
        "project_hooks_path": ".codex/hooks.json",
        "project_hooks": hooks_config(args.project_id, args.task_key),
        "manual_steps": [
            "Review the generated project_hooks object before writing .codex/hooks.json.",
            "After writing it manually, use /hooks in Codex to review and trust the exact definition.",
            "Hooks without XUNYING_TASK_KEY persist general activity only and cannot update a task.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
