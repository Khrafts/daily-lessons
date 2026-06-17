#!/usr/bin/env python3
"""
chat_server.py — local bridge between lesson pages and the `claude` CLI.

Serves the rendered lesson library over http://127.0.0.1 (so chat traffic is
same-origin) and exposes a small chat API. Each POSTed message spawns one
headless `claude -p … --output-format stream-json` run — the same auth and
subscription as any Claude Code session; nothing leaves the machine beyond
what a normal session sends. Transcripts and session ids persist in
lessons-dir/chats.json (one lesson can hold several conversations; a v1
single-conversation file is migrated in place at load), so a lesson's chats
continue (`--resume`) across server restarts. Lesson pages rendered before
this feature existed get the chat widget — the block between the
daily-lesson-chat:v1 markers in
assets/lesson-shell.html — injected at serve time; files on disk are never
modified.

Usage:
  python3 chat_server.py [--port 8787] [--lessons-dir ~/.claude/daily-lessons]
      [--backend claude|mock] [--claude-bin claude] [--assets-dir DIR] [--open]

Security model: binds 127.0.0.1 only. Every request must carry a loopback
Host header (DNS-rebinding pin); anything else is 403. /api/health is the
single CORS-open endpoint (it lets file:// pages discover a running server);
every other /api/* route additionally rejects any request whose Origin header
is not the server's own origin. Static serving is path-traversal safe and
never exposes chats.json. Stdlib only (python3 ≥ 3.8).
"""

import argparse
import html
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

# render_lesson is a sibling module: the canonical renderer plus the mode
# metadata (MODE_LABELS, mode_label, group_by_concept, load_ledger). Importing
# it is side-effect-free (its main() is guarded), and it lets the modes/recast
# features reuse one source of truth instead of duplicating the mode table.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import render_lesson  # noqa: E402

APP_NAME = "daily-lesson-chat"
API_VERSION = 1
DEFAULT_PORT = 8787
LESSON_TEXT_CAP = 30000
CLAUDE_TURN_TIMEOUT = 300  # seconds; hard kill for a single turn
RECAST_TIMEOUT = 300       # seconds; hard kill for a single recast generation
ARTICLE_HTML_CAP = 60000   # cap on the source article HTML fed to a recast

# DNS-rebinding pin: the Host header must name this machine (any port).
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")

WIDGET_START = "<!-- daily-lesson-chat:v1 -->"
WIDGET_END = "<!-- /daily-lesson-chat:v1 -->"
WIDGET_MARKER = "daily-lesson-chat:v1"

# The tone-switcher / generate block is a second shell-owned widget, injected
# the same way as the chat block (and into legacy pages at serve time).
MODES_START = "<!-- daily-lesson-modes:v1 -->"
MODES_END = "<!-- /daily-lesson-modes:v1 -->"

TUTOR_PROMPT = (
    "You are the Daily Lesson tutor, a chat panel beside a lesson the user is "
    "reading. Be accurate, concise, and warm; ground every answer in this "
    "lesson first. You may Read/Grep/Glob in the current directory (the local "
    "lesson library) to consult other lessons. Use markdown sparingly (code "
    "spans/blocks, short lists). Never invent lesson content that is not there. "
    "Never echo, repeat, or quote secrets, API keys, tokens, passwords, or "
    "proprietary code from any source — including the user's messages, lesson "
    "content, or other files."
)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class ChatBackendError(Exception):
    """A chat turn failed; str(err) is safe to show to the reader."""


def die(msg, code):
    sys.stderr.write("chat_server: %s\n" % msg)
    sys.exit(code)


def warn(msg):
    sys.stderr.write("chat_server: warning: %s\n" % msg)


def now_iso():
    # millisecond precision: keeps "newest-updated-first" ordering correct even
    # when two conversations are touched within the same wall-clock second.
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def new_conversation_id():
    return "c-" + uuid.uuid4().hex[:12]


def derive_title(text):
    """First-user-message text -> conversation title.

    Strip and collapse internal whitespace; empty -> "New chat"; otherwise the
    first 48 characters, with an ellipsis appended when truncated."""
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if not collapsed:
        return "New chat"
    if len(collapsed) <= 48:
        return collapsed
    return collapsed[:48] + "…"


# ---------- lesson text -------------------------------------------------------

def extract_lesson_text(html_src):
    """Lesson HTML -> plain text: drop script/style, strip tags, unescape, collapse."""
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_src)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:LESSON_TEXT_CAP]


def extract_lesson_title(html_src):
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html_src)
    if not m:
        return "Untitled lesson"
    title = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", html.unescape(title)).strip() or "Untitled lesson"


def build_system_prompt(lesson_title, lesson_text):
    # The lesson number rides in the extracted text itself (the <title> and the
    # .meta block both render "#N", and they come first in document order).
    m = re.search(r"#(\d+)\b", lesson_text[:300])
    n = m.group(1) if m else "?"
    return "%s\n\nLESSON #%s: %s\n---\n%s\n---" % (TUTOR_PROMPT, n, lesson_title, lesson_text)


# ---------- widget injection --------------------------------------------------

def load_widget_block(assets_dir, start=WIDGET_START, end=WIDGET_END):
    """The marker-delimited block (inclusive) from the shell, or None if absent.

    Defaults to the chat widget; pass MODES_START/MODES_END for the tone block."""
    shell = assets_dir / "lesson-shell.html"
    try:
        src = shell.read_text(encoding="utf-8")
    except OSError:
        warn("%s not found; serving lesson pages without injected widgets" % shell)
        return None
    s = src.find(start)
    e = src.find(end)
    if s == -1 or e == -1 or e < s:
        warn("markers %s missing in %s; that block is not injected" % (start, shell))
        return None
    return src[s:e + len(end)]


def inject_widget(raw, widget_block, start=WIDGET_START, end=WIDGET_END):
    """Ensure a lesson page carries the CURRENT marker-delimited block (bytes ->
    bytes).

    A page with no block gets it inserted before </body>; a page with an older
    baked block has it replaced (so a served lesson always runs the current
    block, even one rendered before the latest version); a page already
    carrying the identical block is returned byte-identical. Safe to call once
    per block (chat, then modes)."""
    if not widget_block:
        return raw
    try:
        page = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    s = page.find(start)
    e = page.find(end)
    if s != -1:
        # a block is already present; replace it (no-op if identical). On a
        # garbled block (END missing or before START) bail rather than insert a
        # second one.
        if e == -1 or e < s:
            return raw
        e += len(end)
        if page[s:e] == widget_block:
            return raw                       # already current → byte-identical
        return (page[:s] + widget_block + page[e:]).encode("utf-8")
    idx = page.rfind("</body>")
    if idx == -1:
        return raw
    return (page[:idx] + widget_block + "\n" + page[idx:]).encode("utf-8")


