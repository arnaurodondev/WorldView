#!/usr/bin/env bash
# Detect Claude-authored commits in last 24h not reachable from any branch ref.
# Signal: parallel session rewound HEAD, orphaning intentional work.
# Part of PLAN-0107 D-4: orphan-commit watchdog.
# Honors WORLDVIEW_DISABLE_ORPHAN_CHECK=1 opt-out.
# Currently runs in WARNING mode per §D.9 — first 2 weeks. Exits non-zero on detection
# so post-cherry-pick hook surfaces the signal; downgrade to exit 0 by setting env var.
set -euo pipefail

[[ "${WORLDVIEW_DISABLE_ORPHAN_CHECK:-}" == "1" ]] && exit 0

# All reachable commits in the last 24h
REACHABLE=$(git log --all --since="24 hours ago" --format="%H" | sort -u)

# All Claude commits in reflog last 24h (catches orphaned)
REFLOG=$(git reflog --since="24 hours ago" --format="%H" | sort -u)

# Find SHAs in reflog NOT in reachable set
ORPHANS=$(comm -23 <(echo "$REFLOG") <(echo "$REACHABLE"))

if [[ -z "$ORPHANS" ]]; then
    echo "OK: no orphan commits in last 24h."
    exit 0
fi

echo "WARN: orphan commits detected (rewound HEAD?):"
FOUND=0
for sha in $ORPHANS; do
    AUTHOR=$(git log -1 --format="%an" "$sha" 2>/dev/null || echo "?")
    if echo "$AUTHOR" | grep -qi "claude\|arnau"; then
        SUBJ=$(git log -1 --format="%s" "$sha")
        echo "  $sha  ($AUTHOR)  $SUBJ"
        echo "    recover: git cherry-pick $sha"
        FOUND=1
    fi
done

[[ "$FOUND" -eq 0 ]] && { echo "OK: no Claude/Arnau-authored orphans."; exit 0; }
exit 1
