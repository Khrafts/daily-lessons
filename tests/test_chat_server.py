"""Tests for scripts/chat_server.py — run: python3 -m unittest discover -s tests

Starts the real server (mock backend, OS-assigned port) against a throwaway
lessons dir; never touches the real library or the claude CLI."""

import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"
sys.path.insert(0, str(TESTS_DIR.parent / "scripts"))

import chat_server  # noqa: E402


SAMPLE_LESSON = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>#7 · Atomic Writes &amp; You</title>
<style>body{color:#111} .zzz-style-only{display:none}</style>
</head>
<body>
<nav class="topnav"><a href="../index.html">&larr; Library</a><span>Daily Lesson</span></nav>
<div class="wrap">
  <div class="meta">
    <span class="n">#7</span>
    <span>Taught&nbsp;2026-06-10</span>
  </div>
  <h1>Atomic Writes &amp; You</h1>
  <p class="dek">Why <code>os.replace</code> beats truncate &amp; pray.</p>
  <p>Body text with an &amp; entity and a &lt;tag&gt; literal.</p>
</div>
<script>var zzScriptOnly = "SCRIPT_ONLY_TOKEN";</script>
</body>
</html>
"""

MARKED_LESSON = """<!DOCTYPE html>
<html><head><title>#3 · Marked Lesson</title></head>
<body>
<h1>Marked Lesson</h1>
<p>This page already carries the chat widget.</p>
<!-- daily-lesson-chat:v1 -->
<div id="existing-widget"></div>
<!-- /daily-lesson-chat:v1 -->
</body></html>
"""

FIXTURE_SHELL = """<!DOCTYPE html>
<html><body>
<p>shell body</p>
<!-- daily-lesson-chat:v1 -->
<style>#dlc-test-widget{display:none}</style>
<div id="dlc-test-widget">hello from the widget fixture</div>
<!-- /daily-lesson-chat:v1 -->
</body></html>
"""


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.headers, resp.read()
    finally:
        conn.close()


def raw_http(port, payload):
    """Send raw bytes (so a test can omit the Host header entirely)."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(payload)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def parse_sse(raw):
    events = []
    for frame in raw.split("\n\n"):
        if not frame.strip():
            continue
        event, data = None, None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event, data))
    return events


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="dlc-test-"))
        cls.root = cls.tmp / "library"
        (cls.root / "lessons").mkdir(parents=True)
        cls.assets = cls.tmp / "assets"
        cls.assets.mkdir()
        (cls.assets / "lesson-shell.html").write_text(FIXTURE_SHELL, encoding="utf-8")
        (cls.tmp / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
        (cls.root / "index.html").write_text("<html><body>library</body></html>",
                                             encoding="utf-8")
        cls.sample = "lessons/2026-06-10-sample.html"
        cls.marked = "lessons/2026-06-09-marked.html"
        (cls.root / cls.sample).write_text(SAMPLE_LESSON, encoding="utf-8")
        (cls.root / cls.marked).write_text(MARKED_LESSON, encoding="utf-8")
        cls.srv = chat_server.build_server(0, cls.root, "mock", assets_dir=cls.assets)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=5)
        cls.srv.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def post_chat(self, lesson, message, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        return request(self.port, "POST", "/api/chat",
                       body=json.dumps({"lesson": lesson, "message": message}),
                       headers=headers)

    # (1) health

    def test_health(self):
        status, headers, data = request(self.port, "GET", "/api/health")
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["app"], "daily-lesson-chat")
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["backend"], "mock")
        self.assertIsInstance(body["plugin_version"], str)
        self.assertTrue(body["plugin_version"])           # never empty
        self.assertIsInstance(body["pid"], int)
        self.assertGreater(body["pid"], 0)
        # no Origin (curl) and a file:// page (Origin: null) may read it
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "null")
        _, h_null, _ = request(self.port, "GET", "/api/health",
                               headers={"Origin": "null"})
        self.assertEqual(h_null.get("Access-Control-Allow-Origin"), "null")
        # a real cross-origin website gets the body but NO CORS header
        _, h_web, web = request(self.port, "GET", "/api/health",
                                headers={"Origin": "https://evil.example"})
        self.assertIsNone(h_web.get("Access-Control-Allow-Origin"))
        self.assertTrue(json.loads(web)["ok"])

    def test_health_options(self):
        status, headers, data = request(self.port, "OPTIONS", "/api/health")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "null")
        self.assertEqual(headers.get("Access-Control-Allow-Methods"), "GET")
        self.assertEqual(data, b"")
        # a real website's preflight is not granted
        _, h_web, _ = request(self.port, "OPTIONS", "/api/health",
                              headers={"Origin": "https://evil.example"})
        self.assertIsNone(h_web.get("Access-Control-Allow-Origin"))

    # (2) origin policy

    def test_origin_policy(self):
        status, headers, data = self.post_chat(self.sample, "hi",
                                               origin="http://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"ok": False, "error": "cross-origin"})
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

        # same-origin and no-Origin both pass the guard (incomplete body -> 400,
        # proving the request got past the origin check without side effects)
        incomplete = json.dumps({"lesson": self.sample})
        status, _, _ = request(
            self.port, "POST", "/api/chat", body=incomplete,
            headers={"Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 400)
        status, _, _ = request(self.port, "POST", "/api/chat", body=incomplete,
                               headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    # (3) full mock roundtrip

    def test_mock_roundtrip(self):
        question = "What is this lesson about?"
        status, headers, raw = self.post_chat(self.sample, question)
        self.assertEqual(status, 200)
        self.assertTrue(headers.get("Content-Type", "").startswith("text/event-stream"))
        self.assertEqual(headers.get("Cache-Control"), "no-cache")

        events = parse_sse(raw.decode("utf-8"))
        deltas = [d for ev, d in events if ev == "delta"]
        dones = [d for ev, d in events if ev == "done"]
        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(len(dones), 1)
        done = dones[0]
        self.assertEqual("".join(d["text"] for d in deltas), done["text"])
        self.assertTrue(done["session_id"].startswith("mock-"))
        self.assertIn('You asked: "%s"' % question, done["text"])
        self.assertIn('Mock tutor for "Atomic Writes & You"', done["text"])

        # done payload now also carries the conversation id it landed in
        self.assertIn("conversation", done)
        conv_id = done["conversation"]
        self.assertTrue(conv_id.startswith("c-"))

        chats = json.loads((self.root / "chats.json").read_text(encoding="utf-8"))
        self.assertIn(self.sample, chats)
        entry = chats[self.sample]
        self.assertEqual(entry["active_id"], conv_id)
        self.assertEqual(len(entry["conversations"]), 1)
        conv = entry["conversations"][0]
        self.assertEqual(conv["id"], conv_id)
        self.assertEqual(conv["session_id"], done["session_id"])

        status, _, data = request(self.port, "GET",
                                  "/api/chat?lesson=" + self.sample)
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["lesson"], self.sample)
        self.assertEqual(body["active_id"], conv_id)
        self.assertEqual(body["conversation"], conv_id)
        self.assertEqual(body["session_id"], done["session_id"])
        self.assertEqual([m["role"] for m in body["messages"]],
                         ["user", "assistant"])
        self.assertEqual(body["messages"][0]["text"], question)
        self.assertEqual(body["messages"][1]["text"], done["text"])
        for msg in body["messages"]:
            self.assertIn("ts", msg)
        # the conversation summary reflects the turn
        self.assertEqual(len(body["conversations"]), 1)
        summary = body["conversations"][0]
        self.assertEqual(summary["id"], conv_id)
        self.assertEqual(summary["message_count"], 2)
        self.assertEqual(summary["title"], question)  # title from first user msg

        # second turn resumes the same session
        status, _, raw2 = self.post_chat(self.sample, "And another thing?")
        self.assertEqual(status, 200)
        done2 = [d for ev, d in parse_sse(raw2.decode("utf-8")) if ev == "done"][0]
        self.assertEqual(done2["session_id"], done["session_id"])
        _, _, data = request(self.port, "GET", "/api/chat?lesson=" + self.sample)
        self.assertEqual(len(json.loads(data)["messages"]), 4)

    # (4) reset

    def test_reset(self):
        status, _, _ = self.post_chat(self.marked, "hello")
        self.assertEqual(status, 200)
        _, _, data = request(self.port, "GET", "/api/chat?lesson=" + self.marked)
        self.assertEqual(len(json.loads(data)["messages"]), 2)

        status, _, data = request(
            self.port, "POST", "/api/chat/reset",
            body=json.dumps({"lesson": self.marked}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"ok": True})

        _, _, data = request(self.port, "GET", "/api/chat?lesson=" + self.marked)
        body = json.loads(data)
        self.assertIsNone(body["session_id"])
        self.assertEqual(body["messages"], [])
        self.assertIsNone(body["active_id"])
        self.assertEqual(body["conversations"], [])

    # (5) widget injection

    def test_widget_injection(self):
        disk = (self.root / self.sample).read_bytes()
        self.assertNotIn(b"daily-lesson-chat:v1", disk)
        status, _, served = request(self.port, "GET", "/" + self.sample)
        self.assertEqual(status, 200)
        text = served.decode("utf-8")
        self.assertEqual(text.count(chat_server.WIDGET_START), 1)
        self.assertEqual(text.count(chat_server.WIDGET_END), 1)
        self.assertIn('id="dlc-test-widget"', text)
        self.assertLess(text.find(chat_server.WIDGET_START), text.rfind("</body>"))
        # serve-time only: the file on disk is untouched
        self.assertEqual((self.root / self.sample).read_bytes(), disk)

        # a page carrying an OLDER/different block is UPGRADED to the current
        # one at serve time (so served lessons always run the latest widget)
        status, _, served_marked = request(self.port, "GET", "/" + self.marked)
        self.assertEqual(status, 200)
        marked_text = served_marked.decode("utf-8")
        self.assertEqual(marked_text.count(chat_server.WIDGET_START), 1)
        self.assertIn('id="dlc-test-widget"', marked_text)     # current block in
        self.assertNotIn('id="existing-widget"', marked_text)  # stale block out
        self.assertEqual((self.root / self.marked).read_bytes(),
                         MARKED_LESSON.encode("utf-8"))         # disk untouched

        # a page already carrying the IDENTICAL current block is byte-identical
        current = chat_server.load_widget_block(self.assets)
        ident_rel = "lessons/2026-06-10-identical.html"
        ident_page = "<html><body><h1>x</h1>\n" + current + "\n</body></html>"
        (self.root / ident_rel).write_text(ident_page, encoding="utf-8")
        _, _, served_ident = request(self.port, "GET", "/" + ident_rel)
        self.assertEqual(served_ident, ident_page.encode("utf-8"))

    # (6) unknown lesson + bad bodies

    def test_unknown_lesson_and_bad_body(self):
        status, _, data = request(self.port, "GET",
                                  "/api/chat?lesson=lessons/nope.html")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"ok": False, "error": "unknown lesson"})

        status, _, _ = self.post_chat("lessons/nope.html", "hi")
        self.assertEqual(status, 404)

        status, _, _ = request(self.port, "POST", "/api/chat", body="{not json",
                               headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

        status, _, _ = request(self.port, "POST", "/api/chat",
                               body=json.dumps({"lesson": self.sample}),
                               headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

        status, _, _ = request(self.port, "GET", "/api/chat")
        self.assertEqual(status, 400)

    # (7) path traversal

    def test_path_traversal(self):
        for path in ("/../secret.txt",
                     "/lessons/..%2f..%2fsecret.txt",
                     "/..%2Fsecret.txt"):
            status, _, data = request(self.port, "GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"TOP SECRET", data, path)
        status, _, _ = request(self.port, "GET", "/nope.html")
        self.assertEqual(status, 404)

    def test_static_index(self):
        for path in ("/", "/index.html"):
            status, headers, data = request(self.port, "GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(b"library", data)
            self.assertTrue(headers.get("Content-Type", "").startswith("text/html"))


# (8) stream-json parser against the captured fixture

class StreamJsonParserTests(unittest.TestCase):
    def fixture_lines(self):
        return (FIXTURES / "stream_json_sample.jsonl").read_text(
            encoding="utf-8").splitlines()

    def test_fixture_stream(self):
        events = list(chat_server.parse_stream_json_lines(self.fixture_lines()))
        # thinking block start + signature_delta ignored; only the text delta survives
        self.assertEqual(events[:-1], [("delta", "OK")])
        kind, done = events[-1]
        self.assertEqual(kind, "done")
        self.assertEqual(done["session_id"], "b49c9fa8-501c-4a8b-a424-0972c3cf4dc6")
        self.assertEqual(done["text"], "OK")

    def test_garbage_lines_ignored(self):
        lines = ["not json at all", "", "[1, 2, 3]"] + self.fixture_lines()
        events = list(chat_server.parse_stream_json_lines(lines))
        self.assertEqual(events[:-1], [("delta", "OK")])
        self.assertEqual(events[-1][0], "done")

    def test_error_result_raises(self):
        lines = [json.dumps({"type": "result", "subtype": "error_during_execution",
                             "is_error": True, "result": "boom", "session_id": "x"})]
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            list(chat_server.parse_stream_json_lines(lines))
        self.assertIn("boom", str(ctx.exception))

    def test_errors_array_surfaces(self):
        lines = [json.dumps({"type": "result", "subtype": "error_during_execution",
                             "is_error": True,
                             "errors": ["No conversation found with session ID: abc",
                                        "second cause"]})]
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            list(chat_server.parse_stream_json_lines(lines))
        self.assertIn("No conversation found with session ID: abc; second cause",
                      str(ctx.exception))

    def test_fallback_to_assistant_text(self):
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            json.dumps({"type": "assistant",
                        "message": {"content": [{"type": "text",
                                                 "text": "fallback text"}]}}),
            json.dumps({"type": "result", "subtype": "success",
                        "is_error": False, "session_id": "s1"}),
        ]
        events = list(chat_server.parse_stream_json_lines(lines))
        self.assertEqual(events,
                         [("done", {"session_id": "s1", "text": "fallback text"})])


# (9) lesson text extraction

class LessonExtractionTests(unittest.TestCase):
    def test_text_extraction(self):
        text = chat_server.extract_lesson_text(SAMPLE_LESSON)
        self.assertNotIn("SCRIPT_ONLY_TOKEN", text)   # <script> subtree dropped
        self.assertNotIn("zzz-style-only", text)      # <style> subtree dropped
        self.assertIn("Atomic Writes & You", text)    # entities unescaped
        self.assertIn("<tag>", text)                  # unescape happens after tag strip
        self.assertNotIn("\n", text)                  # whitespace collapsed
        self.assertNotIn("  ", text)

    def test_text_cap(self):
        big = "<html><body>" + "<p>word </p>" * 10000 + "</body></html>"
        self.assertLessEqual(len(chat_server.extract_lesson_text(big)), 30000)

    def test_title(self):
        self.assertEqual(chat_server.extract_lesson_title(SAMPLE_LESSON),
                         "Atomic Writes & You")
        self.assertEqual(chat_server.extract_lesson_title("<html><body></body></html>"),
                         "Untitled lesson")

    def test_system_prompt(self):
        text = chat_server.extract_lesson_text(SAMPLE_LESSON)
        prompt = chat_server.build_system_prompt("Atomic Writes & You", text)
        self.assertIn("Daily Lesson tutor", prompt)
        self.assertIn("LESSON #7: Atomic Writes & You", prompt)
        self.assertTrue(prompt.endswith("---"))


# (9b) title derivation

class TitleDerivationTests(unittest.TestCase):
    def test_empty_and_whitespace(self):
        self.assertEqual(chat_server.derive_title(""), "New chat")
        self.assertEqual(chat_server.derive_title("   \n\t  "), "New chat")
        self.assertEqual(chat_server.derive_title(None), "New chat")

    def test_whitespace_collapse(self):
        self.assertEqual(chat_server.derive_title("  hello   there\n\tworld "),
                         "hello there world")

    def test_truncation_with_ellipsis(self):
        text = "x" * 60
        title = chat_server.derive_title(text)
        self.assertEqual(len(title), 49)          # 48 chars + ellipsis
        self.assertEqual(title, "x" * 48 + "…")
        # exactly 48 chars -> no ellipsis
        self.assertEqual(chat_server.derive_title("y" * 48), "y" * 48)
        self.assertEqual(chat_server.derive_title("z" * 49), "z" * 48 + "…")


# (9c) v1 -> v2 migration at ChatStore load

class MigrationTests(unittest.TestCase):
    def make_store(self, v1_data):
        tmp = Path(tempfile.mkdtemp(prefix="dlc-migrate-"))
        self.addCleanup(shutil.rmtree, str(tmp), ignore_errors=True)
        (tmp / "chats.json").write_text(json.dumps(v1_data), encoding="utf-8")
        return tmp, chat_server.ChatStore(tmp)

    def test_v1_entry_migrates_losslessly(self):
        v1 = {
            "lessons/a.html": {
                "session_id": "sid-a",
                "messages": [
                    {"role": "user", "text": "How do atomic writes work?",
                     "ts": "2026-06-10T01:00:00+00:00"},
                    {"role": "assistant", "text": "Like this.",
                     "ts": "2026-06-10T01:00:05+00:00"},
                ],
            },
            "lessons/empty.html": {"session_id": None, "messages": []},
        }
        tmp, store = self.make_store(v1)

        a = store.data["lessons/a.html"]
        self.assertIn("conversations", a)
        self.assertEqual(len(a["conversations"]), 1)
        conv = a["conversations"][0]
        self.assertTrue(conv["id"].startswith("c-"))
        self.assertEqual(a["active_id"], conv["id"])
        self.assertEqual(conv["session_id"], "sid-a")
        # messages preserved verbatim
        self.assertEqual(conv["messages"], v1["lessons/a.html"]["messages"])
        # title derived from the first user message
        self.assertEqual(conv["title"], "How do atomic writes work?")
        # timestamps borrowed from the bounding messages
        self.assertEqual(conv["created_at"], "2026-06-10T01:00:00+00:00")
        self.assertEqual(conv["updated_at"], "2026-06-10T01:00:05+00:00")

        # empty v1 entry degrades to an empty v2 entry
        empty = store.data["lessons/empty.html"]
        self.assertEqual(empty, {"conversations": [], "active_id": None})

        # migration ran once and was persisted to disk
        on_disk = json.loads((tmp / "chats.json").read_text(encoding="utf-8"))
        self.assertIn("conversations", on_disk["lessons/a.html"])

    def test_session_only_no_messages_migrates(self):
        # session_id truthy but no messages -> still one conversation
        _, store = self.make_store(
            {"lessons/s.html": {"session_id": "sid-x", "messages": []}})
        s = store.data["lessons/s.html"]
        self.assertEqual(len(s["conversations"]), 1)
        conv = s["conversations"][0]
        self.assertEqual(conv["session_id"], "sid-x")
        self.assertEqual(conv["title"], "New chat")   # no user message to derive from
        self.assertEqual(conv["messages"], [])
        self.assertEqual(s["active_id"], conv["id"])

    def test_migration_is_idempotent(self):
        v1 = {"lessons/a.html": {"session_id": "sid-a",
                                 "messages": [{"role": "user", "text": "q",
                                               "ts": "2026-06-10T01:00:00+00:00"}]}}
        tmp, store = self.make_store(v1)
        bytes_after_first = (tmp / "chats.json").read_bytes()
        conv_id = store.data["lessons/a.html"]["active_id"]

        # reload: already-v2 entries are left untouched (stable bytes, same id)
        store2 = chat_server.ChatStore(tmp)
        self.assertEqual(store2.data["lessons/a.html"]["active_id"], conv_id)
        self.assertEqual((tmp / "chats.json").read_bytes(), bytes_after_first)

    def test_corrupt_entry_degrades(self):
        _, store = self.make_store({"lessons/bad.html": "not a dict",
                                    "lessons/zero.html": 0})
        self.assertEqual(store.data["lessons/bad.html"],
                         {"conversations": [], "active_id": None})
        self.assertEqual(store.data["lessons/zero.html"],
                         {"conversations": [], "active_id": None})

    def test_already_v2_untouched(self):
        v2 = {"lessons/a.html": {
            "conversations": [{"id": "c-deadbeef0001", "title": "Kept",
                               "session_id": "s", "messages": [],
                               "created_at": "t", "updated_at": "t"}],
            "active_id": "c-deadbeef0001"}}
        tmp, store = self.make_store(v2)
        self.assertEqual(store.data["lessons/a.html"]["active_id"], "c-deadbeef0001")
        self.assertEqual(store.data["lessons/a.html"]["conversations"][0]["id"],
                         "c-deadbeef0001")

    def test_malformed_v2_non_list_conversations_is_rebuilt(self):
        # a dict that carries the key but with a non-list value is NOT v2; it
        # must be rebuilt to an empty entry, not left to crash on first use.
        _, store = self.make_store(
            {"lessons/x.html": {"conversations": "oops", "active_id": None}})
        self.assertEqual(store.data["lessons/x.html"],
                         {"conversations": [], "active_id": None})
        # every operation on it is now safe (no AttributeError)
        self.assertEqual(store.get_view("lessons/x.html")["messages"], [])
        cid, _ = store.new_conversation("lessons/x.html")
        self.assertTrue(store.has_conversation("lessons/x.html", cid))

    def test_v2_missing_active_id_is_normalized(self):
        # valid conversations list but no active_id key -> it gets filled in,
        # and get_view must not KeyError.
        conv = {"id": "c-aaaa00000001", "title": "Kept", "session_id": "s",
                "messages": [], "created_at": "2026-06-10T01:00:00+00:00",
                "updated_at": "2026-06-10T01:00:00+00:00"}
        _, store = self.make_store({"lessons/x.html": {"conversations": [conv]}})
        self.assertEqual(store.data["lessons/x.html"]["active_id"], "c-aaaa00000001")
        self.assertEqual(store.get_view("lessons/x.html")["active_id"],
                         "c-aaaa00000001")

    def test_v2_dangling_active_id_is_repaired(self):
        # active_id pointing at a nonexistent conversation -> repaired to the
        # live one (here, the only conversation), never left dangling.
        conv = {"id": "c-bbbb00000001", "title": "Kept", "session_id": None,
                "messages": [], "created_at": "2026-06-10T01:00:00+00:00",
                "updated_at": "2026-06-10T01:00:00+00:00"}
        _, store = self.make_store({"lessons/x.html": {
            "conversations": [conv], "active_id": "c-nonexistent"}})
        self.assertEqual(store.data["lessons/x.html"]["active_id"], "c-bbbb00000001")


# (10) host pin, turn locking, SSE error path, chats.json privacy
# Separate server sandbox so these tests never disturb HttpApiTests' state.

class ServerHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="dlc-hard-"))
        cls.root = cls.tmp / "library"
        (cls.root / "lessons").mkdir(parents=True)
        cls.assets = cls.tmp / "assets"
        cls.assets.mkdir()
        (cls.assets / "lesson-shell.html").write_text(FIXTURE_SHELL, encoding="utf-8")
        cls.srv = chat_server.build_server(0, cls.root, "mock", assets_dir=cls.assets)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=5)
        cls.srv.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def make_lesson(self, name):
        rel = "lessons/%s.html" % name
        (self.root / rel).write_text(SAMPLE_LESSON, encoding="utf-8")
        return rel

    def post_chat(self, lesson, message, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return request(self.port, "POST", "/api/chat",
                       body=json.dumps({"lesson": lesson, "message": message}),
                       headers=h)

    def post_reset(self, lesson):
        return request(self.port, "POST", "/api/chat/reset",
                       body=json.dumps({"lesson": lesson}),
                       headers={"Content-Type": "application/json"})

    # FIX 1: DNS-rebinding host pin

    def test_host_pin_rejects_foreign_host(self):
        lesson = self.make_lesson("host-evil")
        for method, path in (("GET", "/api/health"), ("GET", "/index.html"),
                             ("OPTIONS", "/api/health")):
            status, _, data = request(self.port, method, path,
                                      headers={"Host": "evil.example"})
            self.assertEqual(status, 403, "%s %s" % (method, path))
            self.assertEqual(json.loads(data),
                             {"ok": False, "error": "forbidden host"})
        # POST with no Origin at all is still refused on Host alone
        status, _, data = self.post_chat(lesson, "hi",
                                         headers={"Host": "evil.example:8787"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"ok": False, "error": "forbidden host"})
        # ... and the rejected POST stored nothing
        status, _, data = request(self.port, "GET", "/api/chat?lesson=" + lesson)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["messages"], [])

    def test_host_pin_allows_local_hosts(self):
        for host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port,
                     "localhost", "127.0.0.1", "[::1]:%d" % self.port):
            status, _, data = request(self.port, "GET", "/api/health",
                                      headers={"Host": host})
            self.assertEqual(status, 200, host)
            self.assertTrue(json.loads(data)["ok"])
        lesson = self.make_lesson("host-ok")
        status, _, _ = self.post_chat(lesson, "hello",
                                      headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(status, 200)
        status, _, _ = self.post_chat(lesson, "hello again",
                                      headers={"Host": "127.0.0.1:%d" % self.port})
        self.assertEqual(status, 200)

    def test_missing_host_header_rejected(self):
        raw = raw_http(self.port,
                       b"GET /api/health HTTP/1.1\r\nConnection: close\r\n\r\n")
        self.assertTrue(raw.startswith(b"HTTP/1.1 403"), raw[:80])
        self.assertIn(b"forbidden host", raw)

    # FIX 3d: chats.json is never served statically

    def test_chats_json_not_served(self):
        lesson = self.make_lesson("private")
        status, _, _ = self.post_chat(lesson, "secret question")
        self.assertEqual(status, 200)
        self.assertTrue((self.root / "chats.json").exists())
        status, _, data = request(self.port, "GET", "/chats.json")
        self.assertEqual(status, 404)
        self.assertNotIn(b"secret question", data)
        # transcripts are still reachable through the API
        status, _, data = request(self.port, "GET", "/api/chat?lesson=" + lesson)
        self.assertEqual(status, 200)
        self.assertIn("secret question", data.decode("utf-8"))

    # FIX 3c + 409-busy: one turn per lesson, reset refused mid-turn

    def test_turn_lock_busy(self):
        lesson = self.make_lesson("busy")
        other = self.make_lesson("busy-other")
        gate = threading.Event()
        started = threading.Event()
        real = self.srv.run_turn

        def gated(lesson_rel, title, text, message, session_id):
            if lesson_rel == lesson:
                started.set()
                gate.wait(timeout=10)
            yield ("delta", "ok")
            yield ("done", {"session_id": "gated-sid", "text": "ok"})

        self.srv.run_turn = gated
        try:
            results = {}
            t = threading.Thread(
                target=lambda: results.update(slow=self.post_chat(lesson, "slow")),
                daemon=True)
            t.start()
            self.assertTrue(started.wait(timeout=5))
            status, _, data = self.post_chat(lesson, "second")
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(data), {"ok": False, "error": "busy"})
            status, _, data = self.post_reset(lesson)
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(data), {"ok": False, "error": "busy"})
            # a different lesson is not blocked
            status, _, _ = self.post_chat(other, "parallel")
            self.assertEqual(status, 200)
            gate.set()
            t.join(timeout=10)
            self.assertEqual(results["slow"][0], 200)
            # lock released: both endpoints work again
            status, _, _ = self.post_chat(lesson, "after release")
            self.assertEqual(status, 200)
            status, _, _ = self.post_reset(lesson)
            self.assertEqual(status, 200)
        finally:
            self.srv.run_turn = real
            gate.set()

    # SSE error path: error frame reaches the reader, lock is released

    def test_sse_error_path_releases_lock(self):
        lesson = self.make_lesson("kaboom")
        real = self.srv.run_turn

        def explode(lesson_rel, title, text, message, session_id):
            yield ("delta", "partial ")
            raise chat_server.ChatBackendError("kaboom")

        self.srv.run_turn = explode
        try:
            status, _, raw = self.post_chat(lesson, "trigger")
            self.assertEqual(status, 200)
            events = parse_sse(raw.decode("utf-8"))
            self.assertEqual(events[0], ("delta", {"text": "partial "}))
            self.assertEqual(events[1][0], "error")
            self.assertIn("kaboom", events[1][1]["message"])
            self.assertEqual(len(events), 2)
            # the failed turn persisted the user message only
            status, _, data = request(self.port, "GET", "/api/chat?lesson=" + lesson)
            body = json.loads(data)
            self.assertEqual([m["role"] for m in body["messages"]], ["user"])
            self.assertEqual(body["messages"][0]["text"], "trigger")
        finally:
            self.srv.run_turn = real
        # the lock was released: the next turn succeeds with the mock backend
        status, _, raw = self.post_chat(lesson, "recovered?")
        self.assertEqual(status, 200)
        self.assertTrue(any(ev == "done" for ev, _ in
                            parse_sse(raw.decode("utf-8"))))


