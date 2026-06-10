# Lesson Chat — design

**Date:** 2026-06-10 · **Branch:** `feat/lesson-chat`

## Goal

When viewing a Daily Lesson, the reader can open a chat area, ask questions
about the lesson, and get contextual answers. The chat is powered by the local
`claude` CLI in headless mode, so it uses exactly the same auth, subscription,
and model resources as any other Claude Code session — no separate API key, and
nothing leaves the machine beyond what a normal Claude Code session sends.
Every lesson page gets an option to **create** a chat for its topic or
**continue** the one it already has.

## Constraints discovered in the repo

- Lessons are self-contained HTML files in `~/.claude/daily-lessons/lessons/`,
  normally opened via `file://`. The page chrome is **frozen canon** in
  `assets/lesson-shell.html`; the sanctioned way to change the design is to edit
  the shells (README: "Want a different look? Edit the `assets/` shells").
- The plugin's runtime requirements are deliberately tiny: `python3` ≥ 3.8 and
  `jq`. The chat feature must not add runtime dependencies.
- The body contract in `references/lesson-format.md` (six sections +
  self-check) must stay untouched — the widget lives in the *shell*, not the
  body, so `render_lesson.py`'s token replacement and word-count logic are
  unaffected.

## Architecture

Three pieces, one new moving part:

```
┌────────────────────────────┐   fetch /api/chat (SSE)   ┌──────────────────────┐
│ lesson page (frozen shell) │ ────────────────────────▶ │ chat_server.py       │
│  + inline chat widget      │ ◀──────────────────────── │ stdlib-only, local   │
└────────────────────────────┘      streamed deltas      │ 127.0.0.1:8787       │
                                                         └─────────┬────────────┘
                                                                   │ spawn per message
                                                                   ▼
                                              claude -p --output-format stream-json
                                                --include-partial-messages
                                                --resume <session_id>
                                                --append-system-prompt <lesson context>
```

### 1. `scripts/chat_server.py` — the local bridge (new)

Python stdlib only (`http.server.ThreadingHTTPServer`, `subprocess`, `json`).
Binds `127.0.0.1` only. Serves the lessons library over HTTP *and* the chat
API, so chat traffic is same-origin.

Endpoints:

| Route | Method | Purpose | Cross-origin policy |
|---|---|---|---|
| `/`, `/index.html`, `/lessons/*.html` | GET | serve the library; legacy lesson pages get the widget injected at serve time | n/a |
| `/api/health` | GET | `{ok, app, backend, version}` — lets `file://` pages discover a running server | `Access-Control-Allow-Origin: *` (read-only, no secrets) |
| `/api/chat?lesson=lessons/<f>.html` | GET | stored transcript + session metadata for that lesson | same-origin only |
| `/api/chat` | POST `{lesson, message}` | run one turn; respond as SSE: `delta` events (streamed text), then `done` | same-origin only |
| `/api/chat/reset` | POST `{lesson}` | start a fresh chat (drop session id + transcript) | same-origin only |

**Same-origin enforcement:** mutating/reading chat endpoints reject any request
whose `Origin` header is present and ≠ the server's own origin (curl/no-Origin
is allowed). POST bodies must be `application/json`, which forces a CORS
preflight from browsers — and the preflight is only approved for `/api/health`.
This blocks drive-by requests from random websites *and* from `file://`/null
origins, which are indistinguishable from hostile sandboxed iframes.

**Claude invocation** (per message, one-shot process — no long-lived child):

```
claude -p <message>
  --output-format stream-json --verbose --include-partial-messages
  --append-system-prompt <tutor role + full lesson text>
  [--resume <session_id>]                # continue = resume
  --allowedTools Read Grep Glob          # can read sibling lessons; nothing else
  --strict-mcp-config                    # no MCP servers → fast startup
```

- cwd = the lessons dir; `CLAUDECODE`/`CLAUDE_CODE_*` env stripped so the
  nested run behaves like a fresh headless session.
- The lesson's text (HTML → plain text, server-side) rides in
  `--append-system-prompt` on **every** turn, so answers stay grounded even on
  resumed sessions.
- Parsed events: `system/init` → capture `session_id`; `stream_event`
  `text_delta` → SSE `delta`; `result` → SSE `done` (with fallback to the full
  `assistant` message if no partials arrived).
- One in-flight turn per lesson (per-lesson lock); a second send while busy
  gets a 409.

**Persistence:** `~/.claude/daily-lessons/chats.json` —
`{"lessons/<file>.html": {"session_id", "messages": [{role, text, ts}]}}`.
The transcript is what the widget restores on page load; the `session_id` is
what makes "continue" real (full model-side context via `--resume`).

