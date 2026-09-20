"""Launcher checks with mocked Keychain and process execution only."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.integration import launch_service


class LauncherTests(unittest.TestCase):
    def exercise(self, result=None, error=None):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(launch_service.getpass, "getuser", return_value="local-test-user"), \
             patch.object(launch_service.subprocess, "run", return_value=result, side_effect=error) as read, \
             patch.object(launch_service.os, "chdir") as chdir, \
             patch.object(launch_service.os, "execv") as execute, \
             contextlib.redirect_stderr(stderr):
            code = launch_service.main()
            secret = os.environ.get("CUSTOMER_CONTEXT_TUNNEL_SECRET")
        return code, secret, read, chdir, execute, stderr.getvalue()

    def test_keychain_value_stays_out_of_arguments_and_output(self):
        code, secret, read, chdir, execute, output = self.exercise(
            subprocess.CompletedProcess([], 0, "test-only-transport-value\n", "")
        )
        self.assertEqual(code, 0)
        self.assertEqual(secret, "test-only-transport-value")
        self.assertEqual(output, "")
        self.assertEqual(read.call_args.kwargs["timeout"], 15)
        chdir.assert_called_once_with(launch_service.ROOT)
        execute.assert_called_once_with(sys.executable, [sys.executable, str(launch_service.ROOT / "scripts/integration/start_local.py")])
        self.assertNotIn(secret, repr(execute.call_args))

    def test_failed_keychain_read_never_starts_service_or_logs_payload(self):
        code, _, _, chdir, execute, output = self.exercise(
            subprocess.CompletedProcess([], 1, "private-output", "private-error")
        )
        self.assertEqual(code, 1)
        chdir.assert_not_called()
        execute.assert_not_called()
        self.assertNotIn("private-", output)

    def test_empty_credential_never_starts_service(self):
        code, _, _, _, execute, _ = self.exercise(subprocess.CompletedProcess([], 0, "\n", ""))
        self.assertEqual(code, 1)
        execute.assert_not_called()

    def test_timeout_never_starts_service(self):
        code, _, _, _, execute, output = self.exercise(error=subprocess.TimeoutExpired("security", 15))
        self.assertEqual(code, 1)
        execute.assert_not_called()
        self.assertIn("could not be read", output)


if __name__ == "__main__":
    unittest.main()