# (10b) multiple conversations per lesson: new / switch / delete / continuity

class ConversationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="dlc-conv-"))
        cls.root = cls.tmp / "library"
        (cls.root / "lessons").mkdir(parents=True)
        cls.assets = cls.tmp / "assets"
        cls.assets.mkdir()
        (cls.assets / "lesson-shell.html").write_text(FIXTURE_SHELL, encoding="utf-8")
        cls.srv = chat_server.build_server(0, cls.root, "mock", assets_dir=cls.assets)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=5)
        cls.srv.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def make_lesson(self, name):
        rel = "lessons/%s.html" % name
        (self.root / rel).write_text(SAMPLE_LESSON, encoding="utf-8")
        return rel

    def post(self, path, payload):
        return request(self.port, "POST", path, body=json.dumps(payload),
                       headers={"Content-Type": "application/json"})

    def post_chat(self, lesson, message, conversation=None):
        payload = {"lesson": lesson, "message": message}
        if conversation is not None:
            payload["conversation"] = conversation
        status, _, raw = self.post("/api/chat", payload)
        events = parse_sse(raw.decode("utf-8")) if status == 200 else []
        done = next((d for ev, d in events if ev == "done"), None)
        return status, done

    def get_chat(self, lesson, conversation=None):
        q = "/api/chat?lesson=" + lesson
        if conversation is not None:
            q += "&conversation=" + conversation
        status, _, data = request(self.port, "GET", q)
        return status, json.loads(data)

    # (2) NEW does not clear an existing conversation

    def test_new_does_not_clear(self):
        lesson = self.make_lesson("new-keeps")
        status, done = self.post_chat(lesson, "first question in A")
        self.assertEqual(status, 200)
        conv_a = done["conversation"]

        status, _, data = self.post("/api/chat/new", {"lesson": lesson})
        self.assertEqual(status, 200)
        body = json.loads(data)
        conv_b = body["id"]
        self.assertEqual(body["active_id"], conv_b)
        self.assertNotEqual(conv_a, conv_b)
        # two conversations now exist; the new one is empty
        ids = {c["id"] for c in body["conversations"]}
        self.assertEqual(ids, {conv_a, conv_b})
        new_summary = next(c for c in body["conversations"] if c["id"] == conv_b)
        self.assertEqual(new_summary["message_count"], 0)
        self.assertEqual(new_summary["title"], "New chat")

        # conv A is still fully retrievable by id, with its messages intact
        status, view = self.get_chat(lesson, conv_a)
        self.assertEqual(status, 200)
        self.assertEqual(view["conversation"], conv_a)
        self.assertEqual([m["role"] for m in view["messages"]],
                         ["user", "assistant"])
        self.assertEqual(view["messages"][0]["text"], "first question in A")
        # reading by id does NOT move active_id away from B
        self.assertEqual(view["active_id"], conv_b)

    # TOCTOU: delete winning the pre-lock window must be a clean 404, not a
    # streamed-but-lost reply on a phantom conversation id.

    def test_delete_winning_toctou_is_clean_404_not_silent_loss(self):
        lesson = self.make_lesson("toctou")
        _, done = self.post_chat(lesson, "in the doomed conversation")
        conv = done["conversation"]
        store = self.srv.store
        real = store.has_conversation
        state = {"n": 0}

        def racy(les, cid):
            state["n"] += 1
            if state["n"] == 1:                 # pre-lock check: looks present,
                store.delete_conversation(les, cid)  # but delete wins the race
                return True
            return real(les, cid)               # in-lock recheck sees it gone

        store.has_conversation = racy
        try:
            status, done2 = self.post_chat(lesson, "into the void", conversation=conv)
        finally:
            store.has_conversation = real
        self.assertEqual(status, 404)           # clean 404 before any SSE byte
        self.assertIsNone(done2)
        self.assertFalse(store.has_conversation(lesson, conv))  # no phantom left

    # (8) GET base shape + sorting newest-updated-first

    def test_get_base_shape_and_sorting(self):
        lesson = self.make_lesson("sorted")
        _, done_a = self.post_chat(lesson, "older conversation")
        conv_a = done_a["conversation"]
        self.post("/api/chat/new", {"lesson": lesson})
        # send into the newer (now active) conversation
        _, done_b = self.post_chat(lesson, "newer conversation")
        conv_b = done_b["conversation"]

        status, view = self.get_chat(lesson)
        self.assertEqual(status, 200)
        for key in ("ok", "lesson", "active_id", "conversations", "messages",
                    "session_id", "conversation"):
            self.assertIn(key, view)
        # newest-updated-first: B was touched last
        self.assertEqual([c["id"] for c in view["conversations"]][0], conv_b)
        self.assertIn(conv_a, [c["id"] for c in view["conversations"]])
        for summary in view["conversations"]:
            for key in ("id", "title", "session_id", "message_count",
                        "created_at", "updated_at"):
                self.assertIn(key, summary)
        # default selection is the active (B)
        self.assertEqual(view["conversation"], conv_b)

    # (3) SWITCH sets active and returns the right messages; unknown -> 404

    def test_switch(self):
        lesson = self.make_lesson("switch")
        _, done_a = self.post_chat(lesson, "alpha message")
        conv_a = done_a["conversation"]
        status, _, data = self.post("/api/chat/new", {"lesson": lesson})
        conv_b = json.loads(data)["id"]
        # active is B; switch back to A
        status, _, data = self.post("/api/chat/switch",
                                    {"lesson": lesson, "conversation": conv_a})
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["active_id"], conv_a)
        self.assertEqual(body["conversation"], conv_a)
        self.assertEqual(body["messages"][0]["text"], "alpha message")
        # GET with no conversation= now returns A as the active one
        _, view = self.get_chat(lesson)
        self.assertEqual(view["active_id"], conv_a)

        # unknown id -> 404
        status, _, data = self.post("/api/chat/switch",
                                    {"lesson": lesson, "conversation": "c-doesnotexist"})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"ok": False, "error": "unknown conversation"})

    # (4) DELETE removes, reassigns active to most-recent remaining (or null)

    def test_delete_reassigns_active(self):
        lesson = self.make_lesson("delete")
        _, done_a = self.post_chat(lesson, "in A")
        conv_a = done_a["conversation"]
        self.post("/api/chat/new", {"lesson": lesson})
        _, done_b = self.post_chat(lesson, "in B")
        conv_b = done_b["conversation"]   # B is active and most-recently-updated

        # delete A (not active) -> active stays B
        status, _, data = self.post("/api/chat/delete",
                                    {"lesson": lesson, "conversation": conv_a})
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["active_id"], conv_b)
        self.assertEqual([c["id"] for c in body["conversations"]], [conv_b])

        # delete B (the active one) -> nothing remains -> active null
        status, _, data = self.post("/api/chat/delete",
                                    {"lesson": lesson, "conversation": conv_b})
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertIsNone(body["active_id"])
        self.assertEqual(body["conversations"], [])

        # unknown id -> 404
        status, _, data = self.post("/api/chat/delete",
                                    {"lesson": lesson, "conversation": "c-nope"})
        self.assertEqual(status, 404)

    def test_delete_active_reassigns_to_most_recent(self):
        lesson = self.make_lesson("delete-recent")
        _, da = self.post_chat(lesson, "A")
        conv_a = da["conversation"]
        self.post("/api/chat/new", {"lesson": lesson})
        _, db = self.post_chat(lesson, "B")
        conv_b = db["conversation"]
        self.post("/api/chat/new", {"lesson": lesson})
        _, dc = self.post_chat(lesson, "C")   # C active, newest
        conv_c = dc["conversation"]
        # touch A so it becomes the most-recently-updated of {A,B}
        self.post_chat(lesson, "A again", conversation=conv_a)
        # delete the active C -> active should jump to A (most recent remaining)
        status, _, data = self.post("/api/chat/delete",
                                    {"lesson": lesson, "conversation": conv_c})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["active_id"], conv_a)
        self.assertIn(conv_b, [c["id"] for c in json.loads(data)["conversations"]])

    # (4) DELETE refused (409) while a turn is in flight in that lesson

    def test_delete_busy_while_turn_in_flight(self):
        lesson = self.make_lesson("delete-busy")
        gate = threading.Event()
        started = threading.Event()
        real = self.srv.run_turn

        def gated(lesson_rel, title, text, message, session_id):
            if lesson_rel == lesson:
                started.set()
                gate.wait(timeout=10)
            yield ("delta", "ok")
            yield ("done", {"session_id": "g-sid", "text": "ok"})

        self.srv.run_turn = gated
        try:
            results = {}
            t = threading.Thread(
                target=lambda: results.update(r=self.post_chat(lesson, "slow")),
                daemon=True)
            t.start()
            self.assertTrue(started.wait(timeout=5))
            # a turn is mid-flight on this lesson's active conversation
            _, view = self.get_chat(lesson)
            active = view["active_id"]
            status, _, data = self.post("/api/chat/delete",
                                        {"lesson": lesson, "conversation": active})
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(data), {"ok": False, "error": "busy"})
            gate.set()
            t.join(timeout=10)
            self.assertEqual(results["r"][0], 200)
            # lock released: delete now works
            status, _, _ = self.post("/api/chat/delete",
                                     {"lesson": lesson, "conversation": active})
            self.assertEqual(status, 200)
        finally:
            self.srv.run_turn = real
            gate.set()

    # (5) per-conversation session continuity + isolation

    def test_per_conversation_session_continuity(self):
        lesson = self.make_lesson("continuity")
        # two turns in conversation A reuse one session id
        _, d1 = self.post_chat(lesson, "A turn 1")
        conv_a = d1["conversation"]
        sid_a = d1["session_id"]
        _, d2 = self.post_chat(lesson, "A turn 2", conversation=conv_a)
        self.assertEqual(d2["conversation"], conv_a)
        self.assertEqual(d2["session_id"], sid_a)

        # a new conversation gets its OWN session id
        _, _, data = self.post("/api/chat/new", {"lesson": lesson})
        conv_b = json.loads(data)["id"]
        _, d3 = self.post_chat(lesson, "B turn 1", conversation=conv_b)
        self.assertEqual(d3["conversation"], conv_b)
        self.assertNotEqual(d3["session_id"], sid_a)
        sid_b = d3["session_id"]

        # isolation is visible in chats.json: distinct session ids per conversation
        chats = json.loads((self.root / "chats.json").read_text(encoding="utf-8"))
        convs = {c["id"]: c for c in chats[lesson]["conversations"]}
        self.assertEqual(convs[conv_a]["session_id"], sid_a)
        self.assertEqual(convs[conv_b]["session_id"], sid_b)
        self.assertNotEqual(convs[conv_a]["session_id"], convs[conv_b]["session_id"])
        # A has 4 messages (2 turns), B has 2 (1 turn)
        self.assertEqual(len(convs[conv_a]["messages"]), 4)
        self.assertEqual(len(convs[conv_b]["messages"]), 2)

    # (6) POST with an explicit unknown conversation -> 404 before streaming

    def test_post_unknown_conversation_404_before_stream(self):
        lesson = self.make_lesson("post-unknown")
        status, _, data = self.post(
            "/api/chat",
            {"lesson": lesson, "message": "hi", "conversation": "c-missing00000"})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"ok": False, "error": "unknown conversation"})
        # nothing was created for that lesson
        _, view = self.get_chat(lesson)
        self.assertEqual(view["conversations"], [])

    # (1)/auto-create: POST with no active conversation creates one

    def test_post_auto_creates_when_no_active(self):
        lesson = self.make_lesson("auto-create")
        _, view = self.get_chat(lesson)
        self.assertIsNone(view["active_id"])
        status, done = self.post_chat(lesson, "kick it off")
        self.assertEqual(status, 200)
        self.assertTrue(done["conversation"].startswith("c-"))
        _, view = self.get_chat(lesson)
        self.assertEqual(view["active_id"], done["conversation"])
        self.assertEqual(len(view["conversations"]), 1)

    # (7) reset wipes ALL conversations

    def test_reset_wipes_all(self):
        lesson = self.make_lesson("reset-all")
        self.post_chat(lesson, "one")
        self.post("/api/chat/new", {"lesson": lesson})
        self.post_chat(lesson, "two")
        _, view = self.get_chat(lesson)
        self.assertEqual(len(view["conversations"]), 2)

        status, _, data = self.post("/api/chat/reset", {"lesson": lesson})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"ok": True})
        _, view = self.get_chat(lesson)
        self.assertEqual(view["conversations"], [])
        self.assertIsNone(view["active_id"])

    # bad bodies / unknown lesson on the new endpoints

    def test_bad_bodies_and_unknown_lesson(self):
        lesson = self.make_lesson("badbody")
        # missing lesson
        for path in ("/api/chat/new", "/api/chat/switch", "/api/chat/delete",
                     "/api/chat/reset"):
            status, _, _ = self.post(path, {})
            self.assertEqual(status, 400, path)
        # unknown lesson
        for path in ("/api/chat/new", "/api/chat/reset"):
            status, _, data = self.post(path, {"lesson": "lessons/ghost.html"})
            self.assertEqual(status, 404, path)
            self.assertEqual(json.loads(data), {"ok": False, "error": "unknown lesson"})
        # switch/delete missing conversation field
        for path in ("/api/chat/switch", "/api/chat/delete"):
            status, _, _ = self.post(path, {"lesson": lesson})
            self.assertEqual(status, 400, path)
        # unknown conversation on a GET
        status, _, data = request(
            self.port, "GET",
            "/api/chat?lesson=%s&conversation=c-nope000" % lesson)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"ok": False, "error": "unknown conversation"})


