#!/usr/bin/env bash
#
# fetch_pr.sh — fetch a PR's metadata, diff, and CI checks ONCE so all three
# reviewer personas share a single fetch instead of each hitting the GitHub API.
#
# The orchestrator resolves a fuzzy reference (number / URL / branch / "the open
# PR" / search phrase) to a concrete PR number first, then calls this.
#
# Modes:
#   GitHub PR:   fetch_pr.sh --repo <owner/name> --pr <number> [--out <dir>]
#   Local diff:  fetch_pr.sh --base <ref> --head <ref> [--repo <owner/name>] [--out <dir>]
#                (for reviewing a branch before a PR exists / offline)
#
# Writes into <dir> (default: a fresh mktemp dir):
#   meta.json   — PR metadata (or a synthetic blob in local-diff mode)
#   diff.patch  — the unified diff
#   checks.txt  — CI check results (empty in local-diff mode)
# Prints the output directory on stdout as the last line.
set -euo pipefail

REPO="" ; PR="" ; BASE="" ; HEAD="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --pr)   PR="$2";   shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    --head) HEAD="$2"; shift 2 ;;
    --out)  OUT="$2";  shift 2 ;;
    *) echo "fetch_pr: unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$OUT" ] || OUT="$(mktemp -d -t daily-lessons-pr.XXXXXX)"
mkdir -p "$OUT"

if [ -n "$PR" ]; then
  [ -n "$REPO" ] || { echo "fetch_pr: --pr needs --repo" >&2; exit 2; }
  command -v gh >/dev/null || { echo "fetch_pr: gh CLI not found (brew install gh)" >&2; exit 3; }

  gh pr view "$PR" --repo "$REPO" \
    --json number,title,body,author,state,isDraft,files,additions,deletions,changedFiles,commits,baseRefName,headRefName,url,labels,reviewDecision \
    > "$OUT/meta.json" \
    || { echo "fetch_pr: could not view PR #$PR in $REPO (does it exist? gh authed?)" >&2; exit 3; }

  gh pr diff "$PR" --repo "$REPO" > "$OUT/diff.patch" \
    || { echo "fetch_pr: could not fetch diff for PR #$PR" >&2; exit 3; }

  # checks are best-effort: a PR with no CI configured returns non-zero
  gh pr checks "$PR" --repo "$REPO" > "$OUT/checks.txt" 2>&1 || true

elif [ -n "$BASE" ] && [ -n "$HEAD" ]; then
  git rev-parse --verify "$BASE" >/dev/null 2>&1 || { echo "fetch_pr: bad --base ref: $BASE" >&2; exit 2; }
  git rev-parse --verify "$HEAD" >/dev/null 2>&1 || { echo "fetch_pr: bad --head ref: $HEAD" >&2; exit 2; }
  git diff "$BASE"..."$HEAD" > "$OUT/diff.patch"
  STAT="$(git diff --stat "$BASE"..."$HEAD" | tail -1 | sed 's/"/\\"/g')"
  printf '{"local_diff":true,"repo":"%s","base":"%s","head":"%s","stat":"%s"}\n' \
    "$REPO" "$BASE" "$HEAD" "$STAT" > "$OUT/meta.json"
  : > "$OUT/checks.txt"
else
  echo "fetch_pr: need --pr <n> (with --repo) OR --base/--head" >&2
  exit 2
fi

echo "$OUT"
