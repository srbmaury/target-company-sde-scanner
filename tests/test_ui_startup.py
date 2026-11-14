"""The dashboard must never silently use the local CLI profile."""

import errno
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from jobbot import accounts
from jobbot.ui import server


class DashboardStartupTests(unittest.TestCase):
    def test_response_handles_client_disconnect(self):
        for failure in (BrokenPipeError, ConnectionResetError):
            for stage in ("end_headers", "write"):
                with self.subTest(failure=failure, stage=stage):
                    handler = Mock()
                    target = handler if stage == "end_headers" else handler.wfile
                    getattr(target, stage).side_effect = failure
                    server.Handler._send(handler, 200, {"ok": True})
                    self.assertTrue(handler.close_connection)

        handler = Mock()
        handler.wfile.write.side_effect = OSError("unexpected write failure")
        with self.assertRaisesRegex(OSError, "unexpected"):
            server.Handler._send(handler, 200, {})

    def test_missing_mongodb_does_not_start_server(self):
        with patch.dict(os.environ, {"JOBBOT_MONGODB_URI": ""}), patch.object(server, "make_server") as make:
            with self.assertRaisesRegex(accounts.AccountError, "requires a hosted account"):
                server.serve()
            make.assert_not_called()

    def test_hosted_startup_prints_public_url(self):
        account = Mock(origin="https://jobbot.example.com")
        output = io.StringIO()
        with (patch.dict(os.environ, {"JOBBOT_MONGODB_URI": "mongodb://example.test", "JOBBOT_BIND": "0.0.0.0"}),
              patch.object(accounts, "current", return_value=account) as current,
              patch.object(server, "make_server") as make,
              patch.object(server.paths, "ensure_home"), redirect_stdout(output)):
            server.serve(port=8765)
        current.assert_called_once_with(8765)
        make.assert_called_once_with(8765, account, "0.0.0.0")
        account.initialize.assert_called_once()
        make.return_value.serve_forever.assert_called_once()
        make.return_value.server_close.assert_called_once()
        self.assertIn("jobbot account dashboard: https://jobbot.example.com", output.getvalue())

    def test_busy_port_does_not_change_oauth_port(self):
        with (patch.dict(os.environ, {"JOBBOT_MONGODB_URI": "mongodb://example.test"}),
              patch.object(accounts, "current", return_value=Mock()),
              patch.object(server.paths, "ensure_home"),
              patch.object(server, "make_server", side_effect=OSError(errno.EADDRINUSE, "busy")) as make):
            with self.assertRaisesRegex(accounts.AccountError, "Port 8765 is already in use"):
                server.serve()
            make.assert_called_once()

    @unittest.skipUnless(shutil.which("bash"), "Bash is required for jobbot.sh")
    def test_launcher_loads_repo_dotenv_for_ui_even_with_an_exported_uri(self):
        launcher = Path(__file__).resolve().parents[1] / "jobbot.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(launcher, root / "jobbot.sh")
            (root / ".env").write_text("JOBBOT_MONGODB_URI='mongodb://file.test'\n")
            mock_python = root / ".venv/bin/python"
            mock_python.parent.mkdir(parents=True)
            mock_python.write_text('#!/usr/bin/env bash\nprintf "%s" "${JOBBOT_MONGODB_URI:-unset}"\n')
            mock_python.chmod(0o700)
            env = {k: v for k, v in os.environ.items() if k != "JOBBOT_MONGODB_URI"}
            def launch(command, settings):
                return subprocess.check_output(["bash", str(root / "jobbot.sh"), command],
                                               cwd=root.parent, env=settings, text=True)
            self.assertEqual(launch("ui", env), "mongodb://file.test")
            self.assertEqual(launch("ui", dict(env, JOBBOT_MONGODB_URI="mongodb://env.test")), "mongodb://file.test")
            self.assertEqual(launch("doctor", env), "unset")
            (root / ".env").unlink()
            self.assertEqual(launch("ui", dict(env, JOBBOT_MONGODB_URI="mongodb://env.test")), "mongodb://env.test")