**Backends:** `--backend claude` (default) or `--backend mock` (env
`DAILY_LESSON_CHAT_BACKEND=mock`) — a deterministic streaming responder used by
unit + Playwright tests, so tests are fast and burn no tokens.

### 2. Chat widget — inline in `assets/lesson-shell.html` (shell edit)

A self-contained `<style>+<script>` block between literal markers
`<!-- daily-lesson-chat:v1 -->` … `<!-- /daily-lesson-chat:v1 -->`, placed
before `</body>`. No tokens, no external files: the widget reads the lesson
number/title from the rendered DOM and the lesson file from
`location.pathname`, so the renderer contract is unchanged and pages stay
self-contained.

UX (matches the black-and-white Fraunces/JetBrains Mono canon):

- A fixed bottom-right pill button — `Ask about this lesson` — monochrome,
  JetBrains Mono uppercase, subtle hover lift. Shows `· continue` when a saved
  chat exists for this lesson.
- Clicking slides in a right-hand drawer (~400px; full-width on mobile):
  header (`Lesson chat · #N`), scrollable transcript, textarea + send.
  Assistant turns render minimal markdown (escape-first; fenced code with copy
  button, inline code, bold/em, lists) in the lesson's typography. A thin
  "thinking" shimmer shows while waiting for the first delta; text streams in
  live. `Esc` or ✕ closes; state survives reopen.
- **New chat** button in the drawer header → `/api/chat/reset` + clears the
  transcript (confirm if a chat exists).
- **Serving-mode awareness:**
  - Page served by `chat_server.py` (http) → fully live.
  - Page opened via `file://` → the widget probes `http://127.0.0.1:8787/api/health`.
    Server up → the button becomes "open in chat server": one click navigates
    to the same lesson on the server origin (with `?chat=1` to auto-open the
    drawer). Server down → the drawer explains how to start it (`/lesson-chat`
    inside Claude Code, or the `python3 …/chat_server.py` one-liner) with a
    copy button.

**Legacy pages** (rendered before this feature): the server injects the same
marker-delimited block — extracted at startup from its own
`assets/lesson-shell.html` — before `</body>` when serving any lesson page
that lacks the marker. One source of truth, and old lessons get chat without
re-rendering when viewed through the server.

### 3. `/lesson-chat` command — `commands/lesson-chat.md` (new)

Plugin command that locates the plugin root, starts `chat_server.py` in the
background (or reports the already-running one via `/api/health`), and opens
`http://127.0.0.1:8787/` in the browser. Mirrors the resolver pattern already
used in `commands/daily-lesson.md`.

## Error handling

- `claude` binary missing → SSE `error` event with a human message; widget
  shows it inline in the transcript (not an alert).
- Child process non-zero exit / malformed stream → `error` event with stderr
  tail; transcript keeps the user's message so retry is one click.
- Unknown lesson path → 404 JSON. Bad JSON body → 400. Busy lesson → 409.
- Server not running (file:// case) → graceful instructions, never a dead
  button.

## Testing

- **Unit (stdlib `unittest`, `tests/test_chat_server.py`):** health shape;
  origin policy (cross-origin POST rejected, same-origin accepted, no-Origin
  curl accepted); chat roundtrip on mock backend (SSE framing, transcript
  persisted, session continuity); reset; legacy-page injection
  (marker-present pages untouched); lesson-text extraction; stream-json parsing
  against captured real-CLI fixtures.
- **E2E (Playwright, `tests/e2e/`):** real Chromium against the server in mock
  mode with freshly rendered fixture lessons in a temp dir. Covers: button
  visible on every lesson page; drawer open/close; send → streamed reply
  appears; reload → transcript restored ("continue"); New chat resets; legacy
  page served with injected widget works; library → lesson nav. Screenshots
  captured for visual review. Node/Playwright are dev-only deps under
  `tests/e2e/`, gitignored `node_modules`.
- **Live smoke (manual, run during development):** real `claude` backend, two
  curl turns against an actual lesson; asserts streamed deltas and that turn 2
  resumes turn 1's `session_id`.

## Alternatives considered

- **Anthropic API directly from the page** — rejected: needs an API key,
  violating "same resources as Claude Code" (subscription auth) and the
  repo's local-only promise.
- **Long-lived `claude` child per chat (stdin streaming)** — rejected for v1:
  process lifecycle/cleanup complexity for marginal latency gain; `--resume`
  gives identical conversational state.
- **Widget as a separate JS file** — rejected: `file://` pages have no stable
  relative path to plugin assets; inlining keeps lessons self-contained (the
  repo's stated philosophy) at ~9KB/page.
- **Allowing chat from `file://` origins via CORS** — rejected: `Origin: null`
  is indistinguishable from a hostile sandboxed iframe; redirecting to the
  same-origin served page is one click and strictly safer.
