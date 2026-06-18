---
description: Re-render an existing lesson in a different lecture mode (tone + depth) and persist it as a sibling lesson — the same concept, an alternate voice, retrievable just like the original.
allowed-tools: Bash, Read, Write, Glob, Grep
argument-hint: "<mode: tutorial|grounded|deep|briefing> [which lesson: id, slug, or words from the title — default = most recent]"
---

# Lesson Recast — the same lesson, in another voice

You take a lesson I already have and re-express its **same concept** in a
different **mode** (tone + depth), then persist that rendition as its own
retrievable lesson **alongside** the original — not replacing it. The library
groups the tones under one concept, so afterward I can open "this concept, in
Grounded" or "…in Tutorial" and pick whichever I want.

You do **not** mine my sessions here. The source is the existing lesson itself:
you read what it already teaches and re-voice it. This keeps the concept and the
facts identical, costs nothing in transcript reads, and stays fully local.

Argument: `$ARGUMENTS`
- **First token = the target mode** (a canonical key or alias from
  `references/lesson-modes.md`). Required.
- **Rest (optional) = which lesson** to recast — an `id`, a `slug`, or a few
  words from the title. If omitted, recast my **most recent** lesson.

---

## Step 0 — Resolve helpers, the library, and the arguments

The lesson library lives at `~/.claude/daily-lessons/` with the ledger at
`~/.claude/daily-lessons/index.json` and pages under `lessons/`. Resolve the
renderer and the chat launcher exactly as `/daily-lesson` does:

```bash
RENDER="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/render_lesson.py}"
[ -f "$RENDER" ] || RENDER="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/render_lesson.py' 2>/dev/null | sort -V | tail -1)"
SERVE="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/serve.sh}"
[ -f "$SERVE" ] || SERVE="$(find "$HOME/.claude/plugins/cache" -path '*daily-lesson*/scripts/serve.sh' 2>/dev/null | sort -V | tail -1)"
LEDGER="$HOME/.claude/daily-lessons/index.json"
```

If `$RENDER` is empty/not a file, **stop** — the install is broken; say which
path you looked for. If `$LEDGER` doesn't exist or the ledger is empty, **stop**
and tell me there are no lessons to recast yet (run `/daily-lesson` first).

Parse `$ARGUMENTS`:
1. **Mode.** Lower-case the first token and normalise it to a canonical key
   (`grounded`/`tutorial`/`deep`/`briefing`) via the alias table in
   `${CLAUDE_PLUGIN_ROOT}/references/lesson-modes.md`. If it isn't a recognised
   mode, **stop** and print the four modes + aliases — don't guess.
2. **Target selector.** Whatever remains after the mode token (may be empty).

---

## Step 1 — Resolve the target concept and check the tone is free

Read `index.json`. First **collapse records by `concept_key`** — each concept
has one **primary** rendition (the first record with that `concept_key`; it has
no `variant_of`) plus any alternate-tone renditions. You resolve a *concept*, not
a single record:

- **No selector** → the concept of the **most recent** record (last entry).
- **A selector** → match by `id`, `slug`, or a substring of `title`
  (case-insensitive) and resolve to that record's concept. If several concepts
  match, pick the most recently taught and note the others you skipped. If
  nothing matches, **stop** and list my few most recent lessons (title + slug) so
  I can retry.

Keep the primary's `concept_key`, `slug`, `title`, `one_liner`, `source_day`, and
`tags` — the recast reuses them unchanged.

**Refuse a duplicate tone.** If any record for this `concept_key` already has
`mode` equal to the target mode (treat a record with no `mode` as the original
tone), **stop**: tell me that tone already exists, name its file, and list the
modes still available for this concept. Recasting only makes a tone I don't have.

---

## Step 2 — Read the original rendition (recover the substance)

Open the **primary** rendition's HTML file — its path is the primary record's
`file` field under `~/.claude/daily-lessons/` (e.g.
`~/.claude/daily-lessons/lessons/2026-06-15-erc7201.html`) — and read it.
Recover, from the rendered article, everything you need to teach the
**same** concept again: the definition, the mental model, the worked example and
its real language, the pitfalls, the self-check, and any honest reference to what
happened in my session. The ledger record gives you the title, slug,
`concept_key`, `source_day`, and tags; the HTML gives you the content.

Do not invent new facts or new session events, and do not change the concept —
this is a re-voicing of an existing lesson, not a new one.

