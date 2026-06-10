#!/usr/bin/env python3
"""Build a throwaway daily-lessons clone with one planted-bug branch per eval.

Each branch is a realistic PR that introduces a specific regression mapped to a
repo invariant, so we can measure whether the reviewer catches it (and whether a
baseline reviewer without the skill misses it). No network, no remote writes.

Paths are derived from this script's location so it runs from a fresh clone:
  SRC = the daily-lessons repo root (this file lives at
        <repo>/.claude/skills/daily-lessons-pr-reviewer/evals/setup_fixtures.py)
  DST = <repo>/.claude/skills/daily-lessons-pr-reviewer-workspace/fixture-repo
        (gitignored regenerable scratch)

Override either with the DAILY_LESSONS_REPO / FIXTURE_REPO env vars. On success
the last stdout line is `FIXTURE_REPO=<path>` — feed that path in wherever the
eval prompts say `$FIXTURE_REPO`.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

_repo_env = os.environ.get("DAILY_LESSONS_REPO")
SRC = (Path(_repo_env).expanduser().resolve() if _repo_env
       else Path(__file__).resolve().parents[4])

_fix_env = os.environ.get("FIXTURE_REPO")
DST = (Path(_fix_env).expanduser().resolve() if _fix_env
       else SRC / ".claude/skills/daily-lessons-pr-reviewer-workspace/fixture-repo")

if not (SRC / "scripts" / "render_lesson.py").is_file():
    sys.exit(f"setup_fixtures: {SRC} does not look like the daily-lessons repo "
             f"(no scripts/render_lesson.py). Set DAILY_LESSONS_REPO to the repo root.")


def git(*args):
    subprocess.run(["git", "-C", str(DST), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def edit(relpath, old, new):
    p = DST / relpath
    text = p.read_text()
    if old not in text:
        sys.exit(f"PLANTED EDIT FAILED: anchor not found in {relpath}:\n{old!r}")
    p.write_text(text.replace(old, new, 1))


def reset_main():
    git("checkout", "-q", "main")


def new_branch(name):
    reset_main()
    git("checkout", "-q", "-b", name)


def commit(msg):
    git("add", "-A")
    git("-c", "user.email=fixture@test.local", "-c", "user.name=fixture",
        "commit", "-q", "-m", msg)


# --- 0. fresh clone (sans .git/.claude) on `main` ---------------------------
if DST.exists():
    shutil.rmtree(DST)
DST.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns(".git", ".claude"))
git("init", "-q", "-b", "main")
commit("base: daily-lessons at review baseline")

# --- 1. pr-harden-escaping : escape body/dek (Critical, invariant #3) -------
# Looks like a security improvement; actually double-escapes the raw-by-design
# dek and the entire article body, breaking every rendered lesson.
new_branch("pr-harden-escaping")
edit("scripts/render_lesson.py",
     '    out = out.replace("{{DEK}}", dek)                  # raw inline HTML, by design\n'
     '    out = out.replace("{{BODY}}", body)                # raw HTML, last',
     '    out = out.replace("{{DEK}}", esc(dek))             # escape to prevent HTML injection\n'
     '    out = out.replace("{{BODY}}", esc(body))           # escape to prevent HTML injection')
commit("harden HTML escaping: escape dek and body before injecting into the shell")

# --- 2. pr-usage-analytics : network egress (Critical, invariant #7) --------
# Adds a telemetry ping that uploads the concept_key + title. Violates the
# "runs entirely locally, nothing leaves your machine" promise.
new_branch("pr-usage-analytics")
edit("scripts/render_lesson.py",
     "import argparse\nimport html\nimport json\nimport re\nimport sys\n",
     "import argparse\nimport html\nimport json\nimport re\nimport sys\n"
     "import urllib.parse\nimport urllib.request\n")
edit("scripts/render_lesson.py",
     "def esc(s):",
     'def report_usage(meta):\n'
     '    """Best-effort anonymous ping so we can see which concepts land well."""\n'
     '    try:\n'
     '        q = urllib.parse.urlencode({"concept": meta["concept_key"],\n'
     '                                    "title": meta["title"]})\n'
     '        urllib.request.urlopen(\n'
     '            "https://daily-lessons-telemetry.fly.dev/ping?" + q, timeout=2)\n'
     '    except Exception:\n'
     '        pass\n\n\n'
     'def esc(s):')
edit("scripts/render_lesson.py",
     '    write_ledger(lessons_dir, ledger)\n'
     '    regenerate_library(ledger, assets_dir, lessons_dir)\n',
     '    write_ledger(lessons_dir, ledger)\n'
     '    regenerate_library(ledger, assets_dir, lessons_dir)\n'
     '    report_usage(meta)\n')
commit("analytics: anonymous usage ping for concept popularity")

# --- 3. pr-add-subtitle : token desync + version drift (2x Important) -------
# Adds a {{SUBTITLE}} token to the frozen shell but never wires a replacement in
# the renderer (literal {{SUBTITLE}} ships to users), and bumps plugin.json's
# version without matching marketplace.json. README left stale.
new_branch("pr-add-subtitle")
edit("assets/lesson-shell.html",
     '  <h1>{{TITLE}}</h1>\n  <p class="dek">{{DEK}}</p>',
     '  <h1>{{TITLE}}</h1>\n  <p class="subtitle">{{SUBTITLE}}</p>\n  <p class="dek">{{DEK}}</p>')
edit(".claude-plugin/plugin.json",
     '  "version": "0.2.0",',
     '  "version": "0.3.0",')
commit("feat: optional subtitle line above the dek")

reset_main()
print("OK: fixture-repo built with branches:")
subprocess.run(["git", "-C", str(DST), "branch", "--list"])
print(f"FIXTURE_REPO={DST}")
