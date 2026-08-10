from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = ROOT / ".venv" / "bin"
PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
)


def command_exists(path: Path) -> None:
    if not path.exists():
        raise SystemExit("本机 Python 环境尚未安装，请先创建 .venv 并安装项目依赖。")


def _proxy_is_reachable(value: str, *, timeout: float = 0.4) -> bool:
    parsed = urlparse(value if "://" in value else f"http://{value}")
    if not parsed.hostname or not parsed.port:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def _system_https_proxy() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    values = dict(
        re.findall(
            r"^\s*(HTTPSEnable|HTTPSProxy|HTTPSPort)\s*:\s*(.*?)\s*$",
            completed.stdout,
            flags=re.MULTILINE,
        )
    )
    if values.get("HTTPSEnable") != "1":
        return None
    host = values.get("HTTPSProxy", "").strip()
    port = values.get("HTTPSPort", "").strip()
    if not host or not port.isdigit():
        return None
    return f"http://{host}:{port}"


def configure_runtime_proxy() -> str | None:
    inherited = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if inherited and _proxy_is_reachable(inherited):
        return inherited

    system_proxy = _system_https_proxy()
    if system_proxy and _proxy_is_reachable(system_proxy):
        for key in PROXY_ENV_KEYS:
            os.environ[key] = system_proxy
        bypass = [
            item.strip()
            for item in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(",")
            if item.strip()
        ]
        for host in ("127.0.0.1", "localhost"):
            if host not in bypass:
                bypass.append(host)
        os.environ["NO_PROXY"] = ",".join(bypass)
        os.environ["no_proxy"] = os.environ["NO_PROXY"]
        return system_proxy

    if inherited:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    configure_runtime_proxy()
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