# (11) claude backend against a fake `claude` executable

FAKE_CLAUDE = '''#!/usr/bin/env python3
"""Fake claude CLI: records argv+stdin, then behaves per mode.txt."""
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read(),
                        "cwd": os.getcwd()}) + "\\n")
mode = open(os.path.join(d, "mode.txt")).read().strip()
STALE = {"type": "result", "subtype": "error_during_execution", "is_error": True,
         "errors": ["No conversation found with session ID: stale-sid"]}
if mode == "exit3":
    sys.stderr.write("auth failed")
    sys.exit(3)
if mode == "noresult":
    print(json.dumps({"type": "system", "subtype": "init", "session_id": "s-init"}))
    sys.exit(0)
if mode == "error-with-stderr":
    sys.stderr.write("stderr-detail")
    sys.stderr.flush()
    print(json.dumps({"type": "result", "subtype": "error_during_execution",
                      "is_error": True, "result": "boom"}))
    sys.exit(1)
if mode == "stale-resume" and "--resume" in sys.argv:
    print(json.dumps(STALE))
    sys.exit(1)
if mode == "delta-then-stale":
    print(json.dumps({"type": "stream_event",
                      "event": {"type": "content_block_delta", "index": 0,
                                "delta": {"type": "text_delta", "text": "half"}}}))
    print(json.dumps(STALE))
    sys.exit(1)
sys.stdout.write(open(os.path.join(d, "stream.jsonl")).read())
sys.exit(0)
'''


class ClaudeBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dlc-fakecli-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)
        self.bin = self.tmp / "claude"
        self.bin.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.bin.chmod(0o755)
        shutil.copyfile(str(FIXTURES / "stream_json_sample.jsonl"),
                        str(self.tmp / "stream.jsonl"))
        self.lessons = self.tmp / "library"
        self.lessons.mkdir()
        self.run_turn = chat_server.make_claude_backend(str(self.bin), self.lessons)

    def set_mode(self, mode):
        (self.tmp / "mode.txt").write_text(mode, encoding="utf-8")

    def calls(self):
        path = self.tmp / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()]

    def turn(self, message="hello tutor", session_id=None):
        return list(self.run_turn("lessons/x.html", "Title", "lesson text",
                                  message, session_id))

    # (a) success: deltas + done, message on stdin, no --resume on first turn

    def test_success_message_via_stdin_no_resume(self):
        self.set_mode("success")
        message = "--dash-prefixed message, not a flag"
        events = self.turn(message=message)
        self.assertEqual(events[:-1], [("delta", "OK")])
        kind, done = events[-1]
        self.assertEqual(kind, "done")
        self.assertEqual(done["session_id"], "b49c9fa8-501c-4a8b-a424-0972c3cf4dc6")
        self.assertEqual(done["text"], "OK")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["stdin"], message)
        self.assertNotIn(message, argv)        # never on argv
        self.assertNotIn("--resume", argv)
        self.assertEqual(argv[argv.index("-p") + 1], "--output-format")

    # (b) stored session id -> --resume <sid>

    def test_resume_flag_on_second_turn(self):
        self.set_mode("success")
        self.turn(session_id="sid-123")
        argv = self.calls()[0]["argv"]
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "sid-123")

    # tool root is the lessons/ subdir, so chats.json (one level up) is out of reach

    def test_tool_root_is_lessons_subdir(self):
        self.set_mode("success")
        self.turn()
        self.assertTrue(self.calls()[0]["cwd"].endswith(os.sep + "lessons"))

    # a malformed (user-edited) session id is never passed to --resume

    def test_invalid_session_id_not_resumed(self):
        self.set_mode("success")
        for bad in ("--dangerous-flag", "../escape", "has space", ""):
            (self.tmp / "calls.jsonl").unlink(missing_ok=True)
            self.turn(session_id=bad)
            self.assertNotIn("--resume", self.calls()[0]["argv"])

    # (c) nonzero exit surfaces code + stderr

    def test_nonzero_exit_surfaces_stderr(self):
        self.set_mode("exit3")
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            self.turn()
        msg = str(ctx.exception)
        self.assertIn("exited 3", msg)
        self.assertIn("auth failed", msg)

    # (d) stream without a result event

    def test_missing_result_event(self):
        self.set_mode("noresult")
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            self.turn()
        self.assertIn("without a result", str(ctx.exception))

    # (e) stale --resume self-heals once, without --resume

    def test_stale_resume_self_heals(self):
        self.set_mode("stale-resume")
        events = self.turn(session_id="stale-sid")
        self.assertEqual(events[:-1], [("delta", "OK")])
        kind, done = events[-1]
        self.assertEqual(kind, "done")
        self.assertEqual(done["text"], "OK")
        self.assertEqual(done["session_id"], "b49c9fa8-501c-4a8b-a424-0972c3cf4dc6")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("--resume", calls[0]["argv"])
        self.assertNotIn("--resume", calls[1]["argv"])
        self.assertEqual(calls[1]["stdin"], "hello tutor")

    def test_no_retry_after_delta_reached_client(self):
        self.set_mode("delta-then-stale")
        with self.assertRaises(chat_server.ChatBackendError):
            self.turn(session_id="stale-sid")
        self.assertEqual(len(self.calls()), 1)

    # FIX 2c: the error path still appends the stderr tail

    def test_error_path_appends_stderr_tail(self):
        self.set_mode("error-with-stderr")
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            self.turn()
        msg = str(ctx.exception)
        self.assertIn("boom", msg)
        self.assertIn("stderr-detail", msg)

    # (f) nonexistent binary -> friendly error

    def test_missing_binary(self):
        run_turn = chat_server.make_claude_backend(
            str(self.tmp / "definitely-not-claude"), self.lessons)
        with self.assertRaises(chat_server.ChatBackendError) as ctx:
            list(run_turn("lessons/x.html", "T", "t", "hi", None))
        self.assertIn("claude CLI not found", str(ctx.exception))


