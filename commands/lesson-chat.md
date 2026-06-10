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

## Step 0 — Resolve the server script and fail loudly if you can't

The server ships with the plugin at `scripts/chat_server.py`. Resolve it the
same way `/daily-lesson` resolves the renderer:

```bash
SERVER="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/chat_server.py}"
[ -f "$SERVER" ] || SERVER="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/chat_server.py' 2>/dev/null | sort -V | tail -1)"
```

If `$SERVER` is still empty or not a file, **stop immediately** — the plugin
install is broken; tell me the path you looked for. While you're here, check
the prerequisites:

- `command -v python3` — if missing, say exactly what to install: on macOS
  `brew install python3`, on Debian/Ubuntu `sudo apt install python3`.
- `command -v claude` — if missing, the server will start but every chat turn
  will fail. Tell me to install Claude Code so the `claude` CLI is on my PATH
  (it already is if I'm running this as a plugin).

---

## Step 1 — Is it already running?

```bash
curl -s --max-time 2 "http://127.0.0.1:$PORT/api/health"
```

If that returns JSON with `"ok": true`, a healthy instance is already up — do
**not** start a second one. Skip straight to Step 3 and report the existing
URL (its PID, should I want to stop it later: `lsof -ti ":$PORT"`).

---

## Step 2 — Start the server in the background

```bash
nohup python3 "$SERVER" --port "$PORT" > /tmp/daily-lesson-chat.log 2>&1 &
echo "PID: $!"
```

Note the PID. Then poll `http://127.0.0.1:$PORT/api/health` every half-second
for up to ~5 seconds. If it never comes healthy, **fail loudly**: print the
last ~20 lines of `/tmp/daily-lesson-chat.log`, the exact command above so I
can run it by hand, and the likely cause (port taken by something else,
`python3` too old, lessons dir missing). Do not retry silently.

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
- how to stop it: `kill <PID>` — the PID printed in Step 2 (or, if the server
  was already running, the one `lsof -ti ":$PORT"` finds).

---

## Hard rules

- **Never expose the server beyond `127.0.0.1`.** Don't pass a different bind
  address, don't suggest a tunnel, don't port-forward.
- **Never read the contents of `chats.json` into this conversation.** Those
  are my private transcripts; the server is their only reader.
- If `python3` or `claude` is missing, say exactly what to install (Step 0) —
  never half-start a server that can't answer.
- One server per port. If the health check passes, report the existing
  instance; never stack a second one.
