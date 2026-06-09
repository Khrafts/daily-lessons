# Daily Lesson

> A personal tutor for Claude Code. It mines **your own** session history, finds **one** concept you leaned on but probably don't fully understand, and teaches it back to you — as a self-contained, interactive HTML lesson you open in your browser.

Every run picks a fresh concept (it keeps a ledger so it never repeats itself), grounds the lesson in what *you actually did*, and builds a small library of black-and-white, beautifully typeset lessons over time.

**It runs entirely locally.** It reads your transcripts under `~/.claude/`, writes HTML to `~/.claude/daily-lessons/`, and never sends anything anywhere.

---

## Install

Inside Claude Code:

```
/plugin marketplace add Khrafts/daily-lessons
/plugin install daily-lesson@daily-lessons
```

That's it. The `/daily-lesson` command is now available.

> Prefer the menu? Run `/plugin`, pick **Browse marketplaces → daily-lessons → daily-lesson → Install**.

---

## Usage

```
/daily-lesson                 # teach me something from my most recent day of work
/daily-lesson 2026-06-03      # target a specific day (YYYY-MM-DD)
/daily-lesson back            # skip the most recent day, start one day earlier
```

When it finishes it prints the lesson title, a teaser, and the path to the HTML
file — then offers to open it in your browser.

---

## What you get

- **One concept per run**, chosen from things you *used but treated as a black box* — a copied command, a config you didn't question, a spot where you trial-and-errored.
- **Pitched at your stack.** It infers your languages, frameworks, and domain from the sessions themselves, so the worked example is in *your* world (Solidity, Rust, TypeScript, Go, Python — whatever you actually work in).
- **An interactive HTML lesson** — copy-able code blocks, collapsible pitfalls, reveal-on-click self-check questions, Fraunces + JetBrains Mono typography. Rendered from a **frozen canonical template**, so the design is identical on every install.
- **A growing library** at `~/.claude/daily-lessons/index.html`, newest first.

Each lesson covers: what it is → why it mattered in *your* session → the mental
model → a worked example → common pitfalls → go-deeper pointers + a self-check.

---

## Where things live

```
~/.claude/projects/                          # your session transcripts (read-only input)
~/.claude/daily-lessons/
├── index.json                               # the ledger (dedup source of truth)
├── index.html                               # the library landing page
└── lessons/
    └── YYYY-MM-DD-<slug>.html               # one self-contained lesson per run
```

The ledger's `concept_key` is the dedup key, so repeated runs always teach
something new and the same-day re-run lands on a different concept.

---

## Customizing the look

Every lesson is rendered from **frozen templates** bundled in the plugin, so the
typography, layout, and interactions are identical on every install — the design
is canon, not re-improvised each run:

```
assets/lesson-shell.html     # lesson page: <head>, CSS, JS, metadata bar, footer
assets/library-shell.html    # the library landing page
assets/library-row.html      # one library row
scripts/render_lesson.py     # slots your content into the shells (token replacement)
references/lesson-format.md  # the body component contract the command follows
```

The command authors only the *content* (a metadata blob + the article body) and
hands it to `render_lesson.py`, which assembles the page. Want a different look?
Edit the `assets/` shells — that's the whole point of the split. After editing,
re-skin the existing library with:

```
python3 scripts/render_lesson.py --rebuild-library
```

(Existing lesson *pages* are written once at creation; re-render them to re-skin
those too.)

---

## Requirements

- Claude Code with plugin support.
- `python3` (3.8+) — runs the renderer. Pre-installed on macOS and most Linux distros.
- A shell with `jq` available (used to parse the `.jsonl` transcripts). Pre-installed on most setups; on macOS, `brew install jq`.
- Some actual Claude Code history to learn from. Fresh installs with no sessions yet will be told there's nothing to teach.

---

## Privacy

Everything happens on your machine. The command reads your local transcripts and
writes local HTML; nothing is uploaded. The lesson author is instructed to teach
the *general concept* and never echo secrets, keys, tokens, addresses, or
proprietary code from your sessions. (The generated HTML does pull Google Fonts
and highlight.js from CDNs for styling, and degrades gracefully if you're
offline.)

---

## Uninstall

```
/plugin uninstall daily-lesson@daily-lessons
```

Your existing lessons under `~/.claude/daily-lessons/` are left untouched —
delete that folder by hand if you want them gone.

---

## License

MIT — see [LICENSE](./LICENSE).