class WidgetBlockTests(unittest.TestCase):
    def test_markers_missing(self):
        tmp = Path(tempfile.mkdtemp(prefix="dlc-shell-"))
        try:
            (tmp / "lesson-shell.html").write_text("<html><body></body></html>",
                                                   encoding="utf-8")
            self.assertIsNone(chat_server.load_widget_block(tmp))
            self.assertIsNone(chat_server.load_widget_block(tmp / "nope"))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_real_shell_carries_chat_and_modes_blocks(self):
        # The frozen shell must keep BOTH injectable blocks, or serve-time
        # injection silently no-ops (load_widget_block returns None). This is
        # unconditional (no skip), so deleting/renaming either marker — or
        # gutting the modes block's bar/modal — goes RED here.
        assets = TESTS_DIR.parent / "assets"
        chat = chat_server.load_widget_block(assets, chat_server.WIDGET_START,
                                             chat_server.WIDGET_END)
        modes = chat_server.load_widget_block(assets, chat_server.MODES_START,
                                              chat_server.MODES_END)
        self.assertIsNotNone(chat, "chat widget block missing from lesson-shell.html")
        self.assertIsNotNone(modes, "modes block missing from lesson-shell.html")
        self.assertIn('data-testid="modes-bar"', modes)   # the tone bar
        self.assertIn('id="dlm-confirm"', modes)          # the confirm modal


