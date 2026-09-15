"""Inherited Python-only synthetic QA guard; never imported by application runs."""
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
GUARD = str(Path(__file__).resolve().parent)


def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).absolute()
        if path == ROOT / ".env" or any(path.is_relative_to(ROOT / name) for name in ("data", "logs")):
            raise PermissionError("Synthetic QA denies real data/env/log access")
    if event == "sqlite3.connect" and str(args[0]) != ":memory:":
        if Path(str(args[0])).absolute().is_relative_to(ROOT):
            raise PermissionError("Synthetic QA requires a temporary SQLite database")
    if event == "socket.connect" and isinstance(args[1], tuple):
        raise PermissionError("Synthetic QA denies network connections")
    if event in {"os.system", "os.exec", "os.posix_spawn"}:
        raise PermissionError("Synthetic QA denies unguarded process execution")
    if event == "subprocess.Popen":
        executable, argv, _cwd, environment = args
        name = Path(os.fsdecode(executable)).name
        environment = environment if environment is not None else os.environ
        pythonpath = environment.get("PYTHONPATH", "")
        if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", name) or GUARD not in pythonpath.split(os.pathsep):
            raise PermissionError("Synthetic QA requires inherited Python child guard")
        if isinstance(argv, (str, bytes)) or any(flag in argv for flag in ("-I", "-E", "-S")):
            raise PermissionError("Synthetic QA denies isolated child without guard")


sys.addaudithook(guard)

# Both application Settings and FastMCP Settings use this dotenv source.
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource
DotEnvSettingsSource._read_env_files = lambda self: {}
