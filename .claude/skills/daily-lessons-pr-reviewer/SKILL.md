---
name: daily-lessons-pr-reviewer
description: >-
  Review a pull request to the Khrafts/daily-lessons repo (the daily-lesson
  Claude Code plugin). Use this whenever the user wants to review, check, look
  at, or get an opinion on a PR in this repo — e.g. "review PR #12", "review the
  open PR", "what do you think of this pull request", pasting a daily-lessons PR
  URL, "check this PR for bugs", or "review my latest PR / this branch before I
  open a PR". Searches GitHub to resolve the PR (by number, URL, branch, or
  description), fetches the diff once, then runs three parallel reviewers
  (architect, auditor, tidy) specialized for THIS repo's invariants — the frozen
  HTML templates, the render_lesson.py {{token}} contract, escaping rules, exit
  codes, plugin manifests, and the local-only privacy promise. Writes a markdown
  report and prints a terminal summary; NEVER posts to GitHub unless the user
  explicitly approves it first.
---

# daily-lessons PR Reviewer (orchestrator)

Run a thorough, repo-aware review of a pull request to **Khrafts/daily-lessons**.
The foundation is the superpowers `requesting-code-review` idea: hand each
reviewer **precisely-crafted, isolated context** (the diff + this repo's
invariants) rather than your session history, and get back structured,
severity-calibrated findings. Three personas run in parallel and merge into one
report.

## Default repo

`Khrafts/daily-lessons` (remote `origin`). Assume it unless the user names another.

## Personas

| Persona | Focus for this repo |
|---------|---------------------|
| **architect** | Frozen-template/content split, local-only promise, design altitude, manifest coherence, backward-compat |
| **auditor** | render_lesson.py correctness — escaping, {{token}} sync, exit codes, ledger integrity, path safety, no network egress, JS class hooks |
| **tidy** | Docs-vs-reality, the triplicated exit-code/contract sources, description/keyword drift, comment accuracy, naming/style |

Prompt templates live in `agents/architect.md`, `agents/auditor.md`,
`agents/tidy.md`. Shared knowledge for all three: `references/repo-invariants.md`.

## Critical rules

1. **Never post to GitHub silently.** Produce the report first. Only post a
   comment/review **after the user explicitly says to**, and confirm exactly what
   and where. (This honors the standing rule: no writes to a remote without
   per-action permission.)
2. **Always write the markdown report file** — it's the primary artifact; the
   terminal summary just points at it.
3. **Personas must read real files, not just the diff.** The diff is the change;
   the invariants are why it matters.
4. Default to running **all three** personas. Run a subset only if the user asks
   ("just the auditor", "security only" → auditor, etc.).

---

## Step 1 — Resolve the PR reference (the "search" part)

The user may point you at a PR many ways. Resolve to a concrete number (or a
local branch range) before fetching. Let `R=Khrafts/daily-lessons` unless told
otherwise.

- **Bare number / `#12` / full URL** → that PR. Extract the trailing number from a
  URL.
- **A branch name** → `gh pr list --repo $R --head <branch> --json number,title`.
- **"the open PR" / "any open PRs" / no argument** →
  `gh pr list --repo $R --state open --json number,title,headRefName,updatedAt`.
  If exactly one, use it. If several, list them and ask which. If none, say so and
  offer to review the current local branch vs `main` instead.
- **A description / fuzzy phrase** ("the renderer PR", "the one about escaping")
  → search: `gh pr list --repo $R --search "<terms>" --json number,title` (add
  `--state all` if nothing open matches). Show the top matches and confirm before
  reviewing, unless there's an unambiguous single hit.
- **A local branch with no PR yet** ("review this branch", "before I push") →
  skip GitHub: review `main...<branch>` (or `origin/main...HEAD`) via the local
  diff mode below. Note in the report that it's a pre-PR local review.

If `gh` isn't authenticated, `gh auth status` will say so — surface that and fall
back to local-diff review when possible.

## Step 2 — Fetch PR data ONCE

Use the bundled helper so all personas share a single fetch. `$SKILL` is this
skill's directory.

```bash
DATE=$(date +%F)
# GitHub PR:
OUT=$(bash "$SKILL/scripts/fetch_pr.sh" --repo Khrafts/daily-lessons --pr <NUMBER> | tail -1)
# …or local branch review (no PR yet):
# OUT=$(bash "$SKILL/scripts/fetch_pr.sh" --repo Khrafts/daily-lessons --base origin/main --head HEAD | tail -1)
```

`$OUT` now holds `meta.json`, `diff.patch`, `checks.txt`. Skim `meta.json` and
`diff.patch` yourself first so your merge later is grounded, and so a tiny diff
(typo fix) can skip the full fan-out if that's clearly all the user wants.

Make sure the local checkout reflects the PR's code where it matters. For deep
review of a GitHub PR you can optionally check it out (`gh pr checkout <NUMBER>`)
so personas read the actual changed files — but always restore the user's branch
afterward and never discard their uncommitted work. If you don't check it out,
tell the personas the diff is authoritative and the working tree is the base.

