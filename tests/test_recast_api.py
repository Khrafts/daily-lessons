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

    def test_render_variant_sanitizes_model_output(self):
        # Model output is not a trust boundary: a recast reply carrying an XSS
        # payload must be scrubbed before it reaches the served lesson page.
        concept = json.loads((self.root / "index.json").read_text(encoding="utf-8"))[0]
        gen = {
            "dek": 'subtitle <code>x</code><img src=x onerror="steal()">',
            "one_liner": "ol",
            "body_html": ('<h2><span class="h2n">01</span> Heading</h2>'
                          '<script>exfil()</script>'
                          '<p onclick="evil()">legit paragraph</p>'
                          '<a href="javascript:boom()">link</a>'
                          '<style>.pwn{content:"STYLEPWNED"}</style>'
                          '<hr><iframe src="data:text/html,oops"></iframe>'),
        }
        result = chat_server.render_variant(RENDER, self.root, ASSETS,
                                            concept, "tutorial", gen)
        page = (self.root / result["file"]).read_text(encoding="utf-8")
        low = page.lower()
        # Unique payload tokens must be gone from the whole page. (Tokens are
        # chosen not to collide with the frozen shell's own legit CSS/JS.)
        for needle in ("exfil()", "evil()", "steal()", "boom()", "STYLEPWNED"):
            self.assertNotIn(needle, page)
        # These never appear in the frozen shell, so check them page-wide.
        for needle in ("onerror", "onclick", "javascript:"):
            self.assertNotIn(needle, low)
        # The article region (between the dek and the shell's <hr>) holds no
        # script/style/iframe — the shell's own legit <script> sits outside it.
        article = chat_server.extract_article_html(page).lower()
        for needle in ("<script", "<style", "<iframe"):
            self.assertNotIn(needle, article)
        # Legitimate lesson content survived the scrub.
        self.assertIn("01</span> Heading</h2>", page)
        self.assertIn("legit paragraph", page)