class InjectWidgetTests(unittest.TestCase):
    BLOCK = (chat_server.WIDGET_START + "\n<div id=cur></div>\n"
             + chat_server.WIDGET_END)

    def test_inserts_when_absent(self):
        out = chat_server.inject_widget(b"<html><body>x</body></html>", self.BLOCK)
        text = out.decode("utf-8")
        self.assertEqual(text.count(chat_server.WIDGET_START), 1)
        self.assertLess(text.find(chat_server.WIDGET_START), text.rfind("</body>"))

    def test_replaces_older_block(self):
        old = (chat_server.WIDGET_START + "\n<div id=old></div>\n"
               + chat_server.WIDGET_END)
        page = ("<html><body>x\n" + old + "\n</body></html>").encode("utf-8")
        out = chat_server.inject_widget(page, self.BLOCK).decode("utf-8")
        self.assertIn("id=cur", out)
        self.assertNotIn("id=old", out)
        self.assertEqual(out.count(chat_server.WIDGET_START), 1)

    def test_identical_block_is_byte_identical(self):
        page = ("<html><body>x\n" + self.BLOCK + "\n</body></html>").encode("utf-8")
        self.assertEqual(chat_server.inject_widget(page, self.BLOCK), page)

    def test_orphan_start_marker_does_not_double_inject(self):
        # a START with no END is garbled — bail rather than append a 2nd block
        page = ("<html><body>x\n" + chat_server.WIDGET_START
                + "\n<div id=stuck></div>\n</body></html>").encode("utf-8")
        out = chat_server.inject_widget(page, self.BLOCK)
        self.assertEqual(out, page)
        self.assertEqual(out.decode("utf-8").count(chat_server.WIDGET_START), 1)


