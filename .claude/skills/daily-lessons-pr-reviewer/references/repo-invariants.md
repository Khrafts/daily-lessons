# daily-lessons — repo invariants & review checklist

This is the knowledge that makes a review of **Khrafts/daily-lessons** worth more
than a generic code review. Read it before judging a diff. Every reviewer persona
shares this file; your persona prompt tells you which slice to weight most.

## What this repo is

`daily-lessons` is a single Claude Code **plugin** (published to a marketplace),
not an app or a service. It mines the user's local session transcripts, picks one
concept they leaned on without understanding, and renders it as a self-contained
interactive HTML lesson. The moving parts:

| Path | Role | Who edits it |
|------|------|--------------|
| `scripts/render_lesson.py` | The renderer. Slots authored content into frozen shells by literal `{{TOKEN}}` replacement; manages the ledger + library page. | maintainers |
| `assets/lesson-shell.html` | **Frozen** lesson-page chrome: `<head>`, all CSS, all JS, metadata bar, footer. | maintainers (rarely — this is "the canon") |
| `assets/library-shell.html` | **Frozen** library landing page chrome. | maintainers (rarely) |
| `assets/library-row.html` | **Frozen** one-row template for the library list. | maintainers (rarely) |
| `commands/daily-lesson.md` | The `/daily-lesson` slash command — the tutor instructions the model follows at runtime. | maintainers |
| `references/lesson-format.md` | The body-component contract the command must author against. | maintainers |
| `.claude-plugin/plugin.json` | Plugin manifest. | maintainers |
| `.claude-plugin/marketplace.json` | Marketplace manifest (lists the plugin). | maintainers |
| `README.md` | User-facing docs. | maintainers |

The runtime split is the soul of the project: **the command authors only content
(`meta.json` + `body.html`); the renderer assembles the page; the shells own all
design.** Most regressions worth catching are violations of that split or of the
renderer's data contract.

---

## The invariants (what a reviewer must protect)

### 1. The frozen-template / content–shell split

The whole reason this repo exists (see the commit `standardize lesson HTML via
frozen canonical templates`) is that lessons used to re-improvise their own HTML
and no two installs matched. Design now lives **only** in `assets/*.html`.

- ❌ Page chrome (CSS, `<script>`, `<head>`, nav, metadata bar, footer, the
  `<h1>`/dek structure) appearing inside `body.html`, inside `commands/daily-lesson.md`'s
  authored output, or hard-coded as Python strings in `render_lesson.py`.
- ❌ The command re-describing the design in prose instead of pointing at the
  shells / `references/lesson-format.md`.
- ✅ Design changes made by editing `assets/*.html` (changing "the canon" deliberately).
- A diff that moves styling out of the shells is an **architectural regression**
  even if the rendered page looks fine on the author's machine — it breaks the
  "identical on every install" guarantee.

### 2. `{{TOKEN}}` sync between shells and the renderer

The renderer fills the shells by literal string replacement. The tokens are a
contract — a token present on one side but not the other is a silent bug.

Current token inventory (keep this in sync if you review a change that touches it):

- `lesson-shell.html`: `{{N}}` `{{TAUGHT_DATE}}` `{{SOURCE_DAY}}` `{{TITLE}}` `{{TAGS}}` `{{DEK}}` `{{BODY}}`
- `library-shell.html`: `{{COUNT_LINE}}` `{{ROWS}}`
- `library-row.html`: `{{FILE}}` `{{N}}` `{{TAUGHT_DATE}}` `{{SOURCE_DAY}}` `{{TITLE}}` `{{ONE_LINER}}` `{{TAGS}}` `{{TONES}}`

Failure modes to flag:
- A new `{{FOO}}` added to a shell but never `.replace()`d → the literal text
  `{{FOO}}` ships onto the user's page.
- A `.replace("{{FOO}}", …)` added in Python with no matching token in the shell
  → silent no-op; the value never appears.
- Renaming a token on one side only.

### 3. Escaping: text fields are escaped, `dek`/`body` are raw **by design**

`render_lesson.py` has `esc()` (`html.escape(..., quote=False)`). The split is
deliberate and load-bearing:

- **Escaped** (plain text, author cannot inject HTML): `title`, `one_liner`,
  `tags`, `taught_date`, `source_day`, and the library `count_line`.
- **Raw HTML, intentionally NOT escaped**: `dek` (inline HTML like `<code>`,
  `<em>`) and `body` (the whole article fragment).

Flag both directions:
- A new author-facing **text** field interpolated **without** `esc()` → broken
  rendering / injection. (Inputs are local and author-controlled, so this is a
  correctness/robustness bug, not a remote-XSS bug — but still wrong: an
  ampersand or `<` in a title would mangle the page.)
