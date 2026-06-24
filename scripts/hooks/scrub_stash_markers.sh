#!/usr/bin/env bash
# PLAN-0099 W4 T-W4-01 (audit §13.1): block any commit that contains
# residual `git stash` / `git merge` conflict markers in tracked files.
#
# The built-in pre-commit `check-merge-conflict` hook only flags the
# canonical `<<<<<<<` / `=======` / `>>>>>>>` triplet, but the variants
# emitted by `git stash pop` — `<<<<<<< Updated upstream` /
# `>>>>>>> Stashed changes` — caused a real Phase-D regression
# (PLAN-0098 W2 alert-routes + brief-scheduler + ctx-gatherer test
# files). See `docs/audits/2026-05-27-plan-0098-phase-d-code-review.md`
# §3 for the incident. This hook is the belt to the stock hook's
# braces.
#
# Behaviour:
#   * Receives staged file paths from `pre-commit` (`pass_filenames: true`).
#   * Greps each for any of the three markers, with the upstream/
#     stashed wording captured verbatim.
#   * Exits 1 (rejecting the commit) on any hit; logs the offending
#     file:line to stderr so the operator can scrub before retrying.
set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  # Nothing staged that matches the file filter — fall through.
  exit 0
fi

# The OPENING / CLOSING markers are unambiguous: git always writes a label
# after them (`<<<<<<< HEAD`, `>>>>>>> Stashed changes`), so the trailing
# space + content never occurs in normal prose/code.
UNAMBIGUOUS=(
  '^<<<<<<< '
  '^>>>>>>> '
)
# A bare `^=======$` (exactly 7 equals on its own line) is ALSO a valid
# RST/markdown section underline (e.g. a 7-char heading like "CAVEATS"), so
# it is reported ONLY when an unambiguous marker co-occurs in the same file —
# a real conflict always has all three together. This stops the docstring
# false-positive that previously tripped scripts/refresh_fundamentals.py.
SEPARATOR='^=======$'

hits=0
for f in "$@"; do
  # Skip anything that no longer exists on disk (e.g. staged delete).
  [[ -f "$f" ]] || continue
  file_has_conflict=0
  for pat in "${UNAMBIGUOUS[@]}"; do
    if grep -nE "$pat" "$f" >/dev/null 2>&1; then
      file_has_conflict=1
      grep -nE "$pat" "$f" | while IFS= read -r line; do
        echo "stash-marker: $f:$line" >&2
      done
      hits=$((hits + 1))
    fi
  done
  # Only treat a bare separator as a marker when this file also has a real
  # opening/closing marker.
  if [[ "$file_has_conflict" -eq 1 ]] && grep -nE "$SEPARATOR" "$f" >/dev/null 2>&1; then
    grep -nE "$SEPARATOR" "$f" | while IFS= read -r line; do
      echo "stash-marker: $f:$line" >&2
    done
  fi
done

if [[ "$hits" -gt 0 ]]; then
  echo "" >&2
  echo "Commit rejected: residual stash/merge markers detected." >&2
  echo "Scrub them before retrying. See PLAN-0099 W4 T-W4-01." >&2
  exit 1
fi
exit 0
