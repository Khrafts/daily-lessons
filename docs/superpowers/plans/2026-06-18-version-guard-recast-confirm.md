# Server Version Guard + Recast Confirmation Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a stale-version chat server impossible to silently reuse, and gate recast (alternate-tone generation) behind a confirmation modal with a "Don't ask again" option and a reset affordance.

**Architecture:** `.claude-plugin/plugin.json` becomes the single source of truth for "what version is this code." `chat_server.py` reports it (plus its pid) on `/api/health`; `serve.sh` reads the same manifest and reuses a running server only when its reported version matches — otherwise it kills the stale pid and cold-starts. Separately, the frozen `daily-lesson-modes:v1` block in `assets/lesson-shell.html` wraps the existing generate-button handler in a native `<dialog>` confirmation, persisting the opt-out in `localStorage`.

**Tech Stack:** Python 3 stdlib `http.server`; POSIX `sh` + `curl` + `python3` for the launcher; vanilla JS + native `<dialog>` in a frozen HTML shell; `unittest` (Python) and Playwright (e2e).

---

## File Structure

- `scripts/chat_server.py` — add `PLUGIN_VERSION` (manifest read + env test seam); add `plugin_version` + `pid` to the `/api/health` body.
- `scripts/serve.sh` — version-aware `healthy()`, stale-instance retire-and-restart, graceful degradation.
- `assets/lesson-shell.html` — confirmation `<dialog>` + reset button + JS wiring inside the `daily-lesson-modes:v1` block.
- `tests/test_chat_server.py` — relax the health assertion to a superset incl. new fields.
- `tests/test_serve_sh.py` — new stale-version replacement test.
- `tests/e2e/specs/modes.spec.js` — update the existing generate flow to click through the modal; add a modal-behaviour spec.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version bump 0.4.0 → 0.4.1.
- `README.md` — one-line note on auto-replacing a stale server.

---

## Task 1: Server reports its plugin version + pid on /api/health

**Files:**
- Modify: `scripts/chat_server.py` (constants block near line 58-64; health handler near line 1193-1197)
- Test: `tests/test_chat_server.py:148-163` (`test_health`)

- [ ] **Step 1: Update the failing test**

Replace the body assertion in `tests/test_chat_server.py` `test_health` (lines 150-153) — keep the CORS assertions (lines 154-163) unchanged:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_chat_server.ChatServerTests.test_health -v`
Expected: FAIL with `KeyError: 'plugin_version'` (the health body lacks the new keys).

- [ ] **Step 3: Add `PLUGIN_VERSION` constant**

In `scripts/chat_server.py`, immediately after the constants block (after line 64, the `ARTICLE_HTML_CAP = ...` line) insert:

```python


def _read_manifest_version():
    """Plugin semver from .claude-plugin/plugin.json at the plugin root (the
    parent of this script's scripts/ dir). Returns 'unknown' if the manifest is
    absent or unparseable so a dev checkout / odd layout still serves."""
    try:
        manifest = (Path(__file__).resolve().parent.parent
                    / ".claude-plugin" / "plugin.json")
        return json.loads(manifest.read_text("utf-8")).get("version") or "unknown"
    except (OSError, ValueError):
        return "unknown"


