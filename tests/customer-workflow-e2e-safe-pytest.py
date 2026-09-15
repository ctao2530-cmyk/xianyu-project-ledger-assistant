"""Run synthetic workflow tests without dotenv, business data, or network access.

Usage: .venv/bin/python tests/customer-workflow-e2e-safe-pytest.py <pytest args>
This process-only guard does not change application configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
guard_directory = str(ROOT / "tests" / "customer-workflow-e2e-guard")
sys.path.insert(0, guard_directory)
os.environ["PYTHONPATH"] = guard_directory + os.pathsep + os.environ.get("PYTHONPATH", "")
import sitecustomize  # installs guards here and via PYTHONPATH in Python children

import pytest

arguments = sys.argv[1:]
if not any(argument.startswith("--basetemp") for argument in arguments):
    arguments = ["--basetemp", tempfile.mkdtemp(prefix="customer-workflow-qa-")] + arguments
raise SystemExit(pytest.main(arguments))
