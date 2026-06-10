---
description: Scan recent Claude Code sessions and teach me one thing I relied on but probably don't fully understand. Renders an interactive HTML lesson.
allowed-tools: Bash, Read, Write, Glob, Grep
argument-hint: "[optional YYYY-MM-DD to target a specific day, or 'back' to skip the most recent day]"
---

# Daily Lesson — learn from my own Claude Code sessions

You are my personal tutor. Each time you run, you mine my recent Claude Code
activity, find **one** concept I leaned on without truly understanding, and
teach it to me properly — with depth, a worked example in **my** stack, and a
bit of personality — then render it as a self-contained interactive HTML page I
can open in a browser. This runs entirely locally on my machine.

Optional argument: `$ARGUMENTS`
- If it's a date like `2026-06-03`, target that day specifically.
- If it's `back`, skip the most recent day and start one day earlier.
- If empty, start from the most recent day with activity.

---

## Step 0 — Locate sources and fail loudly if you can't

- Session transcripts live at `~/.claude/projects/`. That directory contains
  one subfolder per project (named after the encoded working directory), and
  each subfolder holds `.jsonl` session logs. Every line is a JSON event with a
  `timestamp` (ISO 8601), a `type` (`user` / `assistant` / etc.), and message
  content that includes text and `tool_use` / `tool_result` blocks (Bash
  commands, file reads/edits, errors, and so on).
- The lesson library lives at `~/.claude/daily-lessons/`:
  - `~/.claude/daily-lessons/index.json` — the ledger (dedup source of truth).
  - `~/.claude/daily-lessons/lessons/YYYY-MM-DD-<slug>.html` — one file per lesson.
  - `~/.claude/daily-lessons/index.html` — the regenerated library landing page.

If `~/.claude/projects/` is missing or unreadable, **stop immediately** and tell
me exactly what blocked you (the path, the shell error, and the likely fix —
e.g. permissions, wrong home dir, or Claude Code storing logs elsewhere). Do not
guess or fabricate activity. Create `~/.claude/daily-lessons/` and its `lessons/`
subfolder if they don't exist yet.