class InjectModesTests(unittest.TestCase):
    """The tone/modes block injects exactly like the chat widget — same routine,
    different markers. _serve_static calls inject_widget for BOTH, so legacy
    pages gain the tone bar + confirm modal too; this locks that path in."""
    START = chat_server.MODES_START
    END = chat_server.MODES_END
    BLOCK = chat_server.MODES_START + "\n<div id=cur-modes></div>\n" + chat_server.MODES_END

    def _inject(self, page):
        return chat_server.inject_widget(page, self.BLOCK, self.START, self.END)

    def test_inserts_when_absent(self):
        out = self._inject(b"<html><body>x</body></html>").decode("utf-8")
        self.assertEqual(out.count(self.START), 1)
        self.assertLess(out.find(self.START), out.rfind("</body>"))

    def test_replaces_older_block(self):
        old = self.START + "\n<div id=old-modes></div>\n" + self.END
        page = ("<html><body>x\n" + old + "\n</body></html>").encode("utf-8")
        out = self._inject(page).decode("utf-8")
        self.assertIn("id=cur-modes", out)
        self.assertNotIn("id=old-modes", out)
        self.assertEqual(out.count(self.START), 1)

    def test_identical_block_is_byte_identical(self):
        page = ("<html><body>x\n" + self.BLOCK + "\n</body></html>").encode("utf-8")
        self.assertEqual(self._inject(page), page)

    def test_orphan_start_marker_does_not_double_inject(self):
        page = ("<html><body>x\n" + self.START
                + "\n<div id=stuck-modes></div>\n</body></html>").encode("utf-8")
        out = self._inject(page)
        self.assertEqual(out, page)
        self.assertEqual(out.decode("utf-8").count(self.START), 1)