- `esc()` newly wrapped around `dek` or `body` → breaks every lesson (the
  intended inline HTML and the entire article get double-escaped and shown as
  literal tags). This is a **Critical** rendering break.

### 4. The exit-code contract

`render_lesson.py` documents and the rest of the repo depends on:
`0` ok · `2` bad input · `3` duplicate `concept_key` · `4` missing template asset.

This contract is stated in **three places** — the script docstring,
`references/lesson-format.md` ("Exit codes: …"), and the README's behavior. A
change to the codes (or to what triggers them) must update all three, and the
command (`daily-lesson.md`) keys off exit `3` to retry with a different concept.
Flag drift.

### 5. Ledger & library integrity

`index.json` is the dedup source of truth and an append-ordered list. Watch for:
- **Dedup**: a new lesson is rejected (exit 3) if its `concept_key` already
  exists. Don't weaken or bypass this.
- **Sequence id** `id = "{taught_date}-{seq:03d}"`, where `seq` counts existing
  records whose id starts with that date, +1. Off-by-one or collision risks.
- **Lesson number** `n = len(ledger)` (chronological, 1-based).
- **Library ordering**: the page shows **newest first** (`reversed(numbered)`).
  A change that lists oldest-first, or renumbers existing lessons, is a regression.
- **Backward compatibility**: existing `index.json` files in the wild must still
  load. Adding a *required* field the renderer reads from old records, or
  changing the record shape without a fallback, breaks upgraders.

### 6. Path safety on the write path

`slug` and `taught_date` flow into `file_rel = f"lessons/{taught_date}-{slug}.html"`
and then to `out_path.write_text(...)`. A `slug` containing `/` or `..` would
write outside `lessons/`. The input is author/model-generated rather than
attacker-supplied, so weigh severity accordingly — but a renderer that will
happily write to `lessons/../../etc/whatever.html` is a real bug worth flagging,
especially if a diff starts accepting slugs from a less-trusted source.

### 7. Local-only / privacy — a hard promise

The README and both manifests promise the tool "runs entirely locally; nothing
leaves your machine," and the command is instructed never to echo secrets, keys,
tokens, addresses, or proprietary code from sessions. Treat as **Critical** any
diff that:
- adds network egress (HTTP client, telemetry, analytics, uploading transcripts
  or lessons anywhere) — note the *one* sanctioned exception already documented:
  the rendered HTML pulls Google Fonts + highlight.js from CDNs *for styling* and
  degrades offline. New runtime network calls beyond that break the promise.
- reads input from outside `~/.claude/projects/` or writes outside
  `~/.claude/daily-lessons/` (scope creep on the filesystem).
- weakens the "teach the general concept, never echo secrets" instruction in the
  command.

### 8. Plugin/manifest coherence

- `plugin.json` and the `daily-lesson` entry in `marketplace.json` should agree
  on `name`, `version`, `description` intent, and keywords. They currently both
  pin the plugin at `0.2.0`; the marketplace's own `metadata.version` is separate
  (`1.0.0`). A version bump that lands in one manifest but not the other is a
  flag.
- `commands/daily-lesson.md` frontmatter: `allowed-tools` should stay minimal and
  match what the command actually uses (`Bash, Read, Write, Glob, Grep`);
  `argument-hint` and `description` should match real behavior.
- The command invokes the renderer via `${CLAUDE_PLUGIN_ROOT}/scripts/render_lesson.py`
  — a moved/renamed script or changed flags must be reflected there.

### 9. Frozen JS depends on exact class names

The lesson-shell JS wires up interactions by class: `.copy` (copy buttons),
`.pit` (collapsible pitfalls), `.checks` / `.card` / `.reveal` (self-check), plus
`.h2n` `.tag` `.chev` for styling. If a diff renames these in the shell, in
`references/lesson-format.md`, or in the authored body contract, the copy buttons
and reveal cards silently stop working. Keep the three in lockstep.

---

## Severity calibration for this repo

Map issues to impact on *this* project, not a generic rubric:

- **Critical (Must Fix)** — breaks rendering for everyone (e.g. escaping `body`),
  crashes/wrong output from the renderer, **violates the local-only/privacy
  promise** (network egress, leaking secrets), path-traversal write, corrupts or
  can't-load the ledger, or makes the plugin invalid/uninstallable.
- **Important (Should Fix)** — violates the frozen-template split, token desync
  that leaks `{{PLACEHOLDERS}}`, exit-code/contract drift across the three
  sources, manifest/version mismatch, missing edge-case handling, README/docs
  that now actively mislead, broken `.copy`/`.checks` JS hooks.
- **Minor (Nice to Have)** — naming, a comment that now lies, docstring polish,
  keyword/description drift, style/whitespace inconsistency with surrounding code.

Calibrate honestly. A nitpick marked Critical erodes trust in the rest of the
review; a privacy regression marked Minor is a miss.
