"""Tests for scripts/serve.sh — the idempotent chat-server launcher.

serve.sh must: start the server detached and print its base URL on a cold call,
then on a second call reuse the running instance (fast, no second listener).
Uses the mock backend so no `claude` CLI or tokens are involved; the health
endpoint these tests hit never touches the backend anyway.
"""

import json
import os
import shutil
import socket
import subprocess
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVE = REPO / "scripts" / "serve.sh"


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _pids_on(port):
    if not shutil.which("lsof"):
        return []
    out = subprocess.run(["lsof", "-ti", ":%d" % port],
                         capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


@unittest.skipUnless(SERVE.is_file(), "serve.sh not present")
@unittest.skipUnless(shutil.which("python3") and shutil.which("curl"),
                     "needs python3 + curl")
class ServeShTests(unittest.TestCase):
    def setUp(self):
        self.port = _free_port()
        self.log = "/tmp/serve-sh-test-%d.log" % self.port
        self.env = dict(os.environ,
                        DAILY_LESSON_CHAT_BACKEND="mock",
                        DAILY_LESSON_CHAT_LOG=self.log)

    def tearDown(self):
        for pid in _pids_on(self.port):
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        try:
            os.remove(self.log)
        except OSError:
            pass

    def _run(self):
        return subprocess.run(["sh", str(SERVE), str(self.port)],
                              capture_output=True, text=True,
                              env=self.env, timeout=20)

    def test_cold_start_then_idempotent_reuse(self):
        # Cold start: prints the URL, exits 0, server answers health.
        r1 = self._run()
        self.assertEqual(r1.returncode, 0, r1.stderr)
        base = r1.stdout.strip()
        self.assertEqual(base, "http://127.0.0.1:%d" % self.port)

        body = urllib.request.urlopen(base + "/api/health", timeout=3).read()
        health = json.loads(body)
        self.assertTrue(health["ok"])
        self.assertEqual(health["app"], "daily-lesson-chat")

        if shutil.which("lsof"):
            self.assertEqual(len(_pids_on(self.port)), 1)

        # Second call: same URL, reuses the instance — fast and no new listener.
        start = time.monotonic()
        r2 = self._run()
        elapsed = time.monotonic() - start
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(r2.stdout.strip(), base)
        self.assertLess(elapsed, 3.0, "reuse path should not re-poll for ~6s")
        if shutil.which("lsof"):
            self.assertEqual(len(_pids_on(self.port)), 1,
                             "reuse must not start a second server")

    def test_replaces_stale_version(self):
        # A server reporting an OLD plugin version is started directly (not via
        # serve.sh). serve.sh must retire it and bring up the current version.
        server = REPO / "scripts" / "chat_server.py"
        stale_env = dict(self.env, DAILY_LESSON_PLUGIN_VERSION="0.0.1-stale")
        stale = subprocess.Popen(
            ["python3", str(server), "--port", str(self.port)],
            env=stale_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(stale.terminate)

        base = "http://127.0.0.1:%d" % self.port
        for _ in range(40):
            try:
                body = urllib.request.urlopen(base + "/api/health", timeout=2).read()
                if json.loads(body).get("plugin_version") == "0.0.1-stale":
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            self.fail("stale server never came up")
        stale_pid = stale.pid

        # serve.sh with normal env: should replace the stale instance.
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), base)

        # The live server now reports the REAL manifest version, not the stale one.
        expected = json.loads(
            (REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
        body = json.loads(urllib.request.urlopen(base + "/api/health", timeout=3).read())
        self.assertEqual(body["plugin_version"], expected)
        self.assertNotEqual(body["pid"], stale_pid)

        # The stale process is gone, and exactly one listener remains.
        for _ in range(20):
            if stale.poll() is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(stale.poll(), "stale server was not killed")
        if shutil.which("lsof"):
            self.assertEqual(len(_pids_on(self.port)), 1)


if __name__ == "__main__":
    unittest.main()
