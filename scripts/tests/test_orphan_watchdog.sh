#!/usr/bin/env bash
# Positive test for the PLAN-0108 Wave B tuned orphan-commit watchdog.
#
# Scenario: a commit X is briefly orphaned (detached-HEAD → branch switch
# leaves X dangling) and then cherry-picked back onto the branch. The
# watchdog must auto-clear it via the subject-match heuristic and exit 0.
#
# Runnable as: bash scripts/tests/test_orphan_watchdog.sh
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/orphan_commit_check.sh"

PASS=0
FAIL=0

mk_repo() {
    local d
    d="$(mktemp -d -t orphan-watchdog.XXXXXX)"
    (
        cd "$d"
        git init -q -b main
        git config user.email "claude@example.invalid"
        git config user.name  "Claude Test"
        echo "seed" > seed.txt
        git add seed.txt
        git commit -q -m "chore: seed"
    )
    echo "$d"
}

echo "==> Test 1: orphan that was cherry-picked back is auto-cleared (exit 0)"
T1="$(mk_repo)"
(
    cd "$T1"
    # Create commit X on a detached HEAD so it becomes unreachable when we
    # return to main.
    git checkout -q --detach
    echo "alpha" > a.txt
    git add a.txt
    SUBJ="feat: add alpha file (PLAN-0108 test orphan)"
    git commit -q -m "$SUBJ"
    ORPHAN_SHA="$(git rev-parse HEAD)"
    # Return to main — ORPHAN_SHA is now unreachable from any ref.
    git checkout -q main
    # Advance main with an unrelated commit so the cherry-pick produces a
    # *different* SHA from the orphan (different parent → different SHA).
    # Without this, an identical-tree/parent cherry-pick produces the SAME
    # SHA and the orphan becomes reachable again.
    echo "unrelated" > unrelated.txt
    git add unrelated.txt
    git commit -q -m "chore: unrelated change to advance main"
    # Cherry-pick re-applies the change with the same subject line.
    # NOTE: `git cherry-pick` does not accept `-q` in modern git (2.53+).
    git cherry-pick "$ORPHAN_SHA" >/dev/null 2>&1
    # Sanity: the original SHA is still in the reflog, still unreachable.
    if ! git log --all --format='%H' | grep -qxF "$ORPHAN_SHA"; then
        # Confirmed unreachable. Run watchdog.
        set +e
        bash "$SCRIPT" >/tmp/orphan_watchdog_out 2>&1
        rc=$?
        set -e
        if [ "$rc" = "0" ] && grep -q "RE-APPLIED" /tmp/orphan_watchdog_out; then
            echo "1 0" >/tmp/orphan_watchdog_t1
            printf "  PASS  watchdog exit 0, RE-APPLIED marker present\n"
        else
            echo "0 1" >/tmp/orphan_watchdog_t1
            printf "  FAIL  rc=%s output:\n" "$rc"
            sed 's/^/      /' /tmp/orphan_watchdog_out
        fi
    else
        echo "0 1" >/tmp/orphan_watchdog_t1
        printf "  FAIL  setup: orphan SHA still reachable\n"
    fi
)
read P F </tmp/orphan_watchdog_t1; PASS=$((PASS + P)); FAIL=$((FAIL + F))
rm -rf "$T1"

rm -f /tmp/orphan_watchdog_out /tmp/orphan_watchdog_t1

echo
echo "==================================="
printf "Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "==================================="
[ "$FAIL" -gt 0 ] && exit 1
exit 0
