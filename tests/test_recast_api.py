"""Tests for the modes/recast HTTP API in scripts/chat_server.py.

GET /api/renditions lists a concept's existing tones + the modes not yet
generated; POST /api/recast generates an alternate-tone rendition (via the mock
backend here) and persists it as a sibling lesson. The library is built with the
REAL renderer and REAL assets so --variant and serve-time injection are exercised
end to end against a throwaway dir; the claude CLI is never invoked (mock backend)."""

import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent
ASSETS = REPO / "assets"
RENDER = REPO / "scripts" / "render_lesson.py"
sys.path.insert(0, str(REPO / "scripts"))

import chat_server  # noqa: E402

ORIGIN_HDR = {"Content-Type": "application/json"}


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.headers, resp.read()
    finally:
        conn.close()


def render_primary(root, slug, concept_key, title, mode):
    meta = {"slug": slug, "concept_key": concept_key, "title": title,
            "dek": "Why <code>%s</code> matters." % slug,
            "one_liner": "%s in one line." % title,
            "source_day": "2026-06-15", "taught_at": "2026-06-16T09:00:00+01:00",
            "tags": ["evm", "test"], "mode": mode}
    body = ('<h2><span class="h2n">01</span> What it is</h2>'
            '<p class="lead">The original grounded lesson body.</p>'
            '<h2><span class="h2n">04</span> A worked example</h2>'
            '<figure class="code"><figcaption><span>x.py</span>'
            '<button class="copy" type="button">Copy</button></figcaption>'
            '<pre><code class="language-python">x = 1</code></pre></figure>')
    with tempfile.TemporaryDirectory() as td:
        mp, bp = Path(td) / "m.json", Path(td) / "b.html"
        mp.write_text(json.dumps(meta), encoding="utf-8")
        bp.write_text(body, encoding="utf-8")
        out = subprocess.run([sys.executable, str(RENDER), "--meta", str(mp),
                              "--body", str(bp), "--lessons-dir", str(root),
                              "--assets-dir", str(ASSETS)],
                             capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["file"]


@unittest.skipUnless(RENDER.is_file(), "render_lesson.py not present")
class RecastApiTests(unittest.TestCase):
    # Per-test isolation: each test gets a fresh library + server, so a recast
    # in one test never leaks renditions into another (tests run in any order).
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dlc-recast-"))
        self.root = self.tmp / "library"
        (self.root / "lessons").mkdir(parents=True)
        self.primary = render_primary(self.root, "erc7201", "evm-erc7201",
                                      "Namespaced storage", "grounded")
        self.srv = chat_server.build_server(0, self.root, "mock", assets_dir=ASSETS)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown()
        self.thread.join(timeout=5)
        self.srv.server_close()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def _get_json(self, path):
        status, _, data = request(self.port, "GET", path)
        return status, json.loads(data)

    def _post_json(self, path, payload):
        status, _, data = request(self.port, "POST", path,
                                  body=json.dumps(payload), headers=ORIGIN_HDR)
        return status, json.loads(data)

    def test_renditions_initial(self):
        status, j = self._get_json("/api/renditions?lesson=" + self.primary)
        self.assertEqual(status, 200)
        self.assertTrue(j["ok"])
        self.assertEqual(j["current_mode"], "grounded")
        self.assertEqual(j["concept_key"], "evm-erc7201")
        self.assertEqual(len(j["renditions"]), 1)
        self.assertTrue(j["renditions"][0]["current"])
        avail = {a["mode"] for a in j["available"]}
        self.assertEqual(avail, {"tutorial", "deep", "briefing"})

    def test_renditions_unknown_lesson(self):
        status, j = self._get_json("/api/renditions?lesson=lessons/nope.html")
        self.assertEqual(status, 404)
        self.assertFalse(j["ok"])

    def test_recast_unknown_mode(self):
        status, j = self._post_json("/api/recast",
                                    {"lesson": self.primary, "mode": "bogus"})
        self.assertEqual(status, 400)
        self.assertFalse(j["ok"])

    def test_recast_unknown_lesson(self):
        status, j = self._post_json("/api/recast",
                                    {"lesson": "lessons/nope.html", "mode": "tutorial"})
        self.assertEqual(status, 404)

    def test_recast_creates_and_is_idempotent(self):
        # Generate a Tutorial rendition of the grounded primary.
        status, j = self._post_json("/api/recast",
                                    {"lesson": self.primary, "mode": "tutorial"})
        self.assertEqual(status, 200, j)
        self.assertTrue(j["ok"])
        self.assertFalse(j["already"])
        self.assertEqual(j["mode"], "tutorial")
        self.assertTrue(j["file"].endswith("-tutorial.html"), j["file"])
        self.assertTrue((self.root / j["file"]).is_file())

        # The new rendition is served with BOTH shell blocks injected.
        status, _, page = request(self.port, "GET", "/" + j["file"])
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn(chat_server.MODES_START, page)
        self.assertIn(chat_server.WIDGET_START, page)

        # The concept now has two tones; tutorial is no longer "available".
        _, r = self._get_json("/api/renditions?lesson=" + self.primary)
        self.assertEqual(len(r["renditions"]), 2)
        self.assertEqual({a["mode"] for a in r["available"]}, {"deep", "briefing"})
        files = {x["file"] for x in r["renditions"]}
        self.assertIn(j["file"], files)

        # Idempotent: asking for the same tone again returns it, doesn't dup.
        status, again = self._post_json("/api/recast",
                                        {"lesson": self.primary, "mode": "tutorial"})
        self.assertEqual(status, 200)
        self.assertTrue(again["already"])
        self.assertEqual(again["file"], j["file"])


if __name__ == "__main__":
    unittest.main()
