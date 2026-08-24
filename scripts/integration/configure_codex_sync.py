#!/usr/bin/env python3
"""Ensure a private local Codex sync secret without printing its value."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = PROJECT_ROOT / ".env"
KEY = "XUNYING_CODEX_EVENT_SECRET"


def configure(env_path: Path, *, rotate: bool = False) -> dict[str, object]:
    if env_path.is_symlink():
        raise RuntimeError("refusing to update a symlinked .env")
    env_path = env_path.resolve(strict=False)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines()
    current = ""
    found = False
    for line in lines:
        if line.startswith(f"{KEY}="):
            found = True
            current = line.split("=", 1)[1].strip()
            break
    generated = rotate or len(current) < 32
    value = secrets.token_urlsafe(48) if generated else current
    next_lines: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{KEY}="):
            if not replaced:
                next_lines.append(f"{KEY}={value}")
                replaced = True
            continue
        next_lines.append(line)
    if not replaced:
        if next_lines and next_lines[-1] != "":
            next_lines.append("")
        next_lines.append(f"{KEY}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{env_path.name}.", dir=env_path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(next_lines).rstrip("\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, env_path)
        env_path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "configured": True,
        "generated": generated,
        "rotated": rotate,
        "path": str(env_path),
        "mode": "0600",
        "secret_printed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure local Xunying Codex event HMAC")
    parser.add_argument("--rotate", action="store_true", help="Replace an existing secret")
    args = parser.parse_args()
    print(json.dumps(configure(DEFAULT_ENV, rotate=args.rotate), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