class ModesInjectionServerTests(unittest.TestCase):
    """Serve-time integration: a legacy lesson whose on-disk HTML lacks the modes
    block gets the REAL tone-bar + confirm-modal block (read from the actual
    assets/lesson-shell.html) injected when served — without rewriting the file.
    This is the legacy-page guarantee for the modes feature, mirroring
    HttpApiTests.test_widget_injection for the chat widget."""
    REAL_ASSETS = TESTS_DIR.parent / "assets"

    @classmethod
    def setUpClass(cls):
        if chat_server.load_widget_block(cls.REAL_ASSETS, chat_server.MODES_START,
                                         chat_server.MODES_END) is None:
            raise unittest.SkipTest("assets/lesson-shell.html lacks the modes block")
        cls.tmp = Path(tempfile.mkdtemp(prefix="dlc-modes-"))
        cls.root = cls.tmp / "library"
        (cls.root / "lessons").mkdir(parents=True)
        cls.legacy = "lessons/2026-01-01-legacy.html"
        cls.legacy_html = ("<!DOCTYPE html><html><body><div class='wrap'>"
                           "<p class='dek'>d</p><h1>Legacy</h1></div></body></html>")
        (cls.root / cls.legacy).write_text(cls.legacy_html, encoding="utf-8")
        cls.stale = "lessons/2026-01-02-stale.html"
        cls.stale_html = ("<!DOCTYPE html><html><body><div class='wrap'>x\n"
                          + chat_server.MODES_START + "\n<div id=old-modes></div>\n"
                          + chat_server.MODES_END + "\n</div></body></html>")
        (cls.root / cls.stale).write_text(cls.stale_html, encoding="utf-8")
        cls.srv = chat_server.build_server(0, cls.root, "mock", assets_dir=cls.REAL_ASSETS)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=5)
        cls.srv.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_legacy_page_gains_modes_block_at_serve_time(self):
        disk = (self.root / self.legacy).read_bytes()
        self.assertNotIn(b"daily-lesson-modes:v1", disk)   # absent on disk
        status, _, served = request(self.port, "GET", "/" + self.legacy)
        self.assertEqual(status, 200)
        text = served.decode("utf-8")
        self.assertEqual(text.count(chat_server.MODES_START), 1)
        self.assertEqual(text.count(chat_server.MODES_END), 1)
        # the actual tone bar + confirm modal landed on the legacy page
        self.assertIn('data-testid="modes-bar"', text)
        self.assertIn('id="dlm-confirm"', text)
        self.assertLess(text.find(chat_server.MODES_START), text.rfind("</body>"))
        # serve-time only: the file on disk is untouched
        self.assertEqual((self.root / self.legacy).read_bytes(), disk)

    def test_stale_modes_block_is_upgraded(self):
        status, _, served = request(self.port, "GET", "/" + self.stale)
        self.assertEqual(status, 200)
        text = served.decode("utf-8")
        self.assertEqual(text.count(chat_server.MODES_START), 1)
        self.assertNotIn("id=old-modes", text)             # stale block replaced
        self.assertIn('data-testid="modes-bar"', text)
        self.assertEqual((self.root / self.stale).read_bytes(),
                         self.stale_html.encode("utf-8"))   # disk untouched


if __name__ == "__main__":
    unittest.main()
