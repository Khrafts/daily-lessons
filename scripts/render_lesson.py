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
    "word_count": 1050                            # optional; computed if absent
  }

body.html: the inner HTML of the article (sections 01..06 + self-check), using
ONLY the canonical component markup documented in references/lesson-format.md.

Stdout: a JSON summary {ok, title, lesson_number, file, path, word_count}.
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


def die(msg, code):
    sys.stderr.write(f"render_lesson: {msg}\n")
    sys.exit(code)


def esc(s):
    """Escape for HTML text context (& < >). Leaves quotes alone."""
    return html.escape(str(s), quote=False)


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


def render_row(row_tpl, rec, n):
    tag_spans = "\n".join(f'        <span class="tag">{esc(t)}</span>'
                          for t in rec.get("tags", []))
    out = row_tpl.rstrip("\n")
    out = out.replace("{{FILE}}", rec["file"])
    out = out.replace("{{N}}", str(n))
    out = out.replace("{{TAUGHT_DATE}}", esc(rec["taught_at"][:10]))
    out = out.replace("{{SOURCE_DAY}}", esc(rec["source_day"]))
    out = out.replace("{{TITLE}}", esc(rec["title"]))
    out = out.replace("{{ONE_LINER}}", esc(rec["one_liner"]))
    out = out.replace("{{TAGS}}", tag_spans)
    return out


def regenerate_library(ledger, assets_dir, lessons_dir):
    shell = read_template(assets_dir, "library-shell.html")
    row_tpl = read_template(assets_dir, "library-row.html")
    # ledger is chronological (append order); N = 1-based position; show newest first
    numbered = [(i + 1, rec) for i, rec in enumerate(ledger)]
    rows = [render_row(row_tpl, rec, n) for n, rec in reversed(numbered)]
    count = len(ledger)
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
    if any(r.get("concept_key") == concept_key for r in ledger):
        die(f"concept_key already taught: {concept_key}", 3)

    body = Path(args.body).expanduser().read_text(encoding="utf-8").rstrip("\n")
    taught_date = meta["taught_at"][:10]
    slug = meta["slug"]
    file_rel = f"lessons/{taught_date}-{slug}.html"
    wc = int(meta.get("word_count") or word_count_of(body))

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
    ledger.append(record)
    n = len(ledger)  # lesson number (chronological)

    shell = read_template(assets_dir, "lesson-shell.html")
    page = render_lesson_html(
        shell, n=n, title=meta["title"], taught_date=taught_date,
        source_day=meta["source_day"], tags=meta["tags"], dek=meta["dek"], body=body)

    out_path = lessons_dir / file_rel
    out_path.write_text(page, encoding="utf-8")

    write_ledger(lessons_dir, ledger)
    regenerate_library(ledger, assets_dir, lessons_dir)

    print(json.dumps({
        "ok": True,
        "title": meta["title"],
        "lesson_number": n,
        "file": file_rel,
        "path": str(out_path),
        "word_count": wc,
    }))


if __name__ == "__main__":
    main()
