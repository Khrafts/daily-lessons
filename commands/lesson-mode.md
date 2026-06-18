---
description: Show or set the lecture mode for my daily lessons — the tone and depth each lesson is written in. No lesson is generated; this only changes a saved preference.
allowed-tools: Bash, Read
argument-hint: "[a mode: grounded | tutorial | deep | briefing — or empty to show the current mode and the menu]"
---

# Lesson Mode — choose the voice and depth of my lessons

You set my **lecture mode**: the tone and depth every future `/daily-lesson` is
written in. Same six sections, same frozen HTML, same one-concept-from-my-real-
session soul — only the voice and the depth of exposure change. This command
**never** mines sessions, calls a model, or writes a lesson; it only reads and
writes one small preference file. Do it quickly and locally.

The preference lives at `~/.claude/daily-lessons/config.json` (a JSON object;
`mode` is the key you touch — leave any other keys alone). The authoritative
definitions of every mode, the alias table, and the two floors that bind them
all live in `${CLAUDE_PLUGIN_ROOT}/references/lesson-modes.md`.

Optional argument: `$ARGUMENTS`
- A **mode name or alias** → set it as my default and confirm.
- Empty, or `show` / `status` / `list` → show my current mode and the menu.
- `default` / `reset` → set it back to `grounded`.

---

## The modes (canonical keys, default first)

| Key        | Display    | In one line                                                        | Aliases |
|------------|------------|--------------------------------------------------------------------|---------|
| `grounded` | Grounded ⭐ | Calm, senior-colleague voice; teaches the concept and cites my real session as honestly-attributed evidence. **Recommended default.** | `default`, `standard`, `balanced` |
| `tutorial` | Tutorial   | A calm, blog-style explainer; my session is the silent reason the topic was picked, not a story I star in. | `explainer`, `blog`, `docs` |
| `deep`     | Deep Dive  | Reference-grade and long; full derivation, edge cases, two worked examples — for when I want to truly master it. | `deep-dive`, `deepdive`, `deep_dive`, `reference` |
| `briefing` | Briefing   | A terse staff-engineer memo; maximum signal per word, the concept and the episode as facts, zero ornament. | `brief`, `memo`, `refresher` |

All four obey the **clarity floor** (tone never makes a lesson obscure) and the
**attribution rule** (only *my* genuine actions get "you"; the agent's work is
named in the third person). Those are floors, not modes — they apply no matter
what I pick.

---

## Step 0 — Resolve the config path

```bash
DIR="$HOME/.claude/daily-lessons"
CONFIG="$DIR/config.json"
mkdir -p "$DIR"
```

(The library dir is created if absent so the first `/lesson-mode` works on a
fresh install.)

---

## Step 1 — Normalise the argument

Lower-case the first token of `$ARGUMENTS` and map it to a **canonical key** via
the alias table above (`default`/`reset` → `grounded`). Three outcomes:

- **Empty / `show` / `status` / `list`** → go to Step 2 (show), don't write.
- **Resolves to a canonical key** → go to Step 3 (set).
- **Non-empty but unrecognised** → don't write anything. Tell me it wasn't a
  known mode, print the four keys and their aliases, and stop cleanly.

---

## Step 2 — Show the current mode (no write)

Read the saved mode, defaulting to `grounded` when the file is missing,
unreadable, or has no recognised `mode`:

```bash
python3 - "$CONFIG" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); mode = "grounded"
if p.is_file():
    try:
        c = json.loads(p.read_text() or "{}")
        if isinstance(c, dict) and c.get("mode"): mode = c["mode"]
    except Exception: pass
print(mode)
PY
```

Then print, plainly: my **current mode** (mark it `(default)` if no file/key set
it), the **menu** of all four modes with their one-liners from the table above,
the note that **Grounded is the recommended default**, and how to change it
(`/lesson-mode tutorial`). One screen, no fluff. Done.

---

## Step 3 — Set the mode (merge-write, preserve other keys)

Write the **canonical key** (never an alias) into `config.json`, preserving any
other keys already there:

```bash
python3 - "$CONFIG" "$KEY" <<'PY'
import json, pathlib, sys
p, key = pathlib.Path(sys.argv[1]), sys.argv[2]
cfg = {}
if p.is_file():
    try:
        cfg = json.loads(p.read_text() or "{}")
        if not isinstance(cfg, dict): cfg = {}
    except Exception: cfg = {}
cfg["mode"] = key
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(cfg))
PY
```

(`$KEY` is the canonical key from Step 1.) Then confirm in one or two lines: the
mode is now **<Display name>**, a one-line description of what that changes, and
that it takes effect on my **next** `/daily-lesson` (or right now with a one-off,
e.g. `/daily-lesson deep`). Don't regenerate or re-skin anything.

---

## Hard rules

- **Never write a lesson or mine sessions here.** This command only reads/writes
  `config.json`. It must be instant and burn no model tokens beyond your own
  reasoning.
- **Only ever touch the `mode` key.** Merge-write so any other keys in
  `config.json` survive untouched.
- **Always write the canonical key**, never an alias — `/daily-lesson` and the
  renderer expect `grounded` / `tutorial` / `deep` / `briefing`.
- **An unrecognised mode is not an error to crash on** — show the valid options
  and leave the saved preference exactly as it was.
- If `python3` is missing, say so and point at the same install hint
  `/lesson-chat` uses (`brew install python3` / `sudo apt install python3`).
