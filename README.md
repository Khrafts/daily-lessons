# Daily Lesson

> A personal tutor for Claude Code. It mines **your own** session history, finds **one** concept you leaned on but probably don't fully understand, and teaches it back to you — as a self-contained, interactive HTML lesson you open in your browser.

Every run picks a fresh concept (it keeps a ledger so it never repeats itself), grounds the lesson in what *you actually did*, and builds a small library of black-and-white, beautifully typeset lessons over time.

**Lesson generation runs entirely on your machine** — it reads your transcripts under `~/.claude/`, writes HTML to `~/.claude/daily-lessons/`, and uploads nothing. The optional per-lesson chat answers through your local `claude` CLI, so it makes the same network calls any Claude Code session does — under your own account, no API key, and nothing more.

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
/daily-lesson deep            # one-off: write just this lesson in a chosen mode
/lesson-mode                  # show the current lecture mode and the menu
/lesson-mode tutorial         # set the default mode for future lessons
```

When it finishes it prints the lesson title, a teaser, and the path to the HTML
file — then offers to open it in your browser.

---

## What you get

- **One concept per run**, chosen from things you *used but treated as a black box* — a copied command, a config you didn't question, a spot where you trial-and-errored.
- **Pitched at your stack.** It infers your languages, frameworks, and domain from the sessions themselves, so the worked example is in *your* world (Solidity, Rust, TypeScript, Go, Python — whatever you actually work in).
- **An interactive HTML lesson** — copy-able code blocks, collapsible pitfalls, reveal-on-click self-check questions, Fraunces + JetBrains Mono typography. Rendered from a **frozen canonical template**, so the design is identical on every install.
- **A growing library** at `~/.claude/daily-lessons/index.html`, newest first.
- **A chat on every lesson.** An **Ask about this lesson** button on each page —
  ask follow-ups and get answers grounded in that lesson, powered by your own
  `claude` CLI.

Each lesson covers: what it is → why it mattered in *your* session → the mental
model → a worked example → common pitfalls → go-deeper pointers + a self-check.

---

## Lesson modes — pick the voice and depth

The same lesson can be written in different **modes**. They share the six
sections, the frozen HTML, and the one-concept-from-your-real-session soul — only
the **tone** and the **depth of exposure** change, so you read in the register
you actually want.

| Mode | What it reads like | Depth |
|------|--------------------|-------|
| **Grounded** ⭐ | A senior colleague at a whiteboard — teaches the concept and cites your real session as evidence, honestly attributed. | standard (~600–900w) |
| **Tutorial** | A calm, blog-style explainer; your session is the silent reason the topic was picked, not a story you star in. | standard (~650–950w) |
| **Deep Dive** | A reference chapter — full derivation, edge cases, two worked examples; for when you want to truly master it. | long (~1000–1500w) |
| **Briefing** | A terse staff-engineer memo — maximum signal per word, the concept and the episode as facts, zero ornament. | compact (~350–600w) |

```
/lesson-mode                  # show your current mode and the menu
/lesson-mode deep             # set the default for future lessons
/daily-lesson briefing        # …or use a mode just once, without changing the default
```

**Grounded is the default** — it's the safest voice for a daily habit: it keeps
the lesson tied to *your* day without dramatising it. **Tutorial** drops the
session framing entirely if you'd rather read a clean concept explainer;
**Deep Dive** and **Briefing** flex the depth.

Two guarantees bind **every** mode, the default included:

- **Never obscure** — whatever the tone, the concept is defined plainly and leads
  every section; voice is seasoning on a clear explanation, never a substitute.
- **Honest attribution** — a lesson says "you" only for what *you* genuinely did
  or decided. Work the **agent or tooling** did is named in the third person, so
  a lesson never credits you with a command the agent ran.

Your choice is saved in `~/.claude/daily-lessons/config.json`; mode definitions
are canon in `references/lesson-modes.md` (edit there to retune a mode).

---

## Chat with your lessons

Every lesson page has an **Ask about this lesson** button, and it works with
**zero setup**: `/daily-lesson` opens each new lesson through a tiny local
server, so the chat is live the moment the page loads — no extra command to run.

Start a conversation about a lesson, close the tab, come back days later and
**continue** it where you left off. Continuity is real: each chat resumes the
same `claude` session (`--resume`), and the transcript is saved to `chats.json`
next to the lessons.

Each lesson can hold **more than one** conversation. Start a new chat without
losing the old ones — the drawer's history lets you browse a lesson's past chats
and switch between them, each with its own thread and session. Want more room to
read? **Expand** widens the drawer into a centered reading column, and it
remembers the choice.

Answers come from the **local `claude` CLI** — your existing login and
subscription, no API key. Still local-first: the only network calls are the
ones `claude` itself makes, exactly like any other session.

Want the whole library in one place, or need to bring the server back after a
reboot? Run:

```
/lesson-chat                  # ensure the server is up, open the library
/lesson-chat 9000             # same, on a different port
```

It serves your library at `http://127.0.0.1:8787` (loopback only — nothing is
exposed to the network). The launcher is idempotent: it reuses a running server
and only starts one if needed. Lessons opened directly via `file://` show the
button too — if the server is running, the button deep-links into the served
page; if not, it tells you how to start it. Lessons rendered before this feature
gain the chat button automatically when viewed through the server.

---

## Where things live

```
~/.claude/projects/                          # your session transcripts (read-only input)
~/.claude/daily-lessons/
├── index.json                               # the ledger (dedup source of truth)
├── index.html                               # the library landing page
├── config.json                              # preferences (e.g. your lecture mode)
├── chats.json                               # per-lesson chat transcripts + session ids
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
- The `claude` CLI on your PATH — chat only. Already true if you're running this as a plugin.
- Some actual Claude Code history to learn from. Fresh installs with no sessions yet will be told there's nothing to teach.

---

## Privacy

Everything happens on your machine. The command reads your local transcripts and
writes local HTML; nothing is uploaded. Chat answers are generated by your local
`claude` CLI under your own account, and transcripts stay in `chats.json` on
disk. The lesson author is instructed to teach
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
