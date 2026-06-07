#!/usr/bin/env bash
# Warn if a commit on services/ or libs/ lacks Co-Authored-By: Claude trailer.
# Honors WORLDVIEW_DISABLE_COAUTHOR_CHECK=1 opt-out.
# Part of PLAN-0107 D-3: soft-prevention commit-author signature.
# Currently runs in WARNING mode (exit 0 on missing trailer) per §D.9 — first 2 weeks.
set -euo pipefail

[[ "${WORLDVIEW_DISABLE_COAUTHOR_CHECK:-}" == "1" ]] && exit 0

# Pre-commit mode (no args): check staged commit
# CI mode (sha arg): check that commit
SHA="${1:-HEAD}"
[[ "$SHA" == "HEAD" && -z "$(git rev-list --no-walk HEAD 2>/dev/null)" ]] && exit 0

CHANGED=$(git diff --cached --name-only 2>/dev/null || git show --name-only --format="" "$SHA")
TOUCHES_CODE=$(echo "$CHANGED" | grep -E "^(services|libs)/" || true)
[[ -z "$TOUCHES_CODE" ]] && exit 0  # no relevant changes

MSG=$(git log -1 --pretty=%B "$SHA" 2>/dev/null || cat .git/COMMIT_EDITMSG)
if ! echo "$MSG" | grep -qi "Co-Authored-By:.*Claude"; then
    echo "WARN: Commit touches services/ or libs/ but lacks Co-Authored-By: Claude trailer."
    echo "      If this is a manual edit, no action needed."
    echo "      If this should have been a Claude commit, add the trailer."
    # Warning-not-error mode for first 2 weeks per §D.9
    exit 0  # change to 1 after acceptance period
fi
exit 0
