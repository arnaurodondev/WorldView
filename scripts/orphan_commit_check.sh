#!/usr/bin/env bash
# Detect Claude-authored commits in last 24h not reachable from any branch ref.
# Signal: parallel session rewound HEAD, orphaning intentional work.
# Part of PLAN-0107 D-4: orphan-commit watchdog. PLAN-0108 Wave B tuning.
#
# Tuning (PLAN-0108 Wave B): two RE-APPLIED heuristics reduce false positives
#   1. Subject-match: orphan's subject line exists in reachable last-24h log
#   2. Path-rename: every file the orphan touched has a rename match in
#      `git diff --find-renames=50` against the reachable set
#
# Exit codes (PLAN-0108 Wave B):
#   0 — no orphans, OR every orphan is RE-APPLIED
#   1 — at least one orphan has no re-application match (genuine loss)
#   2 — ambiguous (some files of an orphan matched, others did not) — manual triage
#
# Env knobs:
#   WORLDVIEW_DISABLE_ORPHAN_CHECK=1   skip entirely
set -euo pipefail

[[ "${WORLDVIEW_DISABLE_ORPHAN_CHECK:-}" == "1" ]] && exit 0

# All reachable commits in the last 24h (anything referenced by a branch/tag).
REACHABLE=$(git log --all --since="24 hours ago" --format="%H" | sort -u)

# All commits seen via reflog last 24h (catches orphaned HEAD movements).
REFLOG=$(git reflog --since="24 hours ago" --format="%H" | sort -u)

# Find SHAs in reflog NOT reachable from any ref.
ORPHANS=$(comm -23 <(echo "$REFLOG") <(echo "$REACHABLE"))

if [[ -z "$ORPHANS" ]]; then
    echo "OK: no orphan commits in last 24h."
    exit 0
fi

# --- PLAN-0108 Wave B: re-application detection helpers ---

# subject_reapplied <sha>
# Returns 0 (true) iff the orphan's subject line appears in a *reachable*
# commit in the last 24h. We deliberately fuzz only on exact-subject match
# to avoid false positives from generic subjects ("fix tests").
subject_reapplied() {
    local sha="$1"
    local subj
    subj="$(git log -1 --format='%s' "$sha" 2>/dev/null || true)"
    [[ -z "$subj" ]] && return 1
    # Search reachable commits in the last 24h for the same subject.
    # Use -F (fixed string) to neutralise regex metachars in subjects.
    local match
    match="$(git log --all --since='24 hours ago' --format='%H %s' \
        | grep -F -- " $subj" \
        | awk '{print $1}' \
        | grep -vxF "$sha" \
        | head -n 1 || true)"
    [[ -n "$match" ]]
}

# path_rename_reapplied <sha>
# Returns:
#   0 — every file of the orphan has a rename match in HEAD (RE-APPLIED)
#   2 — partial: some files matched, others did not (AMBIGUOUS)
#   1 — none matched (NOT re-applied)
path_rename_reapplied() {
    local sha="$1"
    # Files touched by the orphan commit.
    local files
    files="$(git show --name-only --format='' "$sha" 2>/dev/null | sed '/^$/d' || true)"
    [[ -z "$files" ]] && return 1

    local total=0 matched=0
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        total=$((total + 1))
        # If the exact path exists at HEAD, count as matched.
        if git cat-file -e "HEAD:$f" 2>/dev/null; then
            matched=$((matched + 1))
            continue
        fi
        # Otherwise check whether `git diff --find-renames=50` between the
        # orphan tree and HEAD reports a rename for this path.
        local rename_hit
        rename_hit="$(git diff --find-renames=50 --name-status "$sha" HEAD -- 2>/dev/null \
            | awk -v p="$f" '$1 ~ /^R/ && ($2 == p || $3 == p) {print; exit}')"
        if [[ -n "$rename_hit" ]]; then
            matched=$((matched + 1))
        fi
    done <<<"$files"

    if [[ "$matched" -eq 0 ]]; then
        return 1
    fi
    if [[ "$matched" -eq "$total" ]]; then
        return 0
    fi
    return 2
}

echo "WARN: orphan commits detected (rewound HEAD?):"
GENUINE=0      # un-re-applied orphans → exit 1 contribution
AMBIGUOUS=0    # partially matched → exit 2 contribution
CLEARED=0      # auto-cleared by re-application heuristics

for sha in $ORPHANS; do
    AUTHOR=$(git log -1 --format="%an" "$sha" 2>/dev/null || echo "?")
    # Only worry about Claude/Arnau authored commits; others are likely
    # intentional drops (rebase --skip, etc.).
    if ! echo "$AUTHOR" | grep -qi "claude\|arnau"; then
        continue
    fi
    SUBJ=$(git log -1 --format="%s" "$sha")
    if subject_reapplied "$sha"; then
        echo "  $sha  RE-APPLIED (subject-match)  $SUBJ"
        CLEARED=$((CLEARED + 1))
        continue
    fi
    set +e
    path_rename_reapplied "$sha"
    rc=$?
    set -e
    case "$rc" in
        0)
            echo "  $sha  RE-APPLIED (path-rename)   $SUBJ"
            CLEARED=$((CLEARED + 1))
            ;;
        2)
            echo "  $sha  AMBIGUOUS  ($AUTHOR)  $SUBJ"
            echo "    triage: git show $sha   # some files match HEAD, others do not"
            AMBIGUOUS=$((AMBIGUOUS + 1))
            ;;
        *)
            echo "  $sha  ($AUTHOR)  $SUBJ"
            echo "    recover: git cherry-pick $sha"
            GENUINE=$((GENUINE + 1))
            ;;
    esac
done

if [[ "$GENUINE" -eq 0 && "$AMBIGUOUS" -eq 0 ]]; then
    if [[ "$CLEARED" -gt 0 ]]; then
        echo "OK: $CLEARED orphan(s) auto-cleared as RE-APPLIED."
    else
        echo "OK: no Claude/Arnau-authored orphans."
    fi
    exit 0
fi
if [[ "$GENUINE" -gt 0 ]]; then
    exit 1
fi
# Only ambiguous matches remain — distinguishable from "0 = clean".
exit 2
