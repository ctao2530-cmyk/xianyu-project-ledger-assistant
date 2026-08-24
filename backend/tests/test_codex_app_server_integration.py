from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.app.services.codex_runtime import AppServerDevelopmentRuntime


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_CODEX_INTEGRATION") != "1",
    reason="set RUN_REAL_CODEX_INTEGRATION=1 for the explicit local Codex fixture",
)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.mark.asyncio
async def test_real_app_server_edits_disposable_fixture_without_commit(tmp_path: Path) -> None:
    command = shutil.which("codex")
    assert command, "Codex CLI is required"
    repo = tmp_path / "fixture"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.com")
    git(repo, "config", "user.name", "Fixture")
    (repo / "fixture.txt").write_text("before\n", encoding="utf-8")
    git(repo, "add", "fixture.txt")
    git(repo, "commit", "-m", "fixture")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    runtime = AppServerDevelopmentRuntime(command, request_timeout=60)
    event_types: list[str] = []
    try:
        capabilities = await runtime.capabilities()
        assert capabilities.available and "codex-cli" in capabilities.version
        thread = await runtime.create_run(
            cwd=str(repo),
            model="",
            sandbox_mode="workspace-write",
            # This disposable fixture has an exact pre-authorized edit and is
            # still constrained by workspace-write. Product runs always use
            # ``untrusted`` and persist every approval for a human decision.
            approval_mode="never",
            developer_instructions=(
                "This is a disposable local fixture. Never commit, push, access the network, "
                "read outside the fixture, or call thread/shellCommand."
            ),
        )
        await runtime.start_turn(
            thread_id=thread.thread_id,
            prompt=(
                "Inspect fixture.txt, change its exact contents from 'before' to 'after', "
                "then stop. Do not commit. Do not install anything. Do not access the network."
            ),
            cwd=str(repo),
            model="",
            reasoning_effort="low",
        )
        events = runtime.stream_events().__aiter__()
        for _ in range(200):
            try:
                event = await asyncio.wait_for(events.__anext__(), timeout=90)
            except TimeoutError:
                pytest.fail(f"App Server event timeout: {runtime.diagnostics()}; events={event_types}")
            event_types.append(event.event_type)
            if event.event_type == "approval_requested":
                await runtime.reject_action(
                    server_request_id=event.server_request_id, cancel_turn=True
                )
                pytest.fail("Disposable fixture unexpectedly requested elevated approval")
            if event.event_type in {"run_completed", "run_failed"}:
                assert event.event_type == "run_completed", event.payload
                break
        else:
            pytest.fail("App Server fixture did not complete")
    finally:
        await runtime.close()

    assert (repo / "fixture.txt").read_text(encoding="utf-8") == "after\n"
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip() == base
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip() == "M fixture.txt"
    assert "run_completed" in event_types
    assert {"file_changed", "diff_updated"}.intersection(event_types)