class LegacyRecastGuardTests(unittest.TestCase):
    """A legacy ledger record with no concept_key can't be recast (render_lesson
    --variant needs a concept_key, exit 2). The server must not OFFER generate
    buttons for it (renditions: available == []) and must reject a direct recast
    cleanly (422) rather than letting it blow up at render time."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dlc-legacy-"))
        self.root = self.tmp / "library"
        (self.root / "lessons").mkdir(parents=True)
        self.file = "lessons/2026-01-01-legacy.html"
        # A pre-modes lesson page on disk + a ledger record with NO concept_key
        # and NO mode — exactly what an old install carries.
        (self.root / self.file).write_text(
            "<!DOCTYPE html><html><body><div class='wrap'>"
            "<p class='dek'>old</p><h1>Legacy</h1></div></body></html>",
            encoding="utf-8")
        (self.root / "index.json").write_text(
            json.dumps([{"file": self.file, "title": "Legacy concept",
                         "one_liner": "from before modes", "tags": ["old"]}]),
            encoding="utf-8")
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

    def test_renditions_offers_no_generate_buttons(self):
        status, j = self._get_json("/api/renditions?lesson=" + self.file)
        self.assertEqual(status, 200, j)
        self.assertTrue(j["ok"])
        self.assertIsNone(j["concept_key"])
        # The "Original" tone still shows as a switch chip…
        self.assertEqual(len(j["renditions"]), 1)
        self.assertEqual(j["renditions"][0]["label"], "Original")
        # …but no tone is offered to generate (can't recast without a concept_key).
        self.assertEqual(j["available"], [])

    def test_recast_rejected_cleanly(self):
        status, j = self._post_json("/api/recast",
                                    {"lesson": self.file, "mode": "tutorial"})
        self.assertEqual(status, 422, j)
        self.assertFalse(j["ok"])
        self.assertIn("concept key", j["error"].lower())
        # And nothing was written — no new rendition file leaked into the library.
        extra = [p for p in (self.root / "lessons").iterdir()
                 if p.name != "2026-01-01-legacy.html"]
        self.assertEqual(extra, [])


class SanitizeHtmlTests(unittest.TestCase):
    """Unit coverage for strip_unsafe_html — the scrub applied to model output."""

    def s(self, x):
        return chat_server.strip_unsafe_html(x)

    def test_removes_script_and_style_with_content(self):
        out = self.s('<h2>ok</h2><script>alert(1)</script>'
                     '<style>body{}</style><p>fine</p>')
        self.assertNotIn("<script", out.lower())
        self.assertNotIn("<style", out.lower())
        self.assertNotIn("alert(1)", out)
        self.assertIn("<h2>ok</h2>", out)
        self.assertIn("<p>fine</p>", out)

    def test_defeats_nested_splice_evasion(self):
        # Naive single-pass removal would re-form <script> here.
        self.assertNotIn("<script", self.s("<scr<script>ipt>x</script>ipt>").lower())

    def test_case_insensitive(self):
        self.assertNotIn("<script", self.s("<ScRiPt>x</ScRiPt>").lower())

    def test_strips_event_handlers(self):
        self.assertNotIn("onerror", self.s('<img src=x onerror=alert(1)>').lower())
        self.assertNotIn("onclick", self.s('<p onclick="x()">y</p>').lower())

    def test_neutralizes_dangerous_url_schemes(self):
        self.assertNotIn("javascript:", self.s('<a href="javascript:x()">y</a>').lower())
        self.assertNotIn("vbscript:", self.s("<a href=vbscript:x>y</a>").lower())

    def test_removes_hr_and_iframe(self):
        out = self.s('<hr/><iframe src="evil"></iframe><p>p</p>').lower()
        self.assertNotIn("<hr", out)
        self.assertNotIn("<iframe", out)
        self.assertIn("<p>p</p>", out)

    def test_keeps_canonical_markup_unchanged(self):
        keep = ('<h2><span class="h2n">01</span> X</h2>'
                '<p class="lead">lead</p>'
                '<figure class="code"><figcaption><span>x.py</span>'
                '<button class="copy" type="button">Copy</button></figcaption>'
                '<pre><code class="language-python">x = 1</code></pre></figure>'
                '<details class="pit"><summary>s</summary>'
                '<div class="body">b</div></details>'
                '<em>e</em> <strong>b</strong> <code>c</code>')
        self.assertEqual(self.s(keep), keep)

    def test_empty_and_none(self):
        self.assertEqual(self.s(""), "")
        self.assertIsNone(self.s(None))

    # The corpus of inputs an adversarial red-team confirmed (browser-verified)
    # could defeat the earlier regex denylist: '/'-separated event handlers on
    # allowed tags, <img>/<noscript> handler smuggling, entity-encoded and
    # tab-split URL schemes, and CSS in a style attribute. None may survive the
    # re-parsing allowlist. (Tab in "jav\tascript" is intentional.)
    BYPASS_CORPUS = [
        '<details open/ontoggle=alert(document.domain)><summary>s</summary>x</details>',
        '<img src=x/onerror=alert(document.domain)>',
        '<noscript><img src=x/onerror=alert(document.domain)>',
        '<img src="x"/onerror="alert(document.domain)">',
        '<img/onerror="alert(document.cookie)" src="x">',
        '<figure style="background:url(http://attacker.example/p.png)">x</figure>',
        '<a href="&#106;avascript:alert(document.domain)">read more</a>',
        '<a href="jav\tascript:alert(document.domain)">read more</a>',
        '<a href="javascript&#58;alert(1)">click</a>',
        '<a href="java&#115;cript:alert(1)">x</a>',
        '<a href="&#x6a;avascript:alert(1)">x</a>',
        '<a href="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;alert(1)">x</a>',
        '<a href=" &#106;avascript:alert(1)">x</a>',
        '<svg><script>alert(1)</script></svg>',
    ]

    def test_blocks_confirmed_bypass_corpus(self):
        bad = ("javascript", "vbscript", "onerror", "ontoggle", "onclick",
               "onload", "alert", "attacker", "<script", "<img", "<iframe", "<svg")
        for payload in self.BYPASS_CORPUS:
            out = self.s(payload).lower()
            for token in bad:
                self.assertNotIn(token, out,
                                 "%r survived sanitization of %r -> %r"
                                 % (token, payload, out))

    def test_safe_urls_preserved(self):
        # Legitimate links must still work after sanitization.
        for url in ("https://example.com/docs",
                    "http://127.0.0.1:8765/lessons/x.html",
                    "lessons/x-tutorial.html", "#go-deeper", "mailto:a@b.com"):
            out = self.s('<a href="%s">link</a>' % url)
            self.assertIn('href="%s"' % url, out)
            self.assertIn(">link</a>", out)


if __name__ == "__main__":
    unittest.main()
