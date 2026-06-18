#!/usr/bin/env sh
# serve.sh — ensure the daily-lesson chat server is running, print its base URL.
#
# Idempotent AND version-aware: reuse a running server only when it is THIS
# plugin version; if a stale instance (an older build left running from before
# an update) holds the port, retire it and cold-start the current one;
# otherwise cold-start. This is the single source of truth both /daily-lesson
# and /lesson-chat call so a reader never starts anything by hand.
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

# The plugin version this server belongs to, from the manifest next to the
# resolved server. Empty when it can't be determined (no manifest / no python3);
# we then fall back to liveness-only reuse (the pre-version behaviour).
EXPECTED_VERSION=""
if [ -n "$SERVER" ] && command -v python3 >/dev/null 2>&1; then
  MANIFEST="$(dirname -- "$SERVER")/../.claude-plugin/plugin.json"
  if [ -f "$MANIFEST" ]; then
    EXPECTED_VERSION="$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("version") or "")
except Exception:
    pass' "$MANIFEST" 2>/dev/null)"
  fi
fi

probe() {
  # Echo the /api/health body if anything answers; nothing otherwise.
  curl -fsS --max-time 2 "$URL/api/health" 2>/dev/null
}
field() {
  # field <health-json-body> <key>  ->  value (or empty). Needs python3.
  python3 -c 'import json,sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    d = {}
print(d.get(sys.argv[2]) or "")' "$1" "$2" 2>/dev/null
}
is_ours() {
  # True if the body ($1) is this app answering.
  printf '%s' "$1" | grep -q 'daily-lesson-chat'
}
healthy() {
  # True only if THIS plugin version answers on the port. With EXPECTED_VERSION
  # unknown, fall back to "our app is answering" (liveness-only).
  body="$(probe)" || return 1
  is_ours "$body" || return 1
  [ -z "$EXPECTED_VERSION" ] && return 0
  [ "$(field "$body" plugin_version)" = "$EXPECTED_VERSION" ]
}

# Already up at the right version? Reuse it.
if healthy; then
  echo "$URL"
  exit 0
fi

# Something is on the port but not the right version. If it is OUR app (a stale
# older build), retire it so the cold start below brings up the current one.
body="$(probe)"
if [ -n "$body" ] && is_ours "$body"; then
  stale_ver="$(field "$body" plugin_version)"
  stale_pid="$(field "$body" pid)"
  echo "serve.sh: replacing stale chat server (v${stale_ver:-?} -> v${EXPECTED_VERSION:-?}) on port $PORT" >&2
  if [ -n "$stale_pid" ]; then
    kill "$stale_pid" 2>/dev/null
    # Wait (~5s) for it to release the port before we bind.
    k=0
    while [ "$k" -lt 25 ]; do
      probe >/dev/null 2>&1 || break
      sleep 0.2
      k=$((k + 1))
    done
  fi
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
