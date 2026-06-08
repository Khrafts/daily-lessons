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

## Step 5 — Render an interactive HTML lesson

Write a **single self-contained** HTML file to
`~/.claude/daily-lessons/lessons/YYYY-MM-DD-<slug>.html`. It must open directly
via `file://` with no build step or local server.

Design:
- Minimalist black-and-white aesthetic, generous whitespace, a comfortable
  max-width reading column. **Fraunces** for headings, **JetBrains Mono** for
  code (load via Google Fonts `<link>` with sensible system fallbacks).
- A top metadata bar: lesson number (`#N`), today's date, the source session
  day, and topic tags.
- Syntax-highlighted code blocks, each with a **copy** button. You may pull a
  highlighter from a CDN (e.g. highlight.js) but the page must still read fine
  if the CDN is unreachable.
- Make it *interactive*, not just styled: collapsible **Pitfalls** sections and
  a flip-card or reveal-on-click **Self-check** so answers stay hidden until I
  ask. A "← Library" link back to `index.html`.

Implementation note: inline all CSS, and keep the page's runtime interactivity
in **minimal vanilla browser JavaScript** — this is the single allowed JS
exception, because a `file://` page can't run TypeScript without a build. The
*teaching* code samples follow Step 4's language rule.

---

## Step 6 — Update the ledger and regenerate the library

Append a record to `index.json`:

```json
{
  "id": "2026-06-07-001",
  "slug": "eip712-typed-data-signing",
  "concept_key": "evm-eip712-typed-data",
  "title": "EIP-712: Why Your Signatures Are Structured",
  "one_liner": "Human-readable typed-data signing and how wallets verify it.",
  "source_day": "2026-06-03",
  "taught_at": "2026-06-07T09:14:00+01:00",
  "tags": ["evm", "signatures", "security"],
  "file": "lessons/2026-06-07-eip712-typed-data-signing.html",
  "word_count": 940
}
```

Keep `index.json` as a JSON array; create it as `[]` if absent. `concept_key` is
the dedup key — normalize it (lowercase, hyphenated, domain-prefixed) and never
emit a concept whose key already exists.

Then **regenerate** `~/.claude/daily-lessons/index.html` from the full ledger: a
clean, same-aesthetic library that lists every lesson (newest first) with title,
one-liner, date, tags, and a link to each HTML file. Show a running total
("Lesson 12 of an ever-growing pile").

---

## Step 7 — Report back to the terminal

When done, print:
- the lesson **title**,
- a **2-sentence teaser**,
- the saved HTML **file path**, and
- the exact command to view it: `open ~/.claude/daily-lessons/lessons/<file>.html`
  (on Linux, `xdg-open`; adapt to my platform).
- you could immediately run that command to open the lesson in my default browser.

Then ask if I want you to run that `open` command now. If there was no
meaningful activity, or nothing new left to teach, write nothing and just say so
in one line.

---

## Hard rules

- Never teach a `concept_key` already in `index.json`.
- Never fabricate session activity; if it's thin, say so.
- Never echo secrets, keys, tokens, or proprietary code from my sessions.
- Teaching code is the session's language (or the concept's native language),
  never plain JS where TypeScript fits.
- One concept per run. Depth over breadth. Fun over dry — but never at the cost
  of being correct.
