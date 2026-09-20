"""Launch the existing local service directly from its Python environment.

Keep the transport secret in Keychain and the child environment only. This
entrypoint replaces the LaunchAgent's shell substitution without changing
the service, database, port or startup migrations.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        result = subprocess.run(
            [
                "/usr/bin/security", "find-generic-password",
                "-a", getpass.getuser(),
                "-s", "xunying-customer-context-transport", "-w",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Local service transport credential could not be read from Keychain.", file=sys.stderr)
        return 1
    secret = result.stdout.strip()
    if result.returncode != 0 or not secret:
        print("Local service transport credential is unavailable in Keychain.", file=sys.stderr)
        return 1
    os.environ["CUSTOMER_CONTEXT_TUNNEL_SECRET"] = secret
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(ROOT / "scripts/integration/start_local.py")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
