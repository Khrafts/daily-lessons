#!/usr/bin/env python3
"""
render_lesson.py — assemble a Daily Lesson page from the canonical shells.

The whole point of this script: the look-and-feel (CSS, fonts, the metadata bar,
copy buttons, collapsible pitfalls, reveal-on-click self-check, the library page)
is FROZEN in assets/*.html. The model only ever authors the *content* — the body
fragment and a small metadata blob — and this script slots it into the shell by
literal token replacement. That makes every install render byte-identical chrome;
only the lesson's words change.

Usage (add a lesson):
  python3 render_lesson.py --meta meta.json --body body.html \
      [--lessons-dir ~/.claude/daily-lessons]

Usage (re-skin: regenerate index.html from the existing ledger, no new lesson):
  python3 render_lesson.py --rebuild-library [--lessons-dir ~/.claude/daily-lessons]

meta.json shape:
  {
    "slug": "solidity-metadata-verification",   # kebab; lesson filename stem
    "concept_key": "evm-solidity-metadata",      # dedup key (must be unique)
    "title": "Plain-text title",                 # used in <title> and <h1>
    "dek": "Italic subtitle — inline HTML like <code>x</code> is allowed",
    "one_liner": "Plain-text summary for the library row",
    "source_day": "2026-06-06",                  # the session day mined
    "taught_at": "2026-06-07T01:52:09+01:00",    # ISO 8601
    "tags": ["evm", "solidity"],
    "word_count": 1050,                           # optional; computed if absent
    "mode": "grounded"                            # optional; lecture-mode provenance
  }

body.html: the inner HTML of the article (sections 01..06 + self-check), using
ONLY the canonical component markup documented in references/lesson-format.md.

Stdout: a JSON summary {ok, title, lesson_number, file, path, word_count,
mode, variant_of}. `mode` is the lecture-mode provenance (null for pre-mode
lessons); `variant_of` links an alternate-tone rendition to its primary (null
otherwise).
Exit codes: 0 ok · 2 bad input · 3 duplicate concept_key · 4 missing assets.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

REQUIRED_META = ["slug", "concept_key", "title", "dek", "one_liner",
                 "source_day", "taught_at", "tags"]

# Display labels for the lecture modes; a rendition with no mode (pre-mode or
# legacy lessons) is shown as the "Original" tone in the library.
MODE_LABELS = {
    "grounded": "Grounded",
    "tutorial": "Tutorial",
    "deep": "Deep Dive",
    "briefing": "Briefing",
}


def mode_label(mode):
    return MODE_LABELS.get(mode or "", "Original")


def die(msg, code):
    sys.stderr.write(f"render_lesson: {msg}\n")
    sys.exit(code)


def esc(s):
    """Escape for HTML text context (& < >). Leaves quotes alone."""
    return html.escape(str(s), quote=False)


def esc_attr(s):
    """Escape for a double-quoted HTML attribute value (& < > and quotes).
    Use this, not esc(), for anything interpolated inside `attr="..."` — a bare
    `esc()` leaves `"` intact, which would break out of the attribute."""
    return html.escape(str(s), quote=True)


def read_template(assets_dir, name):
    p = assets_dir / name
    if not p.is_file():
        die(f"missing template {p}", 4)
    return p.read_text(encoding="utf-8")


def word_count_of(body_html):
    text = re.sub(r"<[^>]+>", " ", body_html)          # strip tags
    text = html.unescape(text)
    return len(text.split())


def render_lesson_html(shell, *, n, title, taught_date, source_day, tags, dek, body):
    tag_spans = "\n".join(f'    <span class="tag">{esc(t)}</span>' for t in tags)
    out = shell
    # scalars first; BODY (raw, possibly containing brace-like code) goes last
    out = out.replace("{{N}}", str(n))
    out = out.replace("{{TAUGHT_DATE}}", esc(taught_date))
    out = out.replace("{{SOURCE_DAY}}", esc(source_day))
    out = out.replace("{{TITLE}}", esc(title))
    out = out.replace("{{TAGS}}", tag_spans)
    out = out.replace("{{DEK}}", dek)                  # raw inline HTML, by design
    out = out.replace("{{BODY}}", body)                # raw HTML, last
    return out


def render_tones(renditions):
    """Tone-switch links for a concept with more than one rendition.

    Returns '' for a single-rendition concept so single-tone lessons (and all
    pre-variant libraries) render exactly as before.
    """
    if not renditions or len(renditions) < 2:
        return ""
    links = "".join(
        f'<a class="tone" href="{esc_attr(r["file"])}">{esc(mode_label(r.get("mode")))}</a>'
        for r in renditions
    )
    return f'      <div class="tones"><span class="tones-label">tones</span>{links}</div>'


def render_row(row_tpl, rec, n, renditions=None):
    tag_spans = "\n".join(f'        <span class="tag">{esc(t)}</span>'
                          for t in rec.get("tags", []))
    out = row_tpl.rstrip("\n")
    out = out.replace("{{FILE}}", esc_attr(rec["file"]))   # href="..." context
    out = out.replace("{{N}}", str(n))
    out = out.replace("{{TAUGHT_DATE}}", esc(rec["taught_at"][:10]))
    out = out.replace("{{SOURCE_DAY}}", esc(rec["source_day"]))
    out = out.replace("{{TITLE}}", esc(rec["title"]))
    out = out.replace("{{ONE_LINER}}", esc(rec["one_liner"]))
    out = out.replace("{{TAGS}}", tag_spans)
    out = out.replace("{{TONES}}", render_tones(renditions))
    return out


def group_by_concept(ledger):
    """Group ledger records by concept_key, first-seen order preserved.

    Returns a list of dicts: {primary_n (1-based CONCEPT ordinal — its
    first-appearance order, NOT its raw ledger index, so tone variants don't
    create gaps), primary (record), renditions (all records for the concept)}.
    Records without a concept_key are each their own group (defensive).
    """
    groups = {}
    order = []
    for i, rec in enumerate(ledger):
        ck = rec.get("concept_key") or f"__id::{rec.get('id', i)}"
        g = groups.get(ck)
        if g is None:
            order.append(ck)
            # ordinal = position in first-appearance order; matches the page's
            # #N and keeps the library's count line consistent with the rows.
            g = {"primary_n": len(order), "primary": rec, "renditions": []}
            groups[ck] = g
        g["renditions"].append(rec)
    return [groups[ck] for ck in order]


def regenerate_library(ledger, assets_dir, lessons_dir):
    shell = read_template(assets_dir, "library-shell.html")
    row_tpl = read_template(assets_dir, "library-row.html")
    # One row per concept (renditions of the same concept_key are grouped, with
    # their alternate tones linked from the row). Newest concept first.
    groups = group_by_concept(ledger)
    rows = [render_row(row_tpl, g["primary"], g["primary_n"], g["renditions"])
            for g in reversed(groups)]
    count = len(groups)
    count_line = f"Lesson {count} of an ever-growing pile."
    out = shell.replace("{{COUNT_LINE}}", esc(count_line))
    out = out.replace("{{ROWS}}", "\n\n".join(rows))
    (lessons_dir / "index.html").write_text(out, encoding="utf-8")


def load_ledger(lessons_dir):
    p = lessons_dir / "index.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError as e:
        die(f"index.json is not valid JSON: {e}", 2)
    if not isinstance(data, list):
        die("index.json must be a JSON array", 2)
    return data


def write_ledger(lessons_dir, ledger):
    p = lessons_dir / "index.json"
    p.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Render a Daily Lesson from canonical shells.")
    ap.add_argument("--meta", help="path to meta.json")
    ap.add_argument("--body", help="path to body.html fragment")
    ap.add_argument("--lessons-dir", default="~/.claude/daily-lessons",
                    help="output library dir (default: ~/.claude/daily-lessons)")
    ap.add_argument("--assets-dir", default=None,
                    help="canonical templates dir (default: ../assets next to this script)")
    ap.add_argument("--rebuild-library", action="store_true",
                    help="regenerate index.html from the existing ledger and exit")
    ap.add_argument("--variant", action="store_true",
                    help="render an alternate-tone rendition of an existing concept: "
                         "dedup on (concept_key, mode) instead of concept_key, write a "
                         "mode-suffixed file, and link it to the primary rendition")
    args = ap.parse_args()

    assets_dir = (Path(args.assets_dir).expanduser() if args.assets_dir
                  else Path(__file__).resolve().parent.parent / "assets")
    lessons_dir = Path(args.lessons_dir).expanduser()
    (lessons_dir / "lessons").mkdir(parents=True, exist_ok=True)

    ledger = load_ledger(lessons_dir)

    if args.rebuild_library:
        regenerate_library(ledger, assets_dir, lessons_dir)
        print(json.dumps({"ok": True, "rebuilt_library": True,
                          "lesson_count": len(ledger)}))
        return

    if not args.meta or not args.body:
        die("need --meta and --body (or --rebuild-library)", 2)

    meta = json.loads(Path(args.meta).expanduser().read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_META if k not in meta or meta[k] in (None, "", [])]
    if missing:
        die(f"meta.json missing required keys: {', '.join(missing)}", 2)

    concept_key = meta["concept_key"]
    mode = meta.get("mode") or None
    same_concept = [r for r in ledger if r.get("concept_key") == concept_key]

    body = Path(args.body).expanduser().read_text(encoding="utf-8").rstrip("\n")
    taught_date = meta["taught_at"][:10]
    slug = meta["slug"]
    wc = int(meta.get("word_count") or word_count_of(body))

    if args.variant:
        # An alternate-tone rendition of a concept that already exists. Uniqueness
        # is (concept_key, mode): a different tone is allowed, the same tone is a
        # duplicate. It shares the primary's lesson number and links back to it.
        if not mode:
            die("--variant needs a 'mode' in meta.json (the alternate tone)", 2)
        if not same_concept:
            die(f"--variant of an unknown concept_key: {concept_key}", 2)
        # A legacy/no-mode rendition counts as a distinct tone here ("" != mode),
        # so a pre-modes lesson can still be recast into any named mode.
        if any((r.get("mode") or "") == mode for r in same_concept):
            die(f"concept already has a '{mode}' rendition: {concept_key}", 3)
        file_rel = f"lessons/{taught_date}-{slug}-{mode}.html"
        variant_of = same_concept[0].get("id")
    else:
        # A fresh concept. concept_key stays a hard dedup key for the daily flow.
        if same_concept:
            die(f"concept_key already taught: {concept_key}", 3)
        file_rel = f"lessons/{taught_date}-{slug}.html"
        variant_of = None

    seq = sum(1 for r in ledger if str(r.get("id", "")).startswith(taught_date)) + 1
    record = {
        "id": f"{taught_date}-{seq:03d}",
        "slug": slug,
        "concept_key": concept_key,
        "title": meta["title"],
        "one_liner": meta["one_liner"],
        "source_day": meta["source_day"],
        "taught_at": meta["taught_at"],
        "tags": meta["tags"],
        "file": file_rel,
        "word_count": wc,
    }
    # `mode` is the lecture mode the lesson was written in (tutorial/grounded/
    # deep/briefing). Optional provenance: record it only when present so
    # pre-mode lessons keep a clean record. `variant_of` links an alternate-tone
    # rendition to its primary (the first rendition of the concept).
    if mode:
        record["mode"] = mode
    if variant_of:
        record["variant_of"] = variant_of
    ledger.append(record)
    # Number lessons by distinct concept (dense): a concept and all its tone
    # renditions share one number — its 1-based first-appearance order. This
    # matches the library's grouped rows and count line, so tone variants never
    # leave a gap (e.g. #1, #3 under "Lesson 2"). For a library with no variants
    # this equals the old ledger-position numbering, so existing lessons are
    # unaffected.
    seen = []
    for r in ledger:
        ck = r.get("concept_key")
        if ck and ck not in seen:
            seen.append(ck)
    page_n = (seen.index(concept_key) + 1) if concept_key in seen else len(seen)

    shell = read_template(assets_dir, "lesson-shell.html")
    page = render_lesson_html(
        shell, n=page_n, title=meta["title"], taught_date=taught_date,
        source_day=meta["source_day"], tags=meta["tags"], dek=meta["dek"], body=body)

    out_path = lessons_dir / file_rel
    out_path.write_text(page, encoding="utf-8")

    write_ledger(lessons_dir, ledger)
    regenerate_library(ledger, assets_dir, lessons_dir)

    print(json.dumps({
        "ok": True,
        "title": meta["title"],
        "lesson_number": page_n,
        "file": file_rel,
        "path": str(out_path),
        "word_count": wc,
        "mode": record.get("mode"),
        "variant_of": record.get("variant_of"),
    }))


if __name__ == "__main__":
    main()
