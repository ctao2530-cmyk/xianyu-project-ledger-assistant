from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_mcp_exposes_only_the_approved_xunying_surface() -> None:
    source = (ROOT / "backend" / "app" / "codex_mcp_server.py").read_text()
    tree = ast.parse(source)
    tools = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        )
    }
    assert tools == {
        "xunying_get_project_context",
        "xunying_get_task_list",
        "xunying_get_task",
        "xunying_task_start",
        "xunying_task_checkpoint",
        "xunying_task_blocked",
        "xunying_report_test_result",
        "xunying_task_complete",
    }
    assert not any(
        fragment in " ".join(tools)
        for fragment in ("customer", "quote", "finance", "message", "listing", "promotion", "deploy")
    )
    assert "Database(" not in source
    assert "create_subprocess" not in source and "subprocess" not in source
    runner = (ROOT / "scripts" / "integration" / "run_codex_mcp.py").read_text()
    assert "PROJECT_ROOT" in runner
    assert "mcp.run(transport=\"stdio\")" in runner


def test_hook_generator_uses_official_schema_and_performs_no_write() -> None:
    path = ROOT / "scripts" / "integration" / "generate_codex_sync_config.py"
    spec = importlib.util.spec_from_file_location("codex_sync_config", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.hooks_config("project-one", None)

    assert set(config["hooks"]) == {
        "SessionStart",
        "SessionEnd",
        "PostToolUse",
        "PermissionRequest",
        "Stop",
    }
    for groups in config["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                assert handler["type"] == "command"
                assert "XUNYING_CODEX_EVENT_SECRET" not in handler["command"]
    source = path.read_text()
    assert "write_text(" not in source and "open(" not in source


def test_hook_reporter_selects_only_supported_fields() -> None:
    path = ROOT / "scripts" / "integration" / "codex_hook_reporter.py"
    spec = importlib.util.spec_from_file_location("codex_hook_reporter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    event_type = module._event_type(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
        }
    )
    assert event_type == "test_result"
    payload = module._payload(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q", "environment": {"TOKEN": "no"}},
            "tool_response": {"exit_code": 0, "summary": "passed"},
            "transcript_path": "/private/transcript",
        },
        event_type,
    )
    assert payload == {
        "summary": "passed",
        "hook_event": "PostToolUse",
        "tool_name": "Bash",
        "command": "pytest -q",
        "exit_code": 0,
    }
    assert "environment" not in json.dumps(payload)
    assert "transcript" not in json.dumps(payload)
