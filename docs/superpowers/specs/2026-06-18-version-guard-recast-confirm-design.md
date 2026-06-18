# Server version guard + recast confirmation modal — design

**Date:** 2026-06-18
**Branch:** `feat/version-guard-recast-confirm`
**Status:** approved direction, ready for implementation plan

## Problem

Two issues surfaced from a real incident:

1. **Stale-version server.** `scripts/serve.sh` is "reuse-if-healthy": it
   health-checks the port and reuses any process that answers `/api/health`
   with `daily-lesson-chat`. It never checks *which version of the code* is
   answering. After a plugin update (0.3.0 → 0.4.0) a leftover 0.3.0 process
   kept being reused, so none of the 0.4.0 features (`/api/recast`, mode
   rendering) were reachable. The only workaround was a manual
   `kill $(lsof -ti :8787)`. `/reload-plugins` does not restart a detached
   server. This must become structurally impossible.

2. **No confirmation before recasting.** Clicking a "+ {tone}" button on a
   lesson immediately runs the local `claude` CLI to generate an alternate-tone
   rendition — a minute-long call that counts against the user's Claude usage —
   with no explanation of what is about to happen. We want a confirmation modal
   that explains the action, with a "Don't ask again" option and a way to
   re-enable the prompt later.

Both ship together on one feature branch.

## Root cause (issue 1)

Reuse is keyed on *liveness*, not *version*. `/api/health` reports
`API_VERSION = 1` (the wire-protocol contract, intentionally frozen), not the
plugin semver. The plugin semver lives in `.claude-plugin/plugin.json`
(`version: "0.4.0"`), read by no one at runtime.

Fix: make `.claude-plugin/plugin.json` the single source of truth for "what
version is this", read by **both** the server (at runtime, to report it) and
`serve.sh` (at launch, to decide reuse-vs-restart).

## Design

### Part 1 — version-aware server reuse

**`scripts/chat_server.py`**

- At import/startup, resolve the manifest at
  `Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"`,
  parse `version`, cache as module constant `PLUGIN_VERSION`. Fall back to
  `"unknown"` if the file is absent/unparseable (dev checkout, odd layout).
- Test seam: `PLUGIN_VERSION = os.environ.get("DAILY_LESSON_PLUGIN_VERSION") or _read_manifest_version()`.
  Lets a test launch a server that *reports* a stale version without a second
  checkout. No production caller sets this var.
- `/api/health` body gains two fields:
  - `plugin_version` — e.g. `"0.4.0"`.
  - `pid` — `os.getpid()`, so the launcher can kill a stale instance portably
    (no `lsof` dependency).
  - `version` (API_VERSION = 1) is unchanged — a separate contract.
- The health endpoint stays local-only and CORS-restricted exactly as today
  (the `pid`/`plugin_version` body is already only readable by same-origin or
  `Origin: null` callers; a local actor could read the pid via the OS anyway, so
  this adds no meaningful surface).

**`scripts/serve.sh`**

- Compute `EXPECTED_VERSION` by reading the `version` field from the
  `plugin.json` next to the resolved `$SERVER` (`$(dirname "$SERVER")/../.claude-plugin/plugin.json`),
  using python3 (already a hard dependency of the script).
- `healthy()` returns true **only** when the running server is our app *and* its
  `plugin_version == EXPECTED_VERSION`.
  - Same version → reuse (fast path, behaviour unchanged).
- New "stale our-app" branch: if the port answers as `daily-lesson-chat` but
  `healthy()` is false (version mismatch), it is a stale instance:
  - log `serve.sh: replacing stale chat server (vX → vY) on port N` to stderr,
  - `kill` the `pid` from the health body,
  - poll until the port stops answering (~5s budget),
  - fall through to the existing cold-start path.
- Graceful degradation: if `EXPECTED_VERSION` can't be determined (no manifest,
  no python3), skip the version comparison entirely and behave exactly as today
  (liveness-only reuse), so dev checkouts and minimal environments still work.
- Foreign (non-our-app) server on the port → unchanged: cold-start attempt
  fails to bind and surfaces the existing diagnostic.