## Step 3 — Spawn the three personas IN PARALLEL

Dispatch all selected personas in a **single message** (multiple `Agent` tool
calls, `subagent_type: general-purpose`). For each, read its template in
`agents/<persona>.md` and fill the placeholders:

| Placeholder | Value |
|-------------|-------|
| `{REPO}` | `Khrafts/daily-lessons` |
| `{PR_NUMBER}` | the number (or "local" for a branch review) |
| `{PR_TITLE}` / `{PR_BODY}` | from `meta.json` |
| `{DIFF_PATH}` | `$OUT/diff.patch` |
| `{META_PATH}` / `{CHECKS_PATH}` | `$OUT/meta.json` / `$OUT/checks.txt` |
| `{INVARIANTS_PATH}` | `$SKILL/references/repo-invariants.md` (absolute) |
| `{REPO_PATH}` | the local checkout (the repo working dir) |

Pass the diff via its path, not pasted inline — it keeps each persona's context
clean and lets them grep the full files. Each returns Strengths / Critical /
Important / Minor / Verdict.

**If you can't dispatch subagents** (e.g. you are yourself a subagent, or the
Agent tool isn't available): run the three persona passes **inline**, one after
another, reading each `agents/<persona>.md` and `references/repo-invariants.md`
and producing that persona's section yourself. The value of this skill is the
repo-aware checklist and the three distinct lenses — not the parallelism. Don't
skip a lens just because you couldn't fan out.

## Step 4 — Merge

Collect all three. Deduplicate findings that two personas both raised (keep the
clearest statement, note both flagged it). Reconcile severities — if the auditor
calls something Critical and you can confirm it from the diff, keep it Critical.
Form one overall recommendation:

- **Request Changes** if any confirmed Critical, or multiple Important.
- **Needs Discussion** if the design/altitude is genuinely contested.
- **Approve** if only Minor (or nothing) remains.

## Step 5 — Write the report (mandatory)

```bash
mkdir -p ~/.claude/pr-reviews
```

Write with the Write tool to
`~/.claude/pr-reviews/daily-lessons-<NUMBER>-<DATE>.md` using this structure:

```markdown
# PR Review: daily-lessons #<NUMBER>

**Title:** <title>
**Author:** @<author>   **URL:** <url>
**Reviewed:** <DATE>   **Personas:** architect, auditor, tidy
**Base ← Head:** <baseRefName> ← <headRefName>   **CI:** <pass/fail/none>

## Summary
<2–3 sentences: what the PR does + overall quality.>

**Recommendation:** <Approve | Request Changes | Needs Discussion> — <reason>

| Persona   | Critical | Important | Minor |
|-----------|----------|-----------|-------|
| Architect | 0 | 0 | 0 |
| Auditor   | 0 | 0 | 0 |
| Tidy      | 0 | 0 | 0 |

### Must Fix (Critical)
- <list, or "None">
### Should Fix (Important)
- <list, or "None">
### Key Findings
- <3–5 bullets, the signal across all personas — include what's done well>

---
## Architectural Analysis
<full architect output, or "[Not run]">

## Correctness & Safety Audit
<full auditor output, or "[Not run]">

## Code Quality & Docs
<full tidy output, or "[Not run]">

---
### Consider (Minor)
- [ ] <minor items as a checklist>

*Generated by daily-lessons-pr-reviewer. Nothing was posted to GitHub.*
```

Include the **complete** persona outputs, not summaries.

## Step 6 — Terminal summary

Print a short summary: the report path, a 2–3 sentence what-it-does, the
recommendation, the counts table, and any blocking (Critical) issues one line
each. Keep the detail in the file.

## Step 7 — Offer to post (only after explicit OK)

End by offering — don't act:

> Report saved to `<path>`. Want me to post anything to GitHub? I can drop a
> summary comment on the PR, or leave a review (approve / request changes). I
> won't post anything until you tell me exactly what.

Only if the user explicitly approves, and after confirming the exact text and
target:
- Summary comment: `gh pr comment <NUMBER> --repo Khrafts/daily-lessons --body-file <file>`
- Review: `gh pr review <NUMBER> --repo Khrafts/daily-lessons --comment --body-file <file>`
  (use `--request-changes` / `--approve` only if the user explicitly chooses that
  verdict).

If the user never asks, never post. The local report is a complete deliverable.

---

## Notes

- **Subset / single persona:** "security review" → auditor only; "is the design
  sound?" → architect only; otherwise all three.
- **Tiny diffs:** a one-line typo fix doesn't need three subagents — review it
  inline, still write a short report if the user wanted a review on record.
- **Bundled resources:** `references/repo-invariants.md` (shared checklist),
  `agents/*.md` (persona prompts), `scripts/fetch_pr.sh` (one-shot fetch).
