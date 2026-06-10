---
description: Start the local lesson-chat server and open my lesson library in the browser. Every lesson page gets a live chat powered by the local claude CLI.
allowed-tools: Bash, Read
argument-hint: "[optional port, default 8787]"
---

# Lesson Chat — talk to my lesson library

You are my server operator. Each time you run, you make sure the local
lesson-chat server is up, then open the library in my browser. The server
serves `~/.claude/daily-lessons/` over HTTP and bridges each lesson's chat to
my local `claude` CLI — same login, plan, and model as my normal sessions. It
binds `127.0.0.1` only; nothing is exposed to the network.

Optional argument: `$ARGUMENTS`
- If it's a port number like `9000`, use that port.
- If empty, use the default port `8787`.

In the snippets below, `$PORT` is that port.

---

## Step 0 — Resolve the helper and check prerequisites

The server ships with the plugin at `scripts/chat_server.py`, fronted by an
idempotent launcher `scripts/serve.sh` (reuse-if-healthy, else start). Resolve
the launcher the same way `/daily-lesson` resolves the renderer:

```bash
SERVE="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/serve.sh}"
[ -f "$SERVE" ] || SERVE="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/serve.sh' 2>/dev/null | sort -V | tail -1)"
```

If `$SERVE` is still empty or not a file, **stop immediately** — the plugin
install is broken; tell me the path you looked for. While you're here, check
the prerequisites:

- `command -v python3` — if missing, say exactly what to install: on macOS
  `brew install python3`, on Debian/Ubuntu `sudo apt install python3`.
- `command -v claude` — if missing, the server will start but every chat turn
  will fail. Tell me to install Claude Code so the `claude` CLI is on my PATH
  (it already is if I'm running this as a plugin).

---

## Step 1–2 — Ensure the server is up

`serve.sh` does the reuse-or-start dance for you: it returns fast if a healthy
instance is already on the port, otherwise starts one detached and waits for
health. It prints the base URL on stdout and exits 0; on failure it exits
non-zero with diagnostics on stderr.

```bash
BASE="$(sh "$SERVE" "$PORT" 2>/tmp/daily-lesson-chat.err)"   # http://127.0.0.1:$PORT
```

If `$BASE` is empty (non-zero exit), **fail loudly**: print
`/tmp/daily-lesson-chat.err` and the last ~20 lines of
`${TMPDIR:-/tmp}/daily-lesson-chat.log`, and the likely cause (port already
taken by something else, `python3` too old, lessons dir missing). Suggest a
different port: `/lesson-chat 8788`. Do not retry silently.

The server is detached, so it keeps running after this command (and after the
session) until I stop it — `lsof -ti ":$PORT"` finds its PID.

---

## Step 3 — Open the library

Open `http://127.0.0.1:$PORT/` in my default browser — `open` on macOS,
`xdg-open` on Linux; adapt to my platform.

---

## Step 4 — Report back to the terminal

When done, print:
- the **URL**: `http://127.0.0.1:$PORT/`,
- where chats are stored: `~/.claude/daily-lessons/chats.json`,
- the backend note: *answers come from your local `claude` CLI — same login,
  plan, and model as your normal sessions; conversation context lives in
  claude's own session storage via `--resume`*,
- how to stop it: `kill $(lsof -ti ":$PORT")`.

Note: `/daily-lesson` already calls `serve.sh` and opens each new lesson on
this server, so the chat is usually up before you ever run `/lesson-chat` — this
command is for opening the whole library, or bringing the server back after a
reboot.

---

## Hard rules

- **Never expose the server beyond `127.0.0.1`.** Don't pass a different bind
  address, don't suggest a tunnel, don't port-forward.
- **Never read the contents of `chats.json` into this conversation.** Those
  are my private transcripts; the server is their only reader.
- If `python3` or `claude` is missing, say exactly what to install (Step 0) —
  never half-start a server that can't answer.
- One server per port — `serve.sh` enforces this (it reuses a healthy
  instance); never start `chat_server.py` by hand alongside it.