Net effect: the first `/daily-lesson` or `/lesson-chat` after any plugin update
silently retires the old server and starts the new one. The manual kill is never
needed again. In-flight chats are only interrupted on an actual version change
(rare, intentional), never on same-version reuse.

**Tests**

- `tests/test_chat_server.py`: the health test currently `assertEqual`s the
  exact dict — relax to assert the superset (existing keys + `plugin_version`
  is a non-empty string + `pid` is a positive int).
- `tests/test_serve_sh.py`: new case — start a server *directly* (not via
  serve.sh) with `DAILY_LESSON_PLUGIN_VERSION=0.0.1-stale`, then call `serve.sh`
  with normal env. Assert: serve.sh exits 0, the stale pid is gone, exactly one
  listener remains, and `/api/health` reports the real manifest version (read
  from `.claude-plugin/plugin.json`, not hard-coded, so it survives version
  bumps).

### Part 2 — recast confirmation modal

All changes live inside the self-contained `daily-lesson-modes:v1` block of
`assets/lesson-shell.html` (frozen canon; design stays in the shell). No new
`{{TOKEN}}`, no escaping change, no new network call — it gates the existing
`/api/recast` path.

- Add a native `<dialog>` (focus-trap, Esc, backdrop for free; zero deps),
  styled with the existing CSS variables, hidden until shown.
- Wrap the generate button handler: `genBtn` click → `confirmThenGenerate(a)`.
  - If `lsGet('dlm-recast-skip-confirm') === '1'` → call `generate(a)` directly.
  - Else populate the dialog with the tone label and `showModal()`.
- Modal copy (usage + local + time, honest about all three):
  > **Generate the {Tone} version?**
  > This runs your local `claude` to rewrite this lesson in the **{Tone}** tone.
  > It can take up to a minute and counts against your Claude usage, like a chat
  > turn. The new tone is saved next to this lesson — nothing leaves your machine.
  > ☐ Don't ask again
  > [Cancel] [Generate]
- **Generate** → if "Don't ask again" checked, `lsSet('dlm-recast-skip-confirm','1')`
  and reveal the reset affordance; close dialog; call `generate(a)`.
- **Cancel / Esc / backdrop** → close, no-op.
- The tone label is injected via `textContent` (escape-first), consistent with
  the existing chip/genBtn code — never `innerHTML`.

**Reset affordance** (user requested a way to re-enable):

- Add a muted `<button class="dlm-reset" hidden>` to the modes bar (`#dlm-bar`),
  text e.g. "Always ask before generating".
- Shown only when `dlm-recast-skip-confirm === '1'` (checked on bar init and set
  when the user opts out). Clicking removes the key and re-hides itself.
- Lives in the bar (not the modal) because the modal is exactly what's
  suppressed; the bar is where the user will look.

The preference is per-origin (all lessons share `http://127.0.0.1:PORT`), so
"Don't ask again" is global across lessons — the intended behaviour.

**Tests**

- `tests/e2e/specs/modes.spec.js` (Playwright, mock backend): clicking generate
  shows the dialog; Cancel issues no `/api/recast`; Generate proceeds to recast;
  with "Don't ask again" checked, a subsequent generate skips the dialog and the
  reset button appears; clicking reset brings the dialog back next time.

## Release

After both parts land and all tests pass, bump the version in lockstep in
`.claude-plugin/plugin.json` and the `daily-lesson` entry of
`.claude-plugin/marketplace.json` (`0.4.0 → 0.4.1`) — a patch: bug-fix
(resilience) plus a small UX guardrail, no breaking change to the render/token
contract. README gets a one-line note that the server auto-replaces a stale
instance after an update.

## Out of scope / non-goals

- No change to `render_lesson.py`, the `{{TOKEN}}` contract, escaping, exit
  codes, the ledger, or path-safety logic.
- No new network egress; recast still calls the local `claude` only.
- No per-lesson confirmation preference (global is intended).
- No server-side `/api/shutdown` endpoint (kill stays in the launcher to avoid
  adding a remotely-triggerable shutdown surface).

## Invariants honored

Frozen-template split (design stays in `assets/*.html`); `{{TOKEN}}` contract
untouched; escaping rules untouched; exit-code contract untouched; local-only /
privacy promise untouched (no new egress); manifests bumped in lockstep.
