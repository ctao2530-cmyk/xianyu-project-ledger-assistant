from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = ROOT / ".venv" / "bin"


def command_exists(path: Path) -> None:
    if not path.exists():
        raise SystemExit("本机 Python 环境尚未安装，请先创建 .venv 并安装项目依赖。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    python = VENV_BIN / "python"
    command_exists(python)
    subprocess.run([str(python), "scripts/integration/migrate.py"], cwd=ROOT, check=True)
    backend = [
        str(python),
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        os.environ.get("APP_PORT", "8877"),
    ]
    if args.dev:
        backend.append("--reload")
        processes = [
            subprocess.Popen(backend, cwd=ROOT),
            subprocess.Popen(["pnpm", "run", "dev"], cwd=ROOT),
        ]

        def stop(_signum=None, _frame=None):
            for process in processes:
                if process.poll() is None:
                    process.terminate()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        try:
            return next(process.wait() for process in processes)
        finally:
            stop()
    os.chdir(ROOT)
    os.execv(str(python), backend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
