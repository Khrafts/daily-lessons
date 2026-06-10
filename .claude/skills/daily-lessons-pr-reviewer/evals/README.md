# Evals — daily-lessons-pr-reviewer

A small, reproducible benchmark that checks whether the reviewer catches three
realistic-but-broken PRs, each mapped to a repo invariant. It also doubles as a
baseline test: the same prompts with the skill **disabled** should miss more.

Everything here is committed; the only generated artifact (the fixture clone and
any run output) lands under the gitignored
`.claude/skills/daily-lessons-pr-reviewer-workspace/`.

## 1. Build the fixtures

```bash
python3 .claude/skills/daily-lessons-pr-reviewer/evals/setup_fixtures.py
```

This clones the current repo (sans `.git`/`.claude`) into a throwaway
`fixture-repo`, then creates one planted-bug branch per eval off `main`:

| Branch | Planted bug | Invariant |
|--------|-------------|-----------|
| `pr-harden-escaping` | escapes the raw-by-design `dek`/`body` → double-escapes, breaks every lesson | #3 escaping |
| `pr-usage-analytics` | adds a `urllib` telemetry ping uploading `concept_key` + `title` | #7 local-only |
| `pr-add-subtitle`   | `{{SUBTITLE}}` in the shell with no renderer replacement; `plugin.json` 0.3.0 vs `marketplace.json` 0.2.0 | #2 token sync, #8 version |

The last stdout line is `FIXTURE_REPO=<path>`. Paths default to this repo; override
with `DAILY_LESSONS_REPO` (source repo) or `FIXTURE_REPO` (output dir).

## 2. Run each eval

For every entry in `evals.json`, take its `prompt`, replace `$FIXTURE_REPO` with
the path printed above, and feed it to the skill. Run each twice:

- **with_skill** — the `daily-lessons-pr-reviewer` skill active.
- **without_skill** (baseline) — the same prompt, skill disabled.

The prompts deliberately frame each bug as benign ("security hardening", "anonymous
ping", "optional subtitle") so a shallow reviewer is tempted to approve.

## 3. Grade

Grading is a judgment step (read the produced review, check it against the eval's
`assertions` / `expected_output`) — there is no auto-grader, because the assertions
are semantic. For each run, mark each assertion pass/fail with a one-line piece of
evidence quoted from the review. A run passes only if it flags the bug at the right
severity **and** recommends against merge; being fooled by the framing fails.

A pass means: the bug is caught, severity is right, and the merge recommendation is
correct. The skill should pass all three; the baseline is expected to be weaker.