# The plugin version this code belongs to. serve.sh compares it against the
# running server's reported value to retire a stale instance left over from
# before a plugin update. DAILY_LESSON_PLUGIN_VERSION is a test seam only — no
# production caller sets it.
PLUGIN_VERSION = os.environ.get("DAILY_LESSON_PLUGIN_VERSION") or _read_manifest_version()
```

- [ ] **Step 4: Add the fields to the health response**

In `scripts/chat_server.py`, the health branch of `do_GET` (lines 1193-1197) becomes:

```python
        if parts.path == "/api/health":
            self._send_json(200, {"ok": True, "app": APP_NAME,
                                  "version": API_VERSION,
                                  "plugin_version": PLUGIN_VERSION,
                                  "pid": os.getpid(),
                                  "backend": self.server.backend_name},
                            cors_origin=self._health_acao())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest tests.test_chat_server.ChatServerTests.test_health -v`
Expected: PASS

- [ ] **Step 6: Run the full chat-server suite (no regressions)**

Run: `python3 -m unittest tests.test_chat_server -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add scripts/chat_server.py tests/test_chat_server.py
git commit -m "feat(server): report plugin_version and pid on /api/health"
```

---

## Task 2: serve.sh reuses only a matching-version server; retires a stale one

**Files:**
- Modify: `scripts/serve.sh` (full rewrite of the resolve/health/reuse section, preserving the cold-start tail)
- Test: `tests/test_serve_sh.py` (add a method to `ServeShTests`)

- [ ] **Step 1: Write the failing test**

Add this method to the `ServeShTests` class in `tests/test_serve_sh.py` (after `test_cold_start_then_idempotent_reuse`):

```python
    def test_replaces_stale_version(self):
        # A server reporting an OLD plugin version is started directly (not via
        # serve.sh). serve.sh must retire it and bring up the current version.
        server = REPO / "scripts" / "chat_server.py"
        stale_env = dict(self.env, DAILY_LESSON_PLUGIN_VERSION="0.0.1-stale")
        stale = subprocess.Popen(
            ["python3", str(server), "--port", str(self.port)],
            env=stale_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(stale.terminate)

        base = "http://127.0.0.1:%d" % self.port
        for _ in range(40):
            try:
                body = urllib.request.urlopen(base + "/api/health", timeout=2).read()
                if json.loads(body).get("plugin_version") == "0.0.1-stale":
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            self.fail("stale server never came up")
        stale_pid = stale.pid

        # serve.sh with normal env: should replace the stale instance.
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), base)

        # The live server now reports the REAL manifest version, not the stale one.
        expected = json.loads(
            (REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
        body = json.loads(urllib.request.urlopen(base + "/api/health", timeout=3).read())
        self.assertEqual(body["plugin_version"], expected)
        self.assertNotEqual(body["pid"], stale_pid)

        # The stale process is gone, and exactly one listener remains.
        for _ in range(20):
            if stale.poll() is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(stale.poll(), "stale server was not killed")
        if shutil.which("lsof"):
            self.assertEqual(len(_pids_on(self.port)), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_serve_sh.ServeShTests.test_replaces_stale_version -v`
Expected: FAIL — today's `serve.sh` reuses the stale server (its health passes the liveness-only check), so `body["plugin_version"]` is still `"0.0.1-stale"` and the assertion fails.

- [ ] **Step 3: Rewrite serve.sh to be version-aware**

Replace the entire contents of `scripts/serve.sh` with:

```sh
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
```

- [ ] **Step 4: Keep the executable bit**

Run: `chmod +x scripts/serve.sh`

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python3 -m unittest tests.test_serve_sh.ServeShTests.test_replaces_stale_version -v`
Expected: PASS

- [ ] **Step 6: Run the full serve.sh suite (reuse path still works)**

Run: `python3 -m unittest tests.test_serve_sh -v`
Expected: PASS — `test_cold_start_then_idempotent_reuse` still passes (same-version reuse is fast, single listener).

- [ ] **Step 7: Commit**

```bash
git add scripts/serve.sh tests/test_serve_sh.py
git commit -m "feat(serve): retire a stale-version server instead of reusing it"
```

---

## Task 3: Recast confirmation modal + reset affordance

**Files:**
- Modify: `assets/lesson-shell.html` (the `daily-lesson-modes:v1` block: CSS near 927-960, markup near 962-966, JS near 968-1057)
- Test: `tests/e2e/specs/modes.spec.js`

- [ ] **Step 1: Add the modal + reset CSS**

In `assets/lesson-shell.html`, immediately before the `</style>` that closes the modes block (line 959-960, after the `@media print{#dlm-bar...}` rule), insert:

```css
  /* confirm-before-generate modal + reset affordance */
  .dlm-reset{
    border:0;background:none;cursor:pointer;padding:0;margin-left:.2rem;
    color:var(--muted,#6b6b6b);font:inherit;letter-spacing:inherit;text-transform:inherit;
    text-decoration:underline;text-underline-offset:2px;
  }
  .dlm-reset:hover{color:var(--ink,#111)}
  .dlm-reset[hidden]{display:none}
  .dlm-confirm{
    border:1px solid var(--line,#e6e6e6);border-radius:12px;padding:0;
    max-width:30rem;width:calc(100% - 2rem);
    color:var(--ink,#111);background:var(--paper,#fff);
    box-shadow:0 12px 40px rgba(0,0,0,.18);
  }
  .dlm-confirm::backdrop{background:rgba(0,0,0,.32)}
  .dlm-confirm-inner{padding:1.4rem 1.5rem 1.2rem}
  .dlm-confirm-title{
    margin:0 0 .6rem;font-family:Fraunces,"Iowan Old Style",Georgia,serif;
    font-size:1.18rem;font-weight:600;letter-spacing:0;text-transform:none;
  }
  .dlm-confirm-body{
    margin:0 0 1rem;font-family:Fraunces,"Iowan Old Style",Georgia,serif;
    font-size:.95rem;line-height:1.5;letter-spacing:0;text-transform:none;color:var(--ink,#111);
  }
  .dlm-confirm-body code{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em}
  .dlm-confirm-skip{
    display:flex;align-items:center;gap:.45rem;margin:0 0 1.2rem;cursor:pointer;
    font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.7rem;
    letter-spacing:.04em;text-transform:uppercase;color:var(--muted,#6b6b6b);
  }
  .dlm-confirm-actions{display:flex;justify-content:flex-end;gap:.6rem}
  .dlm-btn{
    font:inherit;letter-spacing:inherit;text-transform:inherit;cursor:pointer;
    border:1px solid var(--line,#e6e6e6);border-radius:999px;padding:.4rem .9rem;
    background:var(--paper,#fff);color:var(--ink,#111);
  }
  .dlm-btn-primary{background:var(--ink,#111);color:var(--paper,#fff);border-color:var(--ink,#111)}
  .dlm-btn-ghost:hover{border-color:var(--ink,#111)}
  .dlm-btn:focus-visible{outline:2px solid var(--ink,#111);outline-offset:2px}
  @media print{.dlm-confirm{display:none !important}}
```

- [ ] **Step 2: Add the reset button + dialog markup**

In `assets/lesson-shell.html`, replace the bar markup (lines 962-966) with the bar (now containing a reset button) plus the dialog:

```html
<div id="dlm-bar" data-testid="modes-bar" aria-label="Lesson tone" hidden>
  <span class="dlm-label">Tone</span>
  <span class="dlm-tones" data-testid="modes-tones"></span>
  <span class="dlm-status" data-testid="modes-status" role="status" aria-live="polite"></span>
  <button type="button" class="dlm-reset" data-testid="modes-reset" hidden>Always ask before generating</button>
</div>

<dialog id="dlm-confirm" class="dlm-confirm" data-testid="modes-confirm" aria-labelledby="dlm-confirm-title">
  <div class="dlm-confirm-inner">
    <h2 id="dlm-confirm-title" class="dlm-confirm-title">Generate this tone?</h2>
    <p class="dlm-confirm-body" data-testid="modes-confirm-body"></p>
    <label class="dlm-confirm-skip"><input type="checkbox" data-testid="modes-confirm-skip"> Don't ask again</label>
    <div class="dlm-confirm-actions">
      <button type="button" class="dlm-btn dlm-btn-ghost" data-testid="modes-confirm-cancel">Cancel</button>
      <button type="button" class="dlm-btn dlm-btn-primary" data-testid="modes-confirm-go">Generate</button>
    </div>
  </div>
</dialog>
```

- [ ] **Step 3: Wire the modal in the modes IIFE**

In `assets/lesson-shell.html`, the modes IIFE (`<script>` at line 968). Make three edits:

(a) After the early `file://` return guard (after line 979 `if(!(location.protocol...)) return;`), add the self-contained storage helpers, element refs, and state:

```js
  // Self-contained localStorage (the chat IIFE's helpers are out of this scope)
  // + confirm-before-generate state. SKIP_KEY persists the "don't ask again".
  function mGet(k){try{return window.localStorage.getItem(k);}catch(e){return null;}}
  function mSet(k,v){try{window.localStorage.setItem(k,v);}catch(e){}}
  function mDel(k){try{window.localStorage.removeItem(k);}catch(e){}}
  var SKIP_KEY='dlm-recast-skip-confirm';
  var resetBtn=bar.querySelector('.dlm-reset');
  var dlg=document.getElementById('dlm-confirm');
  var dlgTitle=dlg?dlg.querySelector('.dlm-confirm-title'):null;
  var dlgBody=dlg?dlg.querySelector('[data-testid="modes-confirm-body"]'):null;
  var dlgSkip=dlg?dlg.querySelector('[data-testid="modes-confirm-skip"]'):null;
  var dlgGo=dlg?dlg.querySelector('[data-testid="modes-confirm-go"]'):null;
  var dlgCancel=dlg?dlg.querySelector('[data-testid="modes-confirm-cancel"]'):null;
  var pending=null;

  function syncReset(){ if(resetBtn) resetBtn.hidden = (mGet(SKIP_KEY)!=='1'); }
  function fillBody(label){
    if(!dlgBody) return;
    dlgBody.textContent='';
    dlgBody.appendChild(document.createTextNode('This runs your local '));
    var code=document.createElement('code'); code.textContent='claude';
    dlgBody.appendChild(code);
    dlgBody.appendChild(document.createTextNode(' to rewrite this lesson in the '));
    var strong=document.createElement('strong'); strong.textContent=label;  // escape-first
    dlgBody.appendChild(strong);
    dlgBody.appendChild(document.createTextNode(' tone. It can take up to a minute and'
      +' counts against your Claude usage, like a chat turn. The new tone is saved'
      +' next to this lesson — nothing leaves your machine.'));
  }
  function proceed(){
    var a=pending; pending=null;
    if(dlgSkip&&dlgSkip.checked){ mSet(SKIP_KEY,'1'); syncReset(); }
    if(dlg&&dlg.open){ try{dlg.close();}catch(e){} }
    if(a) generate(a);
  }
  function confirmThenGenerate(a){
    if(mGet(SKIP_KEY)==='1'){ generate(a); return; }
    pending=a;
    if(dlgTitle) dlgTitle.textContent='Generate the '+a.label+' version?';
    fillBody(a.label);
    if(dlgSkip) dlgSkip.checked=false;
    if(dlg&&dlg.showModal){ dlg.showModal(); if(dlgGo) dlgGo.focus(); }
    else { proceed(); }  // no <dialog> support → just generate
  }
  if(dlgGo) dlgGo.addEventListener('click',proceed);
  if(dlgCancel) dlgCancel.addEventListener('click',function(){ if(dlg&&dlg.open){try{dlg.close();}catch(e){}} });
  if(dlg){
    dlg.addEventListener('close',function(){ pending=null; });
    dlg.addEventListener('click',function(e){ if(e.target===dlg){ try{dlg.close();}catch(_){} } }); // backdrop
  }
  if(resetBtn) resetBtn.addEventListener('click',function(){ mDel(SKIP_KEY); syncReset(); });
  syncReset();
```

(b) In `genBtn(a)` (line 1020), change the click handler from calling `generate` to `confirmThenGenerate`:

```js
    b.addEventListener('click',function(){ confirmThenGenerate(a); });
```

(c) At the end of `render(data)` (after line 1028 `bar.hidden = ...`), keep the reset state in sync when the bar (re)renders:

```js
    syncReset();
```

- [ ] **Step 4: Update the existing e2e test to click through the modal**

In `tests/e2e/specs/modes.spec.js`, replace the generate block (lines 25-31) with:

```js
    // Generate the Tutorial rendition: a confirmation modal appears first.
    await page
      .getByTestId('modes-generate')
      .filter({ hasText: 'Tutorial' })
      .first()
      .click();
    await expect(page.getByTestId('modes-confirm')).toBeVisible();
    await page.getByTestId('modes-confirm-go').click();
    await page.waitForURL(/fixture-alpha-tutorial\.html/, { timeout: 20000 });
```

- [ ] **Step 5: Add a modal-behaviour e2e spec**

Append this `test` inside the `test.describe('lesson tone bar', ...)` block in `tests/e2e/specs/modes.spec.js` (before the closing `});` on line 55):

```js
  test('confirm modal: cancel, remember choice, and reset', async ({ page }) => {
    await page.goto('/' + ALPHA);
    await expect(page.getByTestId('modes-bar')).toBeVisible();

    // Count recast attempts; abort them so no page navigation happens.
    let recastCalls = 0;
    await page.route('**/api/recast', (route) => {
      recastCalls += 1;
      route.abort();
    });

    const dlg = page.getByTestId('modes-confirm');

    // Cancel does NOT start a recast.
    await page.getByTestId('modes-generate').filter({ hasText: 'Concise' }).first().click();
    await expect(dlg).toBeVisible();
    await page.getByTestId('modes-confirm-cancel').click();
    await expect(dlg).toBeHidden();
    expect(recastCalls).toBe(0);

    // Opt out: check "Don't ask again" and confirm → recast attempted, reset shows.
    await page.getByTestId('modes-generate').filter({ hasText: 'Concise' }).first().click();
    await expect(dlg).toBeVisible();
    await page.getByTestId('modes-confirm-skip').check();
    await page.getByTestId('modes-confirm-go').click();
    await expect.poll(() => recastCalls).toBe(1);
    await expect(page.getByTestId('modes-reset')).toBeVisible();

    // Choice remembered: the next generate skips the dialog entirely.
    await page.getByTestId('modes-generate').filter({ hasText: 'Tutorial' }).first().click();
    await expect.poll(() => recastCalls).toBe(2);
    await expect(dlg).toBeHidden();

    // Reset re-enables the prompt.
    await page.getByTestId('modes-reset').click();
    await expect(page.getByTestId('modes-reset')).toBeHidden();
    await page.getByTestId('modes-generate').filter({ hasText: 'Tutorial' }).first().click();
    await expect(dlg).toBeVisible();
  });
```

- [ ] **Step 6: Run the e2e suite**

Run: `cd tests/e2e && npm ci >/dev/null 2>&1; npx playwright install chromium >/dev/null 2>&1; npx playwright test specs/modes.spec.js`
Expected: PASS (both specs). If Playwright/browsers can't be installed in this environment, note it and fall back to Step 7's static verification; do not skip the spec edits.

- [ ] **Step 7: Static sanity check of the rendered shell**

Run: `python3 -c "import pathlib,sys; h=pathlib.Path('assets/lesson-shell.html').read_text(); sys.exit(0 if ('id=\"dlm-confirm\"' in h and 'confirmThenGenerate' in h and h.count('daily-lesson-modes:v1')>=1) else 1)" && echo OK`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add assets/lesson-shell.html tests/e2e/specs/modes.spec.js
git commit -m "feat(modes): confirm before generating a tone, with don't-ask-again + reset"
```

---

## Task 4: Version bump + README note

**Files:**
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`

- [ ] **Step 1: Bump plugin.json**

In `.claude-plugin/plugin.json`, change `"version": "0.4.0"` to `"version": "0.4.1"`.

- [ ] **Step 2: Bump marketplace.json**

In `.claude-plugin/marketplace.json`, change the `daily-lesson` plugin entry's `"version": "0.4.0"` to `"version": "0.4.1"` (leave the top-level `metadata.version` `1.0.0` as-is).

- [ ] **Step 3: README note**

In `README.md`, find the section describing the chat/lesson server (search for `serve.sh` or "server"). Add a short sentence:

> After a plugin update, the next lesson you open automatically replaces any
> still-running older server — no manual restart needed.

If no natural spot exists, add it under the existing server/troubleshooting note.

- [ ] **Step 4: Verify manifests agree**

Run: `python3 -c "import json; a=json.load(open('.claude-plugin/plugin.json'))['version']; b=[p for p in json.load(open('.claude-plugin/marketplace.json'))['plugins'] if p['name']=='daily-lesson'][0]['version']; print(a,b); assert a==b=='0.4.1'"`
Expected: prints `0.4.1 0.4.1` with no assertion error.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json README.md
git commit -m "chore: release 0.4.1 — server version guard + recast confirm"
```

---

## Task 5: Full verification

- [ ] **Step 1: Run the entire Python test suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (all). In particular `test_chat_server`, `test_serve_sh`, `test_render_lesson`, `test_render_variant`, `test_recast_api`.

- [ ] **Step 2: Confirm the version is consistent end-to-end**

Run: `DAILY_LESSON_CHAT_BACKEND=mock sh scripts/serve.sh 8791 && curl -fsS http://127.0.0.1:8791/api/health; echo; kill $(curl -fsS http://127.0.0.1:8791/api/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["pid"])')`
Expected: health JSON shows `"plugin_version": "0.4.1"` and a `pid`; the kill cleans up the test server.

- [ ] **Step 3: Final status check**

Run: `git log --oneline -6 && git status -s`
Expected: the four feature commits present; working tree clean (the untracked `COWORK-PORTING-REPORT.md` may remain — leave it).

---

## Self-Review

- **Spec coverage:** Part 1 server → Task 1; Part 1 launcher → Task 2; Part 2 modal + reset → Task 3; release bump + README → Task 4; verification → Task 5. All spec sections mapped.
- **Placeholders:** none — every code/test step shows full content.
- **Type/name consistency:** health keys `plugin_version`/`pid` used identically in `chat_server.py`, `serve.sh` (`field "$body" plugin_version`/`pid`), and both tests. JS uses `SKIP_KEY='dlm-recast-skip-confirm'` consistently with `confirmThenGenerate`/`proceed`/`syncReset`; test selectors (`modes-confirm`, `modes-confirm-go`, `modes-confirm-cancel`, `modes-confirm-skip`, `modes-reset`) match the markup in Step 2.
