# Lesson format — the canonical contract

The look-and-feel of a Daily Lesson is **frozen** in `assets/lesson-shell.html`,
`assets/library-shell.html`, and `assets/library-row.html`. You (the model
running `/daily-lesson`) never reproduce the page chrome — the `<head>`, the CSS,
the `<script>`, the top nav, the metadata bar, or the footer. You author only two
things and hand them to `scripts/render_lesson.py`, which slots them into the
shell by literal token replacement:

1. **`meta.json`** — the lesson's metadata.
2. **`body.html`** — the inner HTML of the article (sections 01–06 + self-check).

The script writes the lesson file, appends to `index.json`, and regenerates the
library `index.html`. Because the chrome comes from the shells, every install
renders identical styling and interactions — only your words differ.

> **Why this exists:** before this, each run re-described the design in prose and
> re-improvised the HTML, so no two machines matched. Freezing the shell makes the
> design canon. To change the canon, edit the files in `assets/` — not the body.

---

## meta.json

```json
{
  "slug": "kebab-case-stem",
  "concept_key": "domain-prefixed-unique-key",
  "title": "Plain-text title (no HTML)",
  "dek": "The italic subtitle. Inline HTML is allowed, e.g. <code>foo</code>, <em>x</em>.",
  "one_liner": "Plain-text summary shown in the library row (no HTML).",
  "source_day": "YYYY-MM-DD",
  "taught_at": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ",
  "tags": ["two", "to", "five", "tags"],
  "word_count": 0
}
```

- `title` and `one_liner` are **plain text** — the renderer HTML-escapes them. Do not put tags in them.
- `dek` is **raw inline HTML** — small inline elements (`<code>`, `<em>`, `<strong>`) only, no block elements.
- `concept_key` is the dedup key; the renderer refuses (exit 3) if it already exists in the ledger. Verify against `index.json` first.
- `word_count` is optional — omit it and the renderer counts the body for you.

---

## body.html — the article

Author **only** the sections between the dek and the footer. The structure is
fixed (this is what makes lessons feel consistent): six numbered sections, then a
self-check. Use exactly these components so the frozen CSS/JS applies.

### Section header
```html
<h2><span class="h2n">01</span> What it is</h2>
```
Numbered `01`–`06`. The six sections, in order: **What it is · Why it mattered
today · The mental model · A worked example · Pitfalls · Go deeper**.

### Paragraphs
Plain `<p>…</p>`. The first paragraph of the lesson may use `<p class="lead">…</p>`
for slightly larger type. Inline `<code>`, `<strong>`, `<em>`, `<a>` are all styled.

### Code block (with copy button)
```html
<figure class="code">
  <figcaption><span>filename.ts</span><button class="copy" type="button">Copy</button></figcaption>
<pre><code class="language-typescript">// real code here
const x = 1;</code></pre>
</figure>
```
Rules that matter:
- The `<pre><code>` content is rendered with `white-space: pre`. Put the code at
  **column 0** (do not indent `<pre>` to match the surrounding HTML) or the
  indentation will show on the page.
- **HTML-escape** `<`, `>`, `&` inside the code (`&lt;`, `&gt;`, `&amp;`).
- Set `class="language-xxx"` (typescript, solidity, rust, python, json, bash…) so
  highlight.js can color it. The page still reads fine if the CDN is offline.
- The figcaption `<span>` is a short label (a filename or one-line caption).

### Blockquote (for the one-line "aha")
```html
<blockquote>The single sentence that makes the mental model click.</blockquote>
```

### Pitfalls (collapsible)
Use 2–4 of these in section 05:
```html
<details class="pit">
  <summary><span class="chev">&rsaquo;</span><span class="pl">01</span><span>Short pitfall title</span></summary>
  <div class="body">The explanation. Inline HTML fine.</div>
</details>
```

### Self-check (reveal-on-click cards)
End the body with this block (2–3 cards):
```html
<h3>Self-check</h3>
<p style="color:var(--muted);font-size:.92rem;margin-top:.2rem">Click a card to reveal the answer.</p>
<div class="checks">
  <div class="card">
    <div class="q"><span class="qn">Q1</span><span>The question?</span></div>
    <div class="a">The answer, revealed on click.</div>
    <div class="reveal">▸ reveal</div>
  </div>
  <!-- Q2, Q3 … -->
</div>
```

**Do not** add a `<hr>` or footer — the shell supplies them. The body ends with
the closing `</div>` of `.checks`.

---

## Invoking the renderer

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_lesson.py" \
  --meta /tmp/daily-lesson-meta.json \
  --body /tmp/daily-lesson-body.html
# default --lessons-dir is ~/.claude/daily-lessons
```

Stdout is JSON: `{ok, title, lesson_number, file, path, word_count}`. Use `path`
to tell the user how to open it. Exit codes: `0` ok · `2` bad input · `3`
duplicate `concept_key` · `4` missing template assets.

Re-skin every existing lesson's library page after editing a shell:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_lesson.py" --rebuild-library
```
(The lesson *pages* are written once at creation; `--rebuild-library` only
rebuilds `index.html`. To re-skin old lesson pages too, re-render them.)

---

## The chat widget (shell-owned)

`assets/lesson-shell.html` now carries a chat block delimited by literal
markers — `<!-- daily-lesson-chat:v1 -->` … `<!-- /daily-lesson-chat:v1 -->` —
just before `</body>`. It is page **chrome**, owned by the shell exactly like
the footer: the body contract above is unchanged, and you never write chat
markup in the body. Lesson pages rendered before the widget existed get the
same marker-delimited block injected by `scripts/chat_server.py` at serve
time, so they don't need re-rendering. Word counts are unaffected — the
renderer counts only the body fragment, never the shell.
