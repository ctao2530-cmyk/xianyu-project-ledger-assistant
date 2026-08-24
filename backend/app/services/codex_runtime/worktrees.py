from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManagedWorktree:
    repository_root: Path
    worktree_path: Path
    base_commit_sha: str
    branch: str
    repository_dirty: bool


def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return (normalized or fallback)[:64]


class WorktreeManager:
    def __init__(self, managed_root: Path) -> None:
        self.managed_root = managed_root.expanduser().resolve(strict=False)

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=True, timeout=30
        )
        if result.returncode:
            raise WorktreeError((result.stderr or result.stdout or "Git 操作失败").strip())
        return result.stdout.strip()

    def inspect_repository(self, repository_path: str) -> tuple[Path, str, bool]:
        candidate = Path(repository_path).expanduser().resolve(strict=True)
        root = Path(self._git(candidate, "rev-parse", "--show-toplevel")).resolve(strict=True)
        if candidate != root and root not in candidate.parents:
            raise WorktreeError("仓库路径解析结果无效")
        head = self._git(root, "rev-parse", "HEAD")
        dirty = bool(self._git(root, "status", "--porcelain=v1", "--untracked-files=normal"))
        return root, head, dirty

    def create(
        self,
        *,
        repository_path: str,
        project_id: str,
        task_key: str,
        run_id: str,
        expected_head_sha: str,
        acknowledge_dirty: bool,
    ) -> ManagedWorktree:
        root, head, dirty = self.inspect_repository(repository_path)
        if (
            self.managed_root == root
            or root in self.managed_root.parents
            or self.managed_root in root.parents
        ):
            raise WorktreeError("受管 Worktree 根目录不得与绑定仓库重叠")
        if expected_head_sha and head != expected_head_sha:
            raise WorktreeError("仓库 HEAD 已变化，请重新确认绑定后再启动")
        if dirty and not acknowledge_dirty:
            raise WorktreeError("主工作区存在未提交内容；独立 Worktree 不会包含这些内容，请先明确确认")
        safe_project = _safe_component(project_id, "project")
        safe_task = _safe_component(task_key, "task")
        safe_run = _safe_component(run_id, "run")
        target = (self.managed_root / safe_project / safe_run).resolve(strict=False)
        if target == self.managed_root or self.managed_root not in target.parents:
            raise WorktreeError("Worktree 路径不在受管目录内")
        if target.exists():
            raise WorktreeError("目标 Worktree 已存在，循营不会自动覆盖或清理")
        target.parent.mkdir(parents=True, exist_ok=True)
        branch = f"codex/{safe_project}/{safe_task}-{safe_run[-8:]}"
        self._git(root, "worktree", "add", "-b", branch, str(target), head)
        resolved = target.resolve(strict=True)
        if self.managed_root not in resolved.parents:
            raise WorktreeError("创建后的 Worktree 逃逸受管目录")
        return ManagedWorktree(root, resolved, head, branch, dirty)

    def diff(self, worktree_path: str, *, max_chars: int = 80_000) -> str:
        path = Path(worktree_path).resolve(strict=True)
        if self.managed_root not in path.parents:
            raise WorktreeError("不能读取受管目录以外的 Diff")
        return self._git(path, "diff", "--no-ext-diff", "--")[:max_chars]

    def open_in_finder(self, worktree_path: str) -> None:
        path = Path(worktree_path).resolve(strict=True)
        if self.managed_root not in path.parents:
            raise WorktreeError("不能打开受管目录以外的路径")
        subprocess.run(["open", str(path)], check=True, timeout=10)
