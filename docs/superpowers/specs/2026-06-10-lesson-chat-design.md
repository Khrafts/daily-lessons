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
| `/api/chat?lesson=lessons/<f>.html[&conversation=<id>]` | GET | conversation summaries + the selected conversation's transcript & session metadata | same-origin only |
| `/api/chat` | POST `{lesson, message, conversation?}` | run one turn on the target conversation; respond as SSE: `delta` events, then `done` (now carries `conversation`) | same-origin only |
| `/api/chat/new` | POST `{lesson}` | create an empty conversation and make it active | same-origin only |
| `/api/chat/switch` | POST `{lesson, conversation}` | set the active conversation; return its transcript | same-origin only |
| `/api/chat/delete` | POST `{lesson, conversation}` | remove one conversation (busy → 409) | same-origin only |
| `/api/chat/reset` | POST `{lesson}` | wipe **all** conversations for the lesson | same-origin only |

The endpoint shapes below are the **v2** contract (multiple conversations per
lesson). See the *v2* section near the end of this doc for the full request/
response payloads and the conversation-by-id turn routing invariant.

**Same-origin enforcement:** mutating/reading chat endpoints reject any request
whose `Origin` header is present and ≠ the server's own origin (curl/no-Origin
is allowed). POST bodies must be `application/json`, which forces a CORS
preflight from browsers — and the preflight is only approved for `/api/health`.
This blocks drive-by requests from random websites *and* from `file://`/null
origins, which are indistinguishable from hostile sandboxed iframes.

**Host pinning:** every request's `Host` header must name a loopback origin
(`127.0.0.1`, `localhost`, `[::1]` — optionally with a port); anything else is
rejected with 403. This defuses DNS rebinding, where a hostile page's domain
re-resolves to 127.0.0.1 and its same-"origin" requests reach the server with
the attacker's hostname in `Host`.

**Transcript privacy:** `chats.json` lives in the library root but is excluded
from static serving (404, compared against its resolved path so a symlink can't
slip past). Transcripts are only reachable through the same-origin `/api/chat`
GET. The tutor subprocess also can't reach it: its `cwd` is the `lessons/`
subdir (rendered pages only), so `Read`/`Grep`/`Glob` see sibling lessons but
not the `chats.json` one level up, and the tutor prompt forbids echoing secrets.

**Claude invocation** (per message, one-shot process — no long-lived child):

```
claude -p
  --output-format stream-json --verbose --include-partial-messages
  --append-system-prompt <tutor role + full lesson text>
  [--resume <session_id>]                  # continue = resume
  --allowedTools Read Grep Glob            # can read sibling lessons; nothing else
  --strict-mcp-config                      # no MCP servers → fast startup
  --settings '{"disableAllHooks": true}'   # user hooks never fire inside a chat turn
  <<< message                              # the message rides on stdin, not argv
```

- cwd = the `lessons/` subdir (not the library root) so the tool root holds
  only rendered pages; the `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, and
  `CLAUDE_CODE_SSE_PORT` env vars are stripped so the nested run behaves like
  a fresh headless session instead of attaching to this one. The stored
  `session_id` is format-checked before it reaches `--resume` (it must start
  with an alphanumeric, so a hand-edited `chats.json` can't smuggle a flag).
- The lesson's text (HTML → plain text, server-side) rides in
  `--append-system-prompt` on **every** turn, so answers stay grounded even on
  resumed sessions.
- Parsed events: `system/init` → capture `session_id`; `stream_event`
  `text_delta` → SSE `delta`; `result` → SSE `done` (with fallback to the full
  `assistant` message if no partials arrived).
- One in-flight turn per lesson (per-lesson lock); a second send while busy
  gets a 409.

**Persistence:** `~/.claude/daily-lessons/chats.json`. The **v2** shape holds
multiple conversations per lesson — see the *v2* section for the schema and the
load-time migration from the v1 single-conversation shape. The transcript of the
selected/active conversation is what the widget restores on page load; each
conversation's `session_id` is what makes "continue" real (full model-side
context via `--resume`).

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
  JetBrains Mono uppercase, subtle hover lift. Reads `Continue the chat` when
  a saved chat exists for this lesson.
- Clicking slides in a right-hand drawer (~400px; full-width on mobile):
  header (`Lesson chat · #N`), scrollable transcript, textarea + send.
  Assistant turns render minimal markdown (escape-first; fenced code with copy
  button, inline code, bold/em, lists) in the lesson's typography. A thin
  "thinking" shimmer shows while waiting for the first delta; text streams in
  live. `Esc` or ✕ closes; state survives reopen.
