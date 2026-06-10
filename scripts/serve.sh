#!/usr/bin/env sh
# serve.sh — ensure the daily-lesson chat server is running, print its base URL.
#
# Idempotent: if a healthy instance is already listening on the port, reuse it;
# otherwise start chat_server.py detached (survives this shell), wait for it to
# come healthy, and print the URL. This is the single source of truth both
# /daily-lesson and /lesson-chat call so a reader never has to start anything
# by hand — opening a lesson is enough.
#
# Usage: serve.sh [PORT]            # default 8787
# Stdout: the base URL (e.g. http://127.0.0.1:8787) on success — nothing else.
# Exit:   0 ready · 1 could not start (diagnostics on stderr) · 2 bad env.
#
# Honors $DAILY_LESSON_CHAT_BACKEND (claude|mock) and $DAILY_LESSON_CHAT_LOG.

PORT="${1:-8787}"
URL="http://127.0.0.1:${PORT}"
LOG="${DAILY_LESSON_CHAT_LOG:-${TMPDIR:-/tmp}/daily-lesson-chat.log}"

# Resolve chat_server.py next to this script (works from a checkout or the
# installed plugin cache), then fall back to the cache by glob.
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SERVER="$SCRIPT_DIR/chat_server.py"
if [ ! -f "$SERVER" ]; then
  SERVER="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/chat_server.py' 2>/dev/null | sort -V | tail -1)"
fi

healthy() {
  # True only if THIS app answers on the port (not some unrelated server).
  curl -fsS --max-time 2 "$URL/api/health" 2>/dev/null | grep -q 'daily-lesson-chat'
}

# Already up? Reuse it.
if healthy; then
  echo "$URL"
  exit 0
fi

if [ -z "$SERVER" ] || [ ! -f "$SERVER" ]; then
  echo "serve.sh: cannot find chat_server.py (looked next to $0 and in the plugin cache)" >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "serve.sh: python3 not found — install it (macOS: brew install python3, Debian: apt install python3)" >&2
  exit 2
fi

# Start detached so the server outlives this shell and future opens reuse it.
nohup python3 "$SERVER" --port "$PORT" >"$LOG" 2>&1 &
PID=$!

# Poll for health, ~6s.
i=0
while [ "$i" -lt 30 ]; do
  if healthy; then
    echo "$URL"
    exit 0
  fi
  # If the process died, stop waiting and surface the log.
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 0.2
  i=$((i + 1))
done

echo "serve.sh: chat server did not come up on port $PORT (pid $PID); last log lines:" >&2
tail -n 20 "$LOG" >&2 2>/dev/null
echo "serve.sh: try a different port, e.g. serve.sh 8788" >&2
exit 1
