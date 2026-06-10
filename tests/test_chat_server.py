"""Tests for scripts/chat_server.py — run: python3 -m unittest discover -s tests

Starts the real server (mock backend, OS-assigned port) against a throwaway
lessons dir; never touches the real library or the claude CLI."""

import http.client
import json
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
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(json.loads(data),
                         {"ok": True, "app": "daily-lesson-chat",
                          "version": 1, "backend": "mock"})

    def test_health_options(self):
        status, headers, data = request(self.port, "OPTIONS", "/api/health")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(headers.get("Access-Control-Allow-Methods"), "GET")
        self.assertEqual(data, b"")

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

        chats = json.loads((self.root / "chats.json").read_text(encoding="utf-8"))
        self.assertIn(self.sample, chats)
        self.assertEqual(chats[self.sample]["session_id"], done["session_id"])

        status, _, data = request(self.port, "GET",
                                  "/api/chat?lesson=" + self.sample)
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["lesson"], self.sample)
        self.assertEqual(body["session_id"], done["session_id"])
        self.assertEqual([m["role"] for m in body["messages"]],
                         ["user", "assistant"])
        self.assertEqual(body["messages"][0]["text"], question)
        self.assertEqual(body["messages"][1]["text"], done["text"])
        for msg in body["messages"]:
            self.assertIn("ts", msg)

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

        # marker already present -> byte-identical to disk
        disk_marked = (self.root / self.marked).read_bytes()
        status, _, served_marked = request(self.port, "GET", "/" + self.marked)
        self.assertEqual(status, 200)
        self.assertEqual(served_marked, disk_marked)

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


# (11) claude backend against a fake `claude` executable

FAKE_CLAUDE = '''#!/usr/bin/env python3
"""Fake claude CLI: records argv+stdin, then behaves per mode.txt."""
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}) + "\\n")
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


if __name__ == "__main__":
    unittest.main()