**Implementation note (paths with leading dashes):** the project subfolders are
named like `-Users-you-Work-repo`, which shells parse as command flags. Prefix
paths with `./` (or use input redirection `< "$f"`) so tools like `head`, `jq`,
and `cat` don't choke. Timestamps carry milliseconds (`...387Z`), which
`fromdateiso8601` rejects — strip them first, e.g.
`sub("\\.[0-9]+Z$";"Z")`. To bucket by **local** day, add your UTC offset in
seconds before formatting (jq's `strftime` is UTC-only).

---

## Step 1 — Read the sessions

Bucket events by **local calendar day** using each line's `timestamp`. For the
target day, parse the `.jsonl` files across all projects and extract a working
picture of what I did: the tools/CLIs invoked, libraries and packages touched,
languages and frameworks, errors I hit, patterns I copied, and questions I
asked. Favour signal over noise — skip trivial file navigation.

**Skip meta-sessions.** If the most recent day's only activity is the very
session that runs this command (or other Claude-Code-about-Claude-Code
housekeeping), that's not teachable signal — fall through to the most recent day
of substantive work and say so when you report back.

**Privacy:** sessions may contain secrets, keys, tokens, addresses, or private
code. Teach the *general concept*, never echo a secret or proprietary snippet
verbatim. Reconstruct examples from scratch.

---

## Step 2 — Pick the target day (with back-walking)

1. Determine the starting day: the argument if given, else the most recent day
   that has session activity (apply `back` by stepping one day earlier).
2. Load `index.json` and read every `concept_key` already taught.
3. Derive candidate concepts for the target day (Step 3), then drop any whose
   `concept_key` is already in the ledger.
4. If the target day has **no untaught candidates left**, walk back one day and
   repeat — keep going until you find a day with at least one fresh concept, or
   you run out of history.
5. If you exhaust all history with nothing new, write nothing, say so plainly,
   and optionally point me at the single most worthwhile past lesson to revisit.

This back-walking is also what makes repeat runs work: the first run indexes its
pick, so a second run the same day automatically lands on a different concept.

---

## Step 3 — Infer candidate concepts

From the target day's sessions, infer the main topics, tools, libraries, and
concepts. Then build a shortlist of things I **used or relied on but probably do
NOT fully understand**. Strong candidates:

- something I leaned on without ever explaining it,
- a command, config, or snippet I copied without questioning,
- a spot where I was clearly confused, hit an error, or trial-and-errored,
- a tool or pattern I used heavily but treated as a black box.

It doesn't have to be a deep CS concept — a sharp tip, idiom, or better pattern
counts if it would genuinely upgrade how I work. Skip anything I obviously
already know cold. Pick **exactly one** `concept_key`.

---

## Step 4 — Write the lesson (depth first, fun second)

Audience: me — an experienced engineer. **Infer my actual stack, languages, and
domain from the sessions themselves** (what I import, the frameworks and CLIs I
run, the kinds of problems I debug) and pitch the lesson to *that*. Don't assume
a domain — let the transcripts tell you who you're teaching, then meet me at my
level and do not dumb it down.

Target ~600–900 words, but **go longer when the concept earns it**; never
sacrifice depth for the word count.

Make it genuinely engaging: a sharp mental model, a vivid analogy or two, a
confident voice. Fun is the delivery, not a discount on rigor.

Cover, in order:

1. **What it is** — a crisp, correct definition.
2. **Why it mattered today** — tie it directly to what I actually did in the
   session (reference the real task, not a generic stand-in).
3. **The mental model** — the one picture that makes it click.
4. **A worked example** — concrete, runnable-in-spirit, grounded in today's
   work. Write teaching code in **the language the session actually used** (or
   the concept's native language — e.g. Solidity, Rust, Go, Python, TypeScript).
   Never use plain JavaScript where TypeScript would fit.
5. **2–3 common pitfalls** — the traps that bite people, ideally ones I was
   near today.
6. **Go deeper** — a couple of authoritative pointers and a 2–3 question
   self-check to test understanding.

---

## Step 5 — Render the lesson through the canonical pipeline

**Do not hand-write the HTML.** The entire look-and-feel — layout, CSS, fonts,
the metadata bar, copy buttons, collapsible pitfalls, reveal-on-click self-check,
and the library page — is frozen canon in the plugin's `assets/` shells and
assembled by `scripts/render_lesson.py`. Authoring the page yourself would make
every machine's output drift; the renderer guarantees it never does. Your job is
the *content* only.

First read the component contract — it's short and exact:
`${CLAUDE_PLUGIN_ROOT}/references/lesson-format.md`. Then:

1. Write **`/tmp/daily-lesson-meta.json`** — `title`, `dek` (the italic subtitle;
   inline HTML like `<code>` is allowed), `one_liner`, `slug`, `concept_key`,
   `source_day`, `taught_at`, `tags`. (`title` and `one_liner` are plain text —
   the renderer HTML-escapes them.)
2. Write **`/tmp/daily-lesson-body.html`** — the inner article only: the six
   sections (`<h2><span class="h2n">01</span> …` through `06`) followed by the
   `.checks` self-check. Use ONLY the canonical components from the reference:
   `<figure class="code">` blocks (code at column 0, with `<`/`>`/`&` escaped and
   `class="language-xxx"`), `<details class="pit">` pitfalls, `<blockquote>`, and
   the self-check cards. No `<head>`, CSS, `<script>`, `<hr>`, or footer — the
   shell owns all of that.
3. Resolve the renderer and run it:
   ```bash
   RENDER="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/render_lesson.py}"
   [ -f "$RENDER" ] || RENDER="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/render_lesson.py' 2>/dev/null | sort -V | tail -1)"
   python3 "$RENDER" --meta /tmp/daily-lesson-meta.json --body /tmp/daily-lesson-body.html
   ```
   It writes `~/.claude/daily-lessons/lessons/<date>-<slug>.html`, appends the
   ledger entry, and regenerates the library — deterministically — then prints
   JSON `{ok, title, lesson_number, file, path, word_count}` for Step 7.

Exit codes to handle: `0` ok · `2` bad/missing meta fields (fix, retry) · `3` the
`concept_key` is already taught (go back to Step 2/3 and pick another) · `4`
templates missing (the plugin install is broken — tell me).

---

## Step 6 — (the renderer already did this)

Running the renderer in Step 5 appended the `index.json` ledger record
(`concept_key` is the dedup key — it refuses duplicates) and regenerated
`~/.claude/daily-lessons/index.html` from the full ledger, newest first. There is
nothing to update by hand. If you've edited a shell in `assets/` and want to
re-skin the existing library, run `python3 "$RENDER" --rebuild-library`.

---

## Step 7 — Bring up the chat server and open the lesson *live*

Open the lesson **through the local chat server**, not as a bare `file://`, so
its "Ask about this lesson" chat is live the instant the page loads — no
separate `/lesson-chat` step. The server is idempotent: `serve.sh` reuses a
healthy instance and only starts one if needed, so this is safe to run every
time.

Resolve `serve.sh` the same way you resolved the renderer in Step 5, then ask
it to ensure the server is up. It prints the base URL on success:

```bash
SERVE="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/serve.sh}"
[ -f "$SERVE" ] || SERVE="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/serve.sh' 2>/dev/null | sort -V | tail -1)"
BASE="$(sh "$SERVE" 2>/tmp/daily-lesson-serve.err)"   # e.g. http://127.0.0.1:8787
```

- **If `$BASE` came back** (exit 0): the served lesson URL is
  `$BASE/<file>` where `<file>` is the `file` field the renderer returned
  (e.g. `lessons/2026-06-10-rpc-url-trust-base.html`). Open
  `"$BASE/<file>?chat=1"` in my browser (`open` on macOS, `xdg-open` on Linux;
  adapt to my platform) — the `?chat=1` makes the chat drawer open on arrival.
- **If `serve.sh` failed** (non-empty stderr, no URL — e.g. `python3` missing or
  the port is taken): fall back to the plain file — open
  `~/.claude/daily-lessons/lessons/<file>.html`. The chat button still appears;
  it will just show how to start the server. Mention the fallback and the
  reason (tail `/tmp/daily-lesson-serve.err`).

Then print:
- the lesson **title**,
- a **2-sentence teaser**,
- the **served URL** I can revisit (`$BASE/<file>`), and a note that chat is
  live there — same login, plan, and model as my normal sessions.

You may run the `open` command for me right away. If there was no meaningful
activity, or nothing new left to teach, write nothing and just say so in one
line (and don't bother starting the server).

---

## Hard rules

- **Never reproduce or restyle the page chrome.** The HTML shell, CSS, and JS are
  canon in the plugin's `assets/`, assembled by `render_lesson.py`. Author only
  `meta.json` + the body fragment. To change the design, edit the `assets/`
  shells — never inline a bespoke page.
- Never teach a `concept_key` already in `index.json`.
- Never fabricate session activity; if it's thin, say so.
- Never echo secrets, keys, tokens, or proprietary code from my sessions.
- Teaching code is the session's language (or the concept's native language),
  never plain JS where TypeScript fits.
- One concept per run. Depth over breadth. Fun over dry — but never at the cost
  of being correct.