---

## Step 3 — Re-author the body in the target mode

Read `${CLAUDE_PLUGIN_ROOT}/references/lesson-modes.md` and write the lesson in
the **target mode**: its tone, framing, second-person policy, and length target
(Grounded ~600–900 · Tutorial ~650–950 · Deep Dive ~1000–1500 · Briefing
~350–600). Keep the six-section structure and the canonical body components from
`references/lesson-format.md` (you are authoring only the body fragment — the
shell is frozen).

- **Compressing** (e.g. → Briefing): keep every section complete; cut narrative
  connective tissue, never the worked example or the definition.
- **Expanding** (e.g. → Deep Dive): you may add depth about the concept from
  general expertise — a second worked example, edge cases, the derivation — but
  the facts about *my* session and the concept must stay exactly as the original
  had them. Never fabricate.

Both floors bind this rendition, the same as a fresh lesson:
- **Clarity floor** — define-first, lead with the point, the example never
  disappears, correctness beats flourish.
- **Attribution rule** — `you` only for what *I* genuinely did or decided; the
  agent's/tooling's work is third-person, actor named. If the original lesson
  attributes an action to "you" but you can't verify from it that *I* (not the
  agent) did it, switch to the impersonal/agent voice — recasting is a good
  moment to **fix** a legacy lesson's mis-attribution, never to copy it forward.

---

## Step 4 — Render the variant through the canonical pipeline

Write the two inputs, then call the renderer with **`--variant`** (which dedups
on `concept_key` + `mode`, writes a mode-suffixed file, and links it to the
primary):

1. `/tmp/daily-lesson-meta.json` — reuse the concept's `slug`, `concept_key`,
   `title`, `source_day`, and `tags`; you may re-voice `dek` and `one_liner` to
   fit the tone; set `taught_at` to **now** as ISO 8601 with a colon in the
   offset — portable via `python3 -c "import datetime; print(datetime.datetime.now().astimezone().isoformat(timespec='seconds'))"`
   (macOS `date` has no `%:z`); set `mode` to the **canonical target key**.
2. `/tmp/daily-lesson-body.html` — the body fragment from Step 3.

```bash
python3 "$RENDER" --variant --meta /tmp/daily-lesson-meta.json --body /tmp/daily-lesson-body.html
```

Exit codes: `0` ok · `2` bad/missing meta, missing `mode`, or `--variant` of an
unknown `concept_key` (fix and retry) · `3` this concept already has that tone
(you missed it in Step 1 — stop and tell me) · `4` templates missing (broken
install). On `0`, the renderer prints JSON `{ok, title, lesson_number, file,
path, word_count, mode, variant_of}` — `lesson_number` is the **shared** number
of the concept, and `variant_of` points at the primary. The library is
regenerated automatically with the tones grouped under the concept.

---

## Step 5 — Open the new rendition live and report

Bring the chat server up and open the new rendition through it, exactly like
`/daily-lesson` Step 7 (so its chat is live immediately):

```bash
BASE="$(sh "$SERVE" 2>/tmp/daily-lesson-serve.err)"   # e.g. http://127.0.0.1:8787
```

- If `$BASE` came back, open `"$BASE/<file>?chat=1"` (the `file` the renderer
  returned). If `serve.sh` failed, fall back to opening the plain file at
  `~/.claude/daily-lessons/<file>` and say why (tail `/tmp/daily-lesson-serve.err`).

Then print, briefly:
- which lesson you recast (title) and **into which mode**,
- the served URL of the new rendition,
- that the original tone is untouched and both now live under the same concept in
  the library (so I can switch tones from there),
- the other modes still available for this concept, if any.

---

## Hard rules

- **Never mine my sessions here.** The only source is the existing lesson page;
  recast re-voices it. No transcript reads, no new concepts.
- **Never change the concept or the facts.** Same `concept_key`, same `slug`,
  same `source_day`. You change tone and depth, not truth.
- **Never overwrite the original.** `--variant` writes a mode-suffixed file; the
  primary rendition stays exactly as it was.
- **Never reproduce the page chrome.** Author only `meta.json` + the body
  fragment; the frozen shell owns the rest.
- **Honour the target mode and both floors** (`references/lesson-modes.md`):
  never obscure, never credit me with the agent's work — and prefer to *fix* a
  legacy lesson's mis-attribution while you're recasting it.
- One concept per recast; refuse a tone the concept already has.