- **New chat** button in the drawer header → `/api/chat/new` (v2): creates a
  fresh, empty conversation and switches the view to it. Non-destructive — older
  conversations stay and appear in the history list. No `confirm()`.
- **History** + **Expand** header buttons (v2) — see the *v2* section.
- **Serving-mode awareness:**
  - Page served by `chat_server.py` (http) → fully live.
  - Page opened via `file://` → the widget probes `http://127.0.0.1:8787/api/health`.
    Server up → the button becomes `Open lesson chat ↗`: one click navigates
    to the same lesson on the server origin (with `?chat=1` to auto-open the
    drawer). Server down → the drawer explains how to start it (`/lesson-chat`
    inside Claude Code, or the `python3 …/chat_server.py` one-liner) with a
    copy button.

**Legacy pages & widget upgrades** (rendered before this feature, or with an
older widget): the server holds one canonical block — extracted at startup from
its own `assets/lesson-shell.html`. When serving a lesson page it **inserts**
the block before `</body>` if absent, and **replaces** an older baked block
(same markers, different content) with the current one; a page already carrying
the identical block is served byte-identical. So a served lesson always runs the
current widget — old lessons get chat, and lessons baked with a v1 widget pick
up the multi-conversation/expand UI — all without re-rendering. (A `file://`
page keeps whatever it was baked with until opened through the server.)

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
- Stale `--resume` session (e.g. the CLI's session store was pruned) →
  self-heals: if the turn failed before streaming any deltas, the server
  retries it once without `--resume`, and the chat continues under the fresh
  session id.
- Unknown lesson path → 404 JSON. Bad JSON body → 400. Busy lesson → 409 (a
  reset during an in-flight turn is refused the same way).
- Server not running (file:// case) → graceful instructions, never a dead
  button.

## v2: multiple conversations + expand

v1 gave each lesson exactly one chat; "New chat" wiped it. v2 lets a lesson hold
**many** conversations: start a fresh one without losing the old, browse the
lesson's chat history, switch between them, and expand the drawer for a wider
reading view. The transport, security model, backends, streaming, and grounding
are unchanged — only the persistence shape, the conversation-routing logic, and
the widget's drawer chrome grow.

### chats.json shape (v2) + migration

```jsonc
{
  "lessons/<file>.html": {
    "active_id": "c-ab12…" ,            // the conversation the widget shows by default; null when none
    "conversations": [
      {
        "id": "c-ab12…",                // server-minted, stable for the life of the conversation
        "title": "First user message…", // derived from the first user message (collapsed, ≤48 chars)
        "session_id": "…" ,             // claude --resume id for THIS conversation; null until the first turn
        "messages": [{ "role", "text", "ts" }],
        "created_at": "…",
        "updated_at": "…"               // bumped on every append; list orders by this, newest first
      }
    ]
  }
}
```

**Migration at load:** a v1 entry (`{session_id, messages}`) is rewritten on
first read into a single conversation `{id, title (from its first user message),
session_id, messages, created_at, updated_at}`, which becomes `active_id`. An
already-v2 entry is left as-is. Empty/legacy/garbage entries normalise to
`{active_id: null, conversations: []}`. All mutations stay atomic under the store
lock + tmp-file `os.replace`.

`ChatStore` gains conversation-aware methods (names internal): `get_view(lesson,
conversation=None)` (the GET base shape); `new_conversation(lesson)`;
`switch(lesson, id)`; `delete_conversation(lesson, id)`; `append_message(lesson,
conv_id, role, text)` (sets the title on the first user message, bumps
`updated_at`); `finish_turn(lesson, conv_id, session_id, text)`;
`ensure_active(lesson)` (creates one if none); `reset(lesson)` (wipe all).

### Endpoints (v2 payloads)

- **GET `/api/chat?lesson=<l>[&conversation=<id>]`** → `200`:
  ```jsonc
  {
    "ok": true, "lesson": "<l>", "active_id": "<id|null>",
    "conversations": [{ id, title, session_id, message_count, created_at, updated_at }],
    "messages": [ /* the SELECTED conversation's messages */ ],
    "session_id": "<selected conv's session_id | null>",
    "conversation": "<selected id | null>"
  }
  ```
  `conversations` is newest-by-`updated_at` first. The **selected** conversation
  is `?conversation=` if given (`404 {"error":"unknown conversation"}` when that
  id isn't in this lesson), else the active one, else none (`messages: []`).
  Reading never changes `active_id`. Unknown lesson → `404 {"error":"unknown
  lesson"}`.
- **POST `/api/chat`** `{lesson, message, conversation?}` → SSE (framing
  unchanged). The turn **resolves its target conversation id up front and
  operates on it by id** for the whole turn — so a concurrent `/new` or `/switch`
  that moves `active_id` can never misroute an in-flight turn. Resolution: given
  + unknown → `404` before streaming; given + known → that id; else the active
  one; else create one (it becomes active). The user message is persisted to that
  id first (also sets the title on the first user message); `finish_turn` writes
  the assistant message + `session_id` + `updated_at` to that **same** id. The
  `done` payload now includes `"conversation": <id>` alongside `{session_id,
  text}`. The per-lesson turn lock still serialises POST `/api/chat`.
- **POST `/api/chat/new`** `{lesson}` → `200 {ok, id, active_id, conversations}`.
  Creates an empty conversation (title `"New chat"`) and makes it active; never
  clears others. Store-lock only — no turn lock (purely additive).
- **POST `/api/chat/switch`** `{lesson, conversation}` → `200 {ok, active_id,
  conversation, messages, session_id}` or `404`. Sets `active_id`; allowed
  mid-turn (store-lock only).
- **POST `/api/chat/delete`** `{lesson, conversation}` → takes the per-lesson
  turn lock **non-blocking** (`409 {"error":"busy"}` if a turn is in flight, so a
  streaming conversation is never deleted). Removes the conversation; if it was
  active, `active_id` becomes the most-recently-updated remaining conversation,
  or `null`. → `200 {ok, active_id, conversations}` or `404`.
- **POST `/api/chat/reset`** `{lesson}` → now means **wipe all** conversations
  (`conversations: []`, `active_id: null`). Still takes the turn lock
  non-blocking (`409` if busy). Returns `{ok: true}`.

All POST bodies: `400 {"error":"bad request"}` on missing/non-string required
fields; `404` unknown lesson; `close_connection` set on the unconsumed-body error
paths. The same-origin + host-pin guards apply to every `/api/*` route exactly as
in v1.

### Widget — history + expand UX

The drawer header gains two buttons next to **New chat**:

- **History** (`#dlc-history`) toggles a conversation list (`#dlc-convs`, hidden
  by default). Opening it re-fetches GET `/api/chat` and renders the rows newest
  first; each row is a button with the title, a relative-time + message-count
  meta line, a per-row delete `×` (`.dlc-conv-del`), and `aria-current="true"` +
  an `is-active` class on the active one.
- **Expand** (`#dlc-expand`) toggles `#dlc-panel[data-expanded]`, persists the
  choice in `localStorage["dlc-expanded"]` (`"1"`/`"0"`), and applies it at init.
  `aria-pressed` mirrors the state and the label/title flips Expand↔Collapse.
  Expanded, the drawer is wider and the transcript/input sit in a centered
  reading column.

Behaviour (LIVE mode; bridge/offline unchanged): **init** renders the
conversation list and the active conversation's messages, and sets the FAB label
(empty active → "Ask about this lesson"; has messages → "Continue the chat").
**Send** posts `{lesson, message, conversation: <active id>}`; the active
conversation's title/`updated_at` may change, so the list is refreshed lazily
(re-fetched the next time History opens). **New chat** clears the view, switches
to the new (active) conversation, refreshes the list, focuses the input — no
`confirm()`. **Switch** (click a row) posts `/api/chat/switch`, loads that
conversation's messages, marks it active. **Delete** (`× `) `confirm("Delete
this chat? This removes its transcript.")` then posts `/api/chat/delete`,
refreshes the list, and loads the new active (or empty) transcript.

**Security:** conversation titles come from user text and are rendered
**escape-first** (`textContent`/`escHtml`), never via unescaped `innerHTML` — the
same rule already applied to message bodies. No new `innerHTML` sink receives
unescaped server/user strings.

## Accepted v1 tradeoffs

- `/api/health` grants the CORS read header only to `file://` callers
  (`Origin: null`) — the legitimate discovery case. A real website can still
  detect the server with a no-cors probe (timing), but cannot read the
  version/backend body cross-origin. The payload is non-secret anyway (no lesson
  content, transcripts, or paths).
- The widget's bridge mode (a `file://` page deep-linking into a running
  server) targets the default port `127.0.0.1:8787`, baked into the frozen
  shell. A server started on a non-default port still works for pages served
  *through* it; only the `file://`→server hand-off assumes the default, because
  a `file://` page has no way to learn which port the server chose.
- Two server instances pointed at the same lessons dir can clobber each
  other's `chats.json` (last write wins). Acceptable for a single-user local
  tool — and `/lesson-chat` reuses a healthy running instance via
  `/api/health` instead of double-starting one.

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