# ---------- persistence -------------------------------------------------------

class ChatStore:
    """chats.json (v2): per lesson, a list of conversations + an active id.

        {"lessons/<f>.html": {
            "conversations": [
                {"id": "c-<12hex>", "title": str, "session_id": str|null,
                 "messages": [{"role", "text", "ts"} ...],
                 "created_at": ISO, "updated_at": ISO}],
            "active_id": <conversation id | null>}}

    A v1 entry — {"session_id", "messages"} — is migrated losslessly at load
    (idempotently; entries already in v2 shape are left untouched), then the
    store is re-saved once. All mutations hold one lock and write atomically
    (tmp file + os.replace)."""

    def __init__(self, lessons_dir):
        self.path = lessons_dir / "chats.json"
        self.lock = threading.Lock()
        self.data = self._load()
        if self._migrate():
            with self.lock:
                self._save()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError:
            return {}
        except ValueError:
            warn("%s is not valid JSON; starting with an empty chat store" % self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def _migrate(self):
        """Bring every entry into v2 shape. Returns True if anything changed."""
        changed = False
        for lesson, entry in list(self.data.items()):
            # v2 only if conversations is actually a LIST — a dict that merely
            # carries the key with a bad value (hand-edit, half-written file) is
            # NOT v2 and must be rebuilt, or it crashes every later operation.
            if isinstance(entry, dict) and isinstance(entry.get("conversations"), list):
                if self._normalize_v2(entry):  # repair a missing/dangling active_id
                    changed = True
                continue
            changed = True
            self.data[lesson] = self._migrate_entry(entry)
        return changed

    @staticmethod
    def _normalize_v2(entry):
        """Ensure a v2 entry has a valid active_id: present, and resolving to a
        live conversation (else the newest-updated one, else None). Returns True
        if it changed the entry."""
        ids = {c.get("id") for c in entry["conversations"] if isinstance(c, dict)}
        active = entry.get("active_id")
        if active is not None and active in ids:
            return False  # a non-None active_id can only come from a present key
        live = [c for c in entry["conversations"]
                if isinstance(c, dict) and c.get("id")]
        new_active = (max(live, key=ChatStore._ts_key)["id"] if live else None)
        if "active_id" in entry and entry["active_id"] == new_active:
            return False
        entry["active_id"] = new_active
        return True

    @staticmethod
    def _migrate_entry(entry):
        if not isinstance(entry, dict):
            return {"conversations": [], "active_id": None}
        messages = entry.get("messages")
        messages = list(messages) if isinstance(messages, list) else []
        session_id = entry.get("session_id")
        if not messages and not session_id:
            return {"conversations": [], "active_id": None}
        first_user = next((m for m in messages
                           if isinstance(m, dict) and m.get("role") == "user"), None)
        title = derive_title(first_user.get("text") if first_user else "")
        first_ts = messages[0].get("ts") if messages and isinstance(messages[0], dict) else None
        last_ts = messages[-1].get("ts") if messages and isinstance(messages[-1], dict) else None
        now = now_iso()
        conv = {"id": new_conversation_id(), "title": title,
                "session_id": session_id, "messages": messages,
                "created_at": first_ts or now, "updated_at": last_ts or now}
        return {"conversations": [conv], "active_id": conv["id"]}

    def _save(self):
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(str(tmp), str(self.path))

    def _entry(self, lesson):
        entry = self.data.get(lesson)
        if not (isinstance(entry, dict) and isinstance(entry.get("conversations"), list)):
            entry = {"conversations": [], "active_id": None}
            self.data[lesson] = entry
        elif "active_id" not in entry:
            entry["active_id"] = None
        return entry

    @staticmethod
    def _find(entry, conv_id):
        for conv in entry["conversations"]:
            if isinstance(conv, dict) and conv.get("id") == conv_id:
                return conv
        return None

    @staticmethod
    def _ts_key(conv):
        """Sort key for newest-updated-first: parse the ISO timestamp so the
        order is chronological regardless of offset/DST (lexicographic string
        compare disagrees across an offset change). Always returns an aware
        datetime so a naive (hand-edited) value can never raise mid-sort."""
        try:
            dt = datetime.fromisoformat(conv.get("updated_at") or "")
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _summary(conv):
        return {"id": conv["id"], "title": conv["title"],
                "session_id": conv.get("session_id"),
                "message_count": len(conv.get("messages") or []),
                "created_at": conv.get("created_at"),
                "updated_at": conv.get("updated_at")}

    @classmethod
    def _summaries(cls, entry):
        """Conversation summaries, newest-updated-first."""
        convs = sorted(entry["conversations"], key=cls._ts_key, reverse=True)
        return [cls._summary(c) for c in convs]

    def get_view(self, lesson, conversation=None):
        """The GET /api/chat base-shape data, or None if `conversation` is given
        but unknown (caller turns that into a 404)."""
        with self.lock:
            entry = self._entry(lesson)
            if conversation is not None:
                selected = self._find(entry, conversation)
                if selected is None:
                    return None
            elif entry["active_id"] is not None:
                selected = self._find(entry, entry["active_id"])
            else:
                selected = None
            return {
                "ok": True, "lesson": lesson, "active_id": entry["active_id"],
                "conversations": self._summaries(entry),
                "messages": list(selected.get("messages") or []) if selected else [],
                "session_id": selected.get("session_id") if selected else None,
                "conversation": selected["id"] if selected else None,
            }

    def new_conversation(self, lesson):
        """Create an empty conversation, make it active, return (id, summaries)."""
        with self.lock:
            entry = self._entry(lesson)
            now = now_iso()
            conv = {"id": new_conversation_id(), "title": "New chat",
                    "session_id": None, "messages": [],
                    "created_at": now, "updated_at": now}
            entry["conversations"].append(conv)
            entry["active_id"] = conv["id"]
            self._save()
            return conv["id"], self._summaries(entry)

    def ensure_active(self, lesson):
        """Return the active conversation id, creating one if none exists."""
        with self.lock:
            entry = self._entry(lesson)
            if entry["active_id"] is not None and self._find(entry, entry["active_id"]):
                return entry["active_id"]
            now = now_iso()
            conv = {"id": new_conversation_id(), "title": "New chat",
                    "session_id": None, "messages": [],
                    "created_at": now, "updated_at": now}
            entry["conversations"].append(conv)
            entry["active_id"] = conv["id"]
            self._save()
            return conv["id"]

    def has_conversation(self, lesson, conv_id):
        with self.lock:
            return self._find(self._entry(lesson), conv_id) is not None

    def switch(self, lesson, conv_id):
        """Set active_id to conv_id. Returns True if it exists, else False."""
        with self.lock:
            entry = self._entry(lesson)
            if self._find(entry, conv_id) is None:
                return False
            entry["active_id"] = conv_id
            self._save()
            return True

    def delete_conversation(self, lesson, conv_id):
        """Remove a conversation. Returns (found, active_id). If it was active,
        active_id becomes the most-recently-updated remaining conversation
        (or None)."""
        with self.lock:
            entry = self._entry(lesson)
            conv = self._find(entry, conv_id)
            if conv is None:
                return False, entry["active_id"]
            entry["conversations"] = [c for c in entry["conversations"]
                                      if c.get("id") != conv_id]
            if entry["active_id"] == conv_id:
                if entry["conversations"]:
                    newest = max(entry["conversations"], key=self._ts_key)
                    entry["active_id"] = newest["id"]
                else:
                    entry["active_id"] = None
            self._save()
            return True, entry["active_id"]

    def append_message(self, lesson, conv_id, role, text):
        """Append a message to a conversation, bumping updated_at. The title is
        set when the FIRST user message lands in a conversation that has had no
        prior user message, so it always reflects the opening question."""
        with self.lock:
            entry = self._entry(lesson)
            conv = self._find(entry, conv_id)
            if conv is None:
                return
            if role == "user" and not any(
                    isinstance(m, dict) and m.get("role") == "user"
                    for m in conv["messages"]):
                conv["title"] = derive_title(text)
            now = now_iso()
            conv["messages"].append({"role": role, "text": text, "ts": now})
            conv["updated_at"] = now
            self._save()

    def finish_turn(self, lesson, conv_id, session_id, text):
        """Write the assistant message + session_id + updated_at to conv_id."""
        with self.lock:
            entry = self._entry(lesson)
            conv = self._find(entry, conv_id)
            if conv is None:
                return
            conv["session_id"] = session_id
            now = now_iso()
            conv["messages"].append({"role": "assistant", "text": text, "ts": now})
            conv["updated_at"] = now
            self._save()

    def reset(self, lesson):
        """Wipe ALL conversations for this lesson."""
        with self.lock:
            self.data[lesson] = {"conversations": [], "active_id": None}
            self._save()


# ---------- backends ----------------------------------------------------------
# A backend is run_turn(lesson_rel, lesson_title, lesson_text, message, session_id)
# -> generator of ("delta", str) then exactly one ("done", {"session_id", "text"});
# may raise ChatBackendError.

def mock_run_turn(lesson_rel, lesson_title, lesson_text, message, session_id):
    sid = session_id or ("mock-" + uuid.uuid4().hex[:12])
    reply = ('You asked: "%s". Mock tutor for "%s" reporting in. '
             "Try `code spans` too." % (message, lesson_title))
    step = max(1, (len(reply) + 3) // 4)
    chunks = [reply[i:i + step] for i in range(0, len(reply), step)]
    for i, chunk in enumerate(chunks):
        if i:
            time.sleep(0.025)
        yield ("delta", chunk)
    yield ("done", {"session_id": sid, "text": reply})


def parse_stream_json_lines(lines):
    """Parse `claude --output-format stream-json` lines (any iterable of str).

    Yields ("delta", text) for text_delta stream events, then ("done", payload)
    on the result event. Unparseable lines and non-text deltas are ignored."""
    init_sid = None
    deltas = []
    fallback = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init":
            init_sid = obj.get("session_id") or init_sid
        elif kind == "stream_event":
            event = obj.get("event") or {}
            if event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        deltas.append(text)
                        yield ("delta", text)
        elif kind == "assistant":
            content = (obj.get("message") or {}).get("content") or []
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            if parts:
                fallback = "".join(parts)
        elif kind == "result":
            sid = obj.get("session_id") or init_sid
            if obj.get("subtype") != "success" or obj.get("is_error"):
                errors = obj.get("errors")
                joined = ("; ".join(str(e) for e in errors)
                          if isinstance(errors, list) and errors else None)
                msg = (obj.get("result") or obj.get("error") or obj.get("message")
                       or joined
                       or "claude turn failed (%s)" % obj.get("subtype"))
                raise ChatBackendError(str(msg))
            if deltas:
                text = "".join(deltas)
            elif obj.get("result") is not None:
                text = obj["result"]
            else:
                text = fallback
            yield ("done", {"session_id": sid, "text": text})
            return


def _kill_quietly(proc):
    # start_new_session=True makes the child a group leader (pgid == pid), so
    # any helpers the CLI spawned die with it.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (AttributeError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _drain(stream, buf):
    try:
        for chunk in stream:
            buf.append(chunk)
    except (OSError, ValueError):
        pass


def _is_stale_resume(err):
    """True when a --resume turn failed because claude no longer knows the id."""
    msg = str(err).lower()
    return "no conversation found" in msg or "error_during_execution" in msg


# Session ids are claude-minted (UUID-shaped). chats.json is user-editable, so
# guard the value before it reaches `--resume`: it must start with an
# alphanumeric (never a dash, so it can't be parsed as a flag) and contain only
# id-safe characters. A value that fails just starts a fresh session.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _valid_session_id(session_id):
    return isinstance(session_id, str) and bool(_SESSION_ID_RE.match(session_id))


def make_claude_backend(claude_bin, lessons_dir):
    # Confine the tutor's Read/Grep/Glob to the lessons/ subdir (rendered HTML
    # pages) so it can consult sibling lessons but NOT chats.json, which lives
    # one level up in the library root.
    tool_root = Path(lessons_dir) / "lessons"
    tool_root.mkdir(parents=True, exist_ok=True)

    def attempt_turn(lesson_title, lesson_text, message, session_id):
        argv = [claude_bin, "-p",  # the message arrives on stdin, never argv
                "--output-format", "stream-json", "--verbose",
                "--include-partial-messages",
                "--append-system-prompt", build_system_prompt(lesson_title, lesson_text),
                "--allowedTools", "Read", "Grep", "Glob",
                "--strict-mcp-config",
                "--settings", '{"disableAllHooks": true}']
        if _valid_session_id(session_id):
            argv += ["--resume", session_id]
        env = dict(os.environ)
        for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env.pop(key, None)  # keep the nested run from seeing this session
        try:
            proc = subprocess.Popen(argv, cwd=str(tool_root), env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace",
                                    start_new_session=True)
        except FileNotFoundError:
            raise ChatBackendError(
                "claude CLI not found — is Claude Code installed and on PATH?")
        try:
            proc.stdin.write(message)
            proc.stdin.close()
        except OSError:
            pass  # child died instantly; the exit-code path reports it
        stderr_buf = []
        drain = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
        drain.start()
        timed_out = []
        killer = threading.Timer(CLAUDE_TURN_TIMEOUT,
                                 lambda: (timed_out.append(True), _kill_quietly(proc)))
        killer.start()
        done = None
        error = None
        try:
            try:
                for kind, payload in parse_stream_json_lines(proc.stdout):
                    if kind == "done":
                        done = payload  # held until the exit code is known
                    else:
                        yield (kind, payload)
            except GeneratorExit:  # client went away mid-stream
                _kill_quietly(proc)
                proc.wait()
                raise
            except ChatBackendError as err:  # tail appended after the drain join
                error = err
                _kill_quietly(proc)
            if error is None:
                try:
                    proc.stdout.read()  # let the child flush anything after result
                except (OSError, ValueError):
                    pass
            proc.wait()
        finally:
            killer.cancel()
        drain.join(timeout=5)
        tail = "".join(stderr_buf)[-500:].strip()
        if timed_out:
            raise ChatBackendError("claude timed out after %ds" % CLAUDE_TURN_TIMEOUT)
        if error is not None:
            raise ChatBackendError("%s%s" % (error, ": " + tail if tail else ""))
        if proc.returncode != 0:
            raise ChatBackendError("claude exited %s%s"
                                   % (proc.returncode, ": " + tail if tail else ""))
        if done is None:
            raise ChatBackendError("claude stream ended without a result event%s"
                                   % (": " + tail if tail else ""))
        if not done.get("session_id"):
            done["session_id"] = session_id
        yield ("done", done)

    def run_turn(lesson_rel, lesson_title, lesson_text, message, session_id):
        emitted = False
        first = attempt_turn(lesson_title, lesson_text, message, session_id)
        try:
            for kind, payload in first:
                if kind == "delta":
                    emitted = True
                yield (kind, payload)
            return
        except ChatBackendError as err:
            # Stale --resume self-heal: claude no longer knows the stored
            # session id. Drop it and retry ONCE without --resume — but only
            # if the reader has not seen any delta yet.
            if not session_id or emitted or not _is_stale_resume(err):
                raise
        finally:
            first.close()
        retry = attempt_turn(lesson_title, lesson_text, message, None)
        try:
            for kind, payload in retry:
                yield (kind, payload)
        finally:
            retry.close()
    return run_turn


# ---------- recast (generate an alternate-tone rendition) ---------------------

def _read_ledger(lessons_dir):
    """Tolerant ledger read for the server: never raises, never exits (unlike
    render_lesson.load_ledger, which calls sys.exit on bad JSON)."""
    p = Path(lessons_dir) / "index.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def rendition_group(lessons_dir, lesson):
    """The concept group containing `lesson` (a ledger 'file' value), or None.

    Returns {"primary": <first rendition record>, "renditions": [records…]}."""
    ledger = _read_ledger(lessons_dir)
    rec = next((r for r in ledger if r.get("file") == lesson), None)
    if rec is None:
        return None
    ck = rec.get("concept_key")
    rends = [r for r in ledger if r.get("concept_key") == ck] if ck else [rec]
    return {"primary": rends[0] if rends else rec, "renditions": rends}


def extract_article_html(src):
    """Inner article HTML (sections + self-check) of a rendered lesson page, for
    feeding a recast. Falls back to plain text if the canonical boundaries are
    missing."""
    try:
        dek = src.index('<p class="dek">')
        start = src.index("</p>", dek) + len("</p>")
        end = src.index("<hr", start)
        article = src[start:end].strip()
        if article:
            return article[:ARTICLE_HTML_CAP]
    except ValueError:
        pass
    return extract_lesson_text(src)[:ARTICLE_HTML_CAP]


RECAST_INSTRUCTIONS = (
    "You re-render an existing Daily Lesson in a different LECTURE MODE — a "
    "different tone and depth for the SAME concept and the SAME facts. This is a "
    "re-voicing, not a new lesson: do not change the concept, invent session "
    "events, or alter technical facts. Output ONLY a single JSON object (no prose, "
    "no markdown fence) with exactly these string keys: "
    '{"dek": "...", "one_liner": "...", "body_html": "..."}. '
    "body_html is the inner HTML of the article: the six numbered sections "
    '(<h2><span class="h2n">01</span> …> through 06) then the .checks self-check, '
    "using ONLY the canonical components (<figure class=\"code\"> with escaped "
    "code at column 0, <details class=\"pit\">, <blockquote>, .checks cards). No "
    "<head>, CSS, <script>, <hr>, or footer. dek is the italic subtitle (small "
    "inline HTML like <code> allowed); one_liner is plain text. Obey the target "
    "mode's tone/depth/length and the two floors in the reference below: never "
    "make the concept obscure, and use second person ('you') ONLY for what the "
    "USER genuinely did or decided — narrate the agent's/tooling's work in the "
    "third person. If the source lesson credits 'you' with something you cannot "
    "confirm the user did, switch it to the impersonal/agent voice."
)


def build_recast_system_prompt(modes_doc, target_mode, concept):
    return (
        "%s\n\n=== TARGET MODE: %s ===\n"
        "Lesson title: %s\nConcept key: %s\nSource day: %s\nTags: %s\n\n"
        "=== references/lesson-modes.md (the mode contract) ===\n%s\n"
        "=== END reference ===" % (
            RECAST_INSTRUCTIONS, target_mode,
            concept.get("title", ""), concept.get("concept_key", ""),
            concept.get("source_day", ""), ", ".join(concept.get("tags") or []),
            modes_doc))


def mock_recast_generate(concept, target_mode, article_html):
    """Deterministic stand-in for the claude backend (tests + offline demos)."""
    label = render_lesson.mode_label(target_mode)
    title = concept.get("title", "this concept")
    body = (
        '<h2><span class="h2n">01</span> What it is</h2>'
        '<p class="lead">A %s rendition of %s.</p>'
        '<h2><span class="h2n">02</span> Why it mattered today</h2>'
        '<p>In the session the agent did the work; this rendition reports it '
        'honestly.</p>'
        '<h2><span class="h2n">03</span> The mental model</h2><p>The picture.</p>'
        '<h2><span class="h2n">04</span> A worked example</h2>'
        '<figure class="code"><figcaption><span>example.py</span>'
        '<button class="copy" type="button">Copy</button></figcaption>'
        '<pre><code class="language-python">x = 1</code></pre></figure>'
        '<h2><span class="h2n">05</span> Pitfalls</h2>'
        '<details class="pit"><summary><span class="chev">&rsaquo;</span>'
        '<span class="pl">01</span><span>A trap</span></summary>'
        '<div class="body">Watch for it.</div></details>'
        '<h2><span class="h2n">06</span> Go deeper</h2><p>Read more.</p>'
        '<h3>Self-check</h3>'
        '<div class="checks"><div class="card"><div class="q">'
        '<span class="qn">Q1</span><span>Which tone is this?</span></div>'
        '<div class="a">%s.</div><div class="reveal">&#9656; reveal</div>'
        '</div></div>' % (label, html.escape(title), label))
    return {"dek": "A <em>%s</em> rendition." % label,
            "one_liner": "%s — in %s mode." % (title, label),
            "body_html": body}


def _extract_json(text):
    """Parse a JSON object out of a model reply (tolerant of fences/prose)."""
    t = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except ValueError:
            pass
    raise ChatBackendError("could not parse the generated lesson as JSON")


def _claude_recast_generate(claude_bin, tool_root, system_prompt, message):
    argv = [claude_bin, "-p",
            "--output-format", "stream-json", "--verbose",
            "--append-system-prompt", system_prompt,
            "--strict-mcp-config",
            "--settings", '{"disableAllHooks": true}']
    env = dict(os.environ)
    for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(key, None)
    try:
        proc = subprocess.Popen(argv, cwd=str(tool_root), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace",
                                start_new_session=True)
    except FileNotFoundError:
        raise ChatBackendError(
            "claude CLI not found — is Claude Code installed and on PATH?")
    try:
        proc.stdin.write(message)
        proc.stdin.close()
    except OSError:
        pass
    stderr_buf = []
    drain = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
    drain.start()
    timed_out = []
    killer = threading.Timer(RECAST_TIMEOUT,
                             lambda: (timed_out.append(True), _kill_quietly(proc)))
    killer.start()
    done = None
    error = None
    try:
        try:
            for kind, payload in parse_stream_json_lines(proc.stdout):
                if kind == "done":
                    done = payload
        except ChatBackendError as err:
            error = err
            _kill_quietly(proc)
        proc.wait()
    finally:
        killer.cancel()
    drain.join(timeout=5)
    tail = "".join(stderr_buf)[-500:].strip()
    if timed_out:
        raise ChatBackendError("claude timed out after %ds" % RECAST_TIMEOUT)
    if error is not None:
        raise ChatBackendError("%s%s" % (error, ": " + tail if tail else ""))
    if proc.returncode != 0:
        raise ChatBackendError("claude exited %s%s"
                               % (proc.returncode, ": " + tail if tail else ""))
    if done is None or not done.get("text"):
        raise ChatBackendError("claude produced no output%s"
                               % (": " + tail if tail else ""))
    return done["text"]


def make_recast(backend, claude_bin, lessons_dir, references_dir):
    """Return recast_generate(concept, target_mode, article_html) -> dict with
    keys dek/one_liner/body_html. Raises ChatBackendError on failure."""
    tool_root = Path(lessons_dir) / "lessons"

    if backend == "mock":
        def recast_generate(concept, target_mode, article_html):
            return mock_recast_generate(concept, target_mode, article_html)
        return recast_generate

    def recast_generate(concept, target_mode, article_html):
        try:
            modes_doc = (references_dir / "lesson-modes.md").read_text(encoding="utf-8")
        except OSError:
            modes_doc = "(mode reference unavailable; follow the target mode name.)"
        prompt = build_recast_system_prompt(modes_doc, target_mode, concept)
        text = _claude_recast_generate(claude_bin, tool_root, prompt, article_html)
        data = _extract_json(text)
        if not isinstance(data, dict) or not isinstance(data.get("body_html"), str):
            raise ChatBackendError("the generated lesson had no usable body")
        return data
    return recast_generate


class RecastRenderError(Exception):
    """render_lesson.py --variant failed; str(err) is safe to surface."""


def render_variant(render_script, lessons_dir, assets_dir, concept, mode, gen):
    """Write meta+body for an alternate-tone rendition and run the canonical
    renderer with --variant. Returns its JSON summary. Raises RecastRenderError."""
    meta = {
        "slug": concept.get("slug"),
        "concept_key": concept.get("concept_key"),
        "title": concept.get("title"),
        "dek": (gen.get("dek") or concept.get("title") or "").strip() or concept.get("title"),
        "one_liner": (gen.get("one_liner") or concept.get("one_liner") or "").strip()
                     or concept.get("one_liner"),
        "source_day": concept.get("source_day"),
        "taught_at": now_iso(),
        "tags": concept.get("tags") or [],
        "mode": mode,
    }
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "meta.json"
        bp = Path(td) / "body.html"
        mp.write_text(json.dumps(meta), encoding="utf-8")
        bp.write_text(gen.get("body_html") or "", encoding="utf-8")
        argv = [sys.executable, str(render_script), "--variant",
                "--meta", str(mp), "--body", str(bp),
                "--lessons-dir", str(lessons_dir), "--assets-dir", str(assets_dir)]
        proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or ("renderer exited %d" % proc.returncode)
        raise RecastRenderError(msg[:300])
    try:
        return json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RecastRenderError("renderer produced no JSON summary")


# ---------- http --------------------------------------------------------------

def _turn_lock(server, lesson):
    with server.turn_locks_guard:
        return server.turn_locks.setdefault(lesson, threading.Lock())


def _recast_lock(server, key):
    with server.recast_locks_guard:
        return server.recast_locks.setdefault(key, threading.Lock())


class ChatHandler(BaseHTTPRequestHandler):
    server_version = APP_NAME + "/" + str(API_VERSION)
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # one startup line is enough
        pass

    # -- helpers --

    def _send_json(self, code, obj, cors_origin=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _health_acao(self):
        """CORS value for /api/health: grant read access only to the legitimate
        cross-origin caller — a `file://` page (Origin: null) discovering the
        server. A real website's Origin gets no header, so it can detect the
        server with a no-cors probe but cannot read the version/backend body."""
        origin = self.headers.get("Origin")
        return "null" if origin in (None, "null") else None

    def _host_ok(self):
        """DNS-rebinding pin: the Host header must name this machine."""
        host = self.headers.get("Host")
        if not host:
            return False
        host = host.strip().lower()
        if host.startswith("["):        # [::1] or [::1]:port
            bracket, _, rest = host.partition("]")
            if rest and not rest.startswith(":"):
                return False
            host = bracket + "]"
        elif host.count(":") == 1:      # host:port
            host = host.split(":", 1)[0]
        return host in ALLOWED_HOSTS

    def _reject_host(self):
        self.close_connection = True
        self._send_json(403, {"ok": False, "error": "forbidden host"})

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin == "http://" + (self.headers.get("Host") or "")

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return None
        if length <= 0 or length > 1_000_000:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _resolve_inside_root(self, rel):
        root = self.server.lessons_root
        try:
            real = (root / rel).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if real != root and not str(real).startswith(str(root) + os.sep):
            return None
        return real if real.is_file() else None

    def _lesson_path(self, lesson):
        if not isinstance(lesson, str) or not lesson:
            return None
        return self._resolve_inside_root(lesson)

    def _sse(self, event, data):
        frame = "event: %s\ndata: %s\n\n" % (event, json.dumps(data))
        self.wfile.write(frame.encode("utf-8"))
        self.wfile.flush()

    def _sse_quiet(self, event, data):
        try:
            self._sse(event, data)
        except OSError:
            pass

    # -- routes --

    def do_OPTIONS(self):
        if not self._host_ok():
            return self._reject_host()
        if urlsplit(self.path).path == "/api/health":
            acao = self._health_acao()
            self.send_response(204)
            if acao is not None:
                self.send_header("Access-Control-Allow-Origin", acao)
                self.send_header("Access-Control-Allow-Methods", "GET")
            self.end_headers()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_GET(self):
        if not self._host_ok():
            return self._reject_host()
        parts = urlsplit(self.path)
        if parts.path == "/api/health":
            self._send_json(200, {"ok": True, "app": APP_NAME,
                                  "version": API_VERSION,
                                  "backend": self.server.backend_name},
                            cors_origin=self._health_acao())
        elif parts.path.startswith("/api/"):
            if not self._origin_ok():
                self._send_json(403, {"ok": False, "error": "cross-origin"})
            elif parts.path == "/api/chat":
                self._handle_chat_get(parts.query)
            elif parts.path == "/api/renditions":
                self._handle_renditions_get(parts.query)
            else:
                self._send_json(404, {"ok": False, "error": "not found"})
        else:
            self._serve_static(parts.path)

    def do_POST(self):
        if not self._host_ok():
            return self._reject_host()
        path = urlsplit(self.path).path
        if not self._origin_ok():
            self.close_connection = True  # request body may be unconsumed
            self._send_json(403, {"ok": False, "error": "cross-origin"})
        elif path == "/api/chat":
            self._handle_chat_post()
        elif path == "/api/chat/new":
            self._handle_new()
        elif path == "/api/chat/switch":
            self._handle_switch()
        elif path == "/api/chat/delete":
            self._handle_delete()
        elif path == "/api/chat/reset":
            self._handle_reset()
        elif path == "/api/recast":
            self._handle_recast()
        else:
            self.close_connection = True  # request body may be unconsumed
            self._send_json(404, {"ok": False, "error": "not found"})

    def _handle_chat_get(self, query):
        params = parse_qs(query)
        lesson = (params.get("lesson") or [None])[0]
        conversation = (params.get("conversation") or [None])[0]
        if not lesson:
            return self._send_json(400, {"ok": False, "error": "bad request"})
        if self._lesson_path(lesson) is None:
            return self._send_json(404, {"ok": False, "error": "unknown lesson"})
        view = self.server.store.get_view(lesson, conversation)
        if view is None:  # conversation= named an id this lesson doesn't have
            return self._send_json(404, {"ok": False, "error": "unknown conversation"})
        self._send_json(200, view)

    def _handle_chat_post(self):
        body = self._read_json_body()
        if not isinstance(body, dict):
            self.close_connection = True  # request body may be unconsumed
            return self._send_json(400, {"ok": False, "error": "bad request"})
        lesson = body.get("lesson")
        message = body.get("message")
        conversation = body.get("conversation", None)
        if (not isinstance(lesson, str) or not isinstance(message, str)
                or not message.strip()
                or (conversation is not None and not isinstance(conversation, str))):
            return self._send_json(400, {"ok": False, "error": "bad request"})
        lesson_path = self._lesson_path(lesson)
        if lesson_path is None:
            return self._send_json(404, {"ok": False, "error": "unknown lesson"})
        # Resolve the target conversation up front (before streaming): an explicit
        # unknown id is a 404 here, never a partial stream.
        if conversation is not None:
            if not self.server.store.has_conversation(lesson, conversation):
                return self._send_json(404, {"ok": False, "error": "unknown conversation"})
        lock = _turn_lock(self.server, lesson)
        if not lock.acquire(False):
            return self._send_json(409, {"ok": False, "error": "busy"})
        try:
            # Bind the turn to a single conversation id and operate on it BY ID
            # for the whole turn, so a concurrent /new or /switch can move
            # active_id without ever misrouting this in-flight turn.
            conv_id = conversation or self.server.store.ensure_active(lesson)
            # Re-check existence INSIDE the lock: a /delete or /reset may have
            # won the race between the pre-lock check above and acquiring this
            # lock (no turn was in flight yet, so its 409 guard didn't fire).
            # Bail with a clean 404 before any SSE byte rather than streaming a
            # reply into a conversation that no longer exists (silent loss).
            if conversation is not None and not self.server.store.has_conversation(
                    lesson, conv_id):
                return self._send_json(404, {"ok": False, "error": "unknown conversation"})
            src = lesson_path.read_text(encoding="utf-8", errors="replace")
            title = extract_lesson_title(src)
            text = extract_lesson_text(src)
            view = self.server.store.get_view(lesson, conv_id)
            session_id = view["session_id"] if view else None
            # user message is persisted up front so a failed turn is retryable
            # (and it sets the conversation title on the first user message)
            self.server.store.append_message(lesson, conv_id, "user", message)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            gen = self.server.run_turn(lesson, title, text, message, session_id)
            try:
                for kind, payload in gen:
                    if kind == "delta":
                        self._sse("delta", {"text": payload})
                    elif kind == "done":
                        self.server.store.finish_turn(
                            lesson, conv_id, payload.get("session_id"),
                            payload.get("text", ""))
                        out = dict(payload)
                        out["conversation"] = conv_id
                        self._sse("done", out)
            except ChatBackendError as err:
                self._sse_quiet("error", {"message": str(err)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:  # never leave the reader without a frame
                sys.stderr.write("chat_server: turn crashed: %r\n" % (err,))
                self._sse_quiet("error", {"message": "internal error: %s" % err})
            finally:
                gen.close()
        finally:
            lock.release()

    def _post_lesson(self):
        """Read a POST body whose only required field is `lesson`; resolve it.

        Returns (lesson, error_handled). On any failure it has already sent the
        right 400/404 response and error_handled is True."""
        body = self._read_json_body()
        if not isinstance(body, dict):
            self.close_connection = True  # request body may be unconsumed
            self._send_json(400, {"ok": False, "error": "bad request"})
            return None, True
        lesson = body.get("lesson")
        if not isinstance(lesson, str) or not lesson:
            self._send_json(400, {"ok": False, "error": "bad request"})
            return None, True
        if self._lesson_path(lesson) is None:
            self._send_json(404, {"ok": False, "error": "unknown lesson"})
            return None, True
        return (body, lesson), False

    def _handle_new(self):
        parsed, handled = self._post_lesson()
        if handled:
            return
        _, lesson = parsed
        new_id, summaries = self.server.store.new_conversation(lesson)
        self._send_json(200, {"ok": True, "id": new_id, "active_id": new_id,
                              "conversations": summaries})

    def _handle_switch(self):
        parsed, handled = self._post_lesson()
        if handled:
            return
        body, lesson = parsed
        conversation = body.get("conversation")
        if not isinstance(conversation, str) or not conversation:
            return self._send_json(400, {"ok": False, "error": "bad request"})
        if not self.server.store.switch(lesson, conversation):
            return self._send_json(404, {"ok": False, "error": "unknown conversation"})
        view = self.server.store.get_view(lesson, conversation)
        self._send_json(200, {"ok": True, "active_id": conversation,
                              "conversation": conversation,
                              "messages": view["messages"],
                              "session_id": view["session_id"]})

    def _handle_delete(self):
        parsed, handled = self._post_lesson()
        if handled:
            return
        body, lesson = parsed
        conversation = body.get("conversation")
        if not isinstance(conversation, str) or not conversation:
            return self._send_json(400, {"ok": False, "error": "bad request"})
        if not self.server.store.has_conversation(lesson, conversation):
            return self._send_json(404, {"ok": False, "error": "unknown conversation"})
        lock = _turn_lock(self.server, lesson)
        if not lock.acquire(False):  # never delete a streaming conversation
            return self._send_json(409, {"ok": False, "error": "busy"})
        try:
            found, active_id = self.server.store.delete_conversation(lesson, conversation)
            entry_view = self.server.store.get_view(lesson)
        finally:
            lock.release()
        if not found:  # raced away between the check and the lock
            return self._send_json(404, {"ok": False, "error": "unknown conversation"})
        self._send_json(200, {"ok": True, "active_id": active_id,
                              "conversations": entry_view["conversations"]})

    def _handle_reset(self):
        parsed, handled = self._post_lesson()
        if handled:
            return
        _, lesson = parsed
        lock = _turn_lock(self.server, lesson)
        if not lock.acquire(False):  # never reset under a turn in flight
            return self._send_json(409, {"ok": False, "error": "busy"})
        try:
            self.server.store.reset(lesson)
        finally:
            lock.release()
        self._send_json(200, {"ok": True})

    def _handle_renditions_get(self, query):
        """The lesson's concept group: existing tones (to switch to) + the modes
        not yet generated (to offer a Generate button)."""
        params = parse_qs(query)
        lesson = (params.get("lesson") or [None])[0]
        if not lesson:
            return self._send_json(400, {"ok": False, "error": "bad request"})
        if self._lesson_path(lesson) is None:
            return self._send_json(404, {"ok": False, "error": "unknown lesson"})
        order = list(render_lesson.MODE_LABELS.keys())
        group = rendition_group(self.server.lessons_dir, lesson)
        if group is None:
            # served page isn't in the ledger: nothing to switch or generate
            return self._send_json(200, {"ok": True, "lesson": lesson,
                                         "concept_key": None, "current_mode": None,
                                         "renditions": [], "available": []})
        rends, present = [], set()
        for r in group["renditions"]:
            m = r.get("mode") or None
            present.add(m)
            f = r.get("file")
            rends.append({"mode": m, "label": render_lesson.mode_label(m),
                          "file": f, "url": "/" + str(f),
                          "current": f == lesson})
        available = [{"mode": m, "label": render_lesson.MODE_LABELS[m]}
                     for m in order if m not in present]
        current = next((x["mode"] for x in rends if x["current"]), None)
        self._send_json(200, {"ok": True, "lesson": lesson,
                              "concept_key": group["primary"].get("concept_key"),
                              "current_mode": current,
                              "renditions": rends, "available": available})

    def _handle_recast(self):
        """Generate an alternate-tone rendition of this lesson's concept and
        return its URL. Idempotent: a tone that already exists is returned as-is
        — re-checked INSIDE the per-concept lock, so two concurrent requests for
        the same tone can't both slip past a stale check into a doomed second
        render."""
        parsed, handled = self._post_lesson()
        if handled:
            return
        body, lesson = parsed
        mode = body.get("mode")
        if mode not in render_lesson.MODE_LABELS:
            return self._send_json(400, {"ok": False, "error": "unknown mode"})

        def existing_in(grp):
            return next((r for r in grp["renditions"]
                         if (r.get("mode") or None) == mode), None)

        def already(rec):
            f = rec.get("file")
            return self._send_json(200, {"ok": True, "already": True, "mode": mode,
                                         "label": render_lesson.mode_label(mode),
                                         "file": f, "url": "/" + str(f)})

        group = rendition_group(self.server.lessons_dir, lesson)
        if group is None:
            return self._send_json(404, {"ok": False, "error": "lesson not in the library ledger"})
        hit = existing_in(group)  # fast path: tone already present (no lock needed)
        if hit:
            return already(hit)
        lock = _recast_lock(self.server, group["primary"].get("concept_key") or lesson)
        if not lock.acquire(False):  # a recast of this concept is already running
            return self._send_json(409, {"ok": False, "error": "busy"})
        try:
            # Re-read + re-check under the lock: a concurrent recast of this same
            # tone may have completed between the fast-path check and here.
            group = rendition_group(self.server.lessons_dir, lesson)
            if group is None:
                return self._send_json(404, {"ok": False, "error": "lesson not in the library ledger"})
            concept = group["primary"]
            hit = existing_in(group)
            if hit:
                return already(hit)
            primary_path = self._lesson_path(concept.get("file"))
            if primary_path is None:
                return self._send_json(404, {"ok": False, "error": "primary rendition missing"})
            article = extract_article_html(
                primary_path.read_text(encoding="utf-8", errors="replace"))
            try:
                gen = self.server.recast(concept, mode, article)
            except ChatBackendError as err:
                return self._send_json(502, {"ok": False, "error": str(err)})
            if not isinstance(gen, dict) or "<h2" not in (gen.get("body_html") or ""):
                return self._send_json(502, {"ok": False,
                                             "error": "generation returned no usable lesson body"})
            try:
                # one global lock around the ledger-mutating render step so two
                # concurrent recasts (different concepts) can't clobber index.json
                with self.server.render_lock:
                    result = render_variant(self.server.render_script,
                                            self.server.lessons_dir,
                                            self.server.assets_dir, concept, mode, gen)
            except RecastRenderError as err:
                return self._send_json(500, {"ok": False, "error": str(err)})
            f = result.get("file")
            self._send_json(200, {"ok": True, "already": False, "mode": mode,
                                  "label": render_lesson.mode_label(mode),
                                  "file": f, "url": "/" + str(f)})
        finally:
            lock.release()

    def _serve_static(self, path):
        if path in ("", "/", "/index.html"):
            rel = "index.html"
        else:
            rel = unquote(path).lstrip("/")
        real = self._resolve_inside_root(rel)
        if real is None or real == self.server.chats_path:
            # transcripts are reachable only through /api/chat
            return self._send_json(404, {"ok": False, "error": "not found"})
        raw = real.read_bytes()
        if rel.startswith("lessons/") and rel.endswith(".html"):
            raw = inject_widget(raw, self.server.widget_block, WIDGET_START, WIDGET_END)
            raw = inject_widget(raw, self.server.modes_block, MODES_START, MODES_END)
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(real.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def build_server(port, lessons_dir, backend, claude_bin="claude", assets_dir=None):
    lessons_dir = Path(lessons_dir).expanduser()
    lessons_dir.mkdir(parents=True, exist_ok=True)
    (lessons_dir / "lessons").mkdir(parents=True, exist_ok=True)  # the tutor's tool root
    if assets_dir is None:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
    assets_dir = Path(assets_dir).expanduser()
    if backend == "mock":
        run_turn = mock_run_turn
    else:
        run_turn = make_claude_backend(claude_bin, lessons_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), ChatHandler)
    server.daemon_threads = True
    server.lessons_dir = lessons_dir
    server.lessons_root = lessons_dir.resolve()
    # resolve() so the static-serving block compares resolved-vs-resolved even if
    # chats.json (or a path component) is ever a symlink.
    server.chats_path = (server.lessons_root / "chats.json").resolve()
    server.backend_name = backend
    server.run_turn = run_turn
    server.store = ChatStore(lessons_dir)
    server.assets_dir = assets_dir
    server.references_dir = assets_dir.parent / "references"
    server.render_script = _SCRIPTS_DIR / "render_lesson.py"
    server.widget_block = load_widget_block(assets_dir, WIDGET_START, WIDGET_END)
    server.modes_block = load_widget_block(assets_dir, MODES_START, MODES_END)
    server.recast = make_recast(backend, claude_bin, lessons_dir, server.references_dir)
    server.turn_locks = {}
    server.turn_locks_guard = threading.Lock()
    server.recast_locks = {}
    server.recast_locks_guard = threading.Lock()
    server.render_lock = threading.Lock()  # serialize ledger-mutating renders
    return server


def main():
    ap = argparse.ArgumentParser(
        description="Serve the lesson library + a local chat API on 127.0.0.1.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="port to bind (default: %d)" % DEFAULT_PORT)
    ap.add_argument("--lessons-dir", default="~/.claude/daily-lessons",
                    help="lesson library dir (default: ~/.claude/daily-lessons)")
    ap.add_argument("--backend", choices=["claude", "mock"], default=None,
                    help="chat backend (default: $DAILY_LESSON_CHAT_BACKEND or claude)")
    ap.add_argument("--claude-bin", default="claude",
                    help="claude CLI binary (default: claude)")
    ap.add_argument("--assets-dir", default=None,
                    help="canonical templates dir (default: ../assets next to this script)")
    ap.add_argument("--open", action="store_true",
                    help="open the library in a browser at startup")
    args = ap.parse_args()

    backend = args.backend or os.environ.get("DAILY_LESSON_CHAT_BACKEND") or "claude"
    if backend not in ("claude", "mock"):
        die("invalid backend %r (want claude or mock)" % backend, 2)

    server = build_server(args.port, args.lessons_dir, backend,
                          claude_bin=args.claude_bin, assets_dir=args.assets_dir)
    url = "http://127.0.0.1:%d" % server.server_address[1]
    print("daily-lesson chat server · %s · backend=%s" % (url, backend), flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
