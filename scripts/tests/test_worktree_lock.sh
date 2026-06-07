#!/usr/bin/env bash
# Unit tests for scripts/worktree_lock.sh (PLAN-0107 D-2).
# Plain bash with a tiny assert helper; runnable as:
#   bash scripts/tests/test_worktree_lock.sh

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK_SCRIPT="$REPO_ROOT/scripts/worktree_lock.sh"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1" expected="$2" label="$3"
    if [ "$actual" = "$expected" ]; then
        PASS=$((PASS + 1))
        printf "  PASS  %s (got %s)\n" "$label" "$actual"
    else
        FAIL=$((FAIL + 1))
        printf "  FAIL  %s (expected %s, got %s)\n" "$label" "$expected" "$actual"
    fi
}

# Each test runs in a temp dir (isolated worktree) so we don't pollute the real lock.
new_tmp() {
    local d
    d="$(mktemp -d -t worktree-lock-test.XXXXXX)"
    (cd "$d" && git init -q .)
    echo "$d"
}

echo "==> Test 1: clean state — acquire succeeds, lockfile exists, check returns 0"
T1="$(new_tmp)"
(
    cd "$T1"
    bash "$LOCK_SCRIPT" acquire test-agent
    rc_acquire=$?
    p=0; f=0
    if [ "$rc_acquire" = "0" ]; then p=$((p+1)); printf "  PASS  acquire exit code (0)\n"; else f=$((f+1)); printf "  FAIL  acquire exit=%s\n" "$rc_acquire"; fi
    if [ -f .worktree-lock ]; then p=$((p+1)); printf "  PASS  lockfile present\n"; else f=$((f+1)); printf "  FAIL  lockfile missing\n"; fi
    # The lockfile created by `acquire` pinned $$ of a short-lived bash that has
    # now exited — so a naive `check` would return 2 (stale). To validate the
    # "alive" path we rewrite the lockfile to point at a long-running sleep.
    sleep 30 &
    live_pid=$!
    cat >.worktree-lock <<EOF
{"pid": $live_pid, "agent_id": "test-agent", "started_at": "2026-06-06T00:00:00Z", "branch": "main"}
EOF
    bash "$LOCK_SCRIPT" check
    rc_check=$?
    kill "$live_pid" 2>/dev/null || true
    wait "$live_pid" 2>/dev/null || true
    if [ "$rc_check" = "0" ]; then p=$((p+1)); printf "  PASS  check exit 0 while alive\n"; else f=$((f+1)); printf "  FAIL  check exit=%s\n" "$rc_check"; fi
    echo "$p $f" >/tmp/wlt_t1
)
read P F </tmp/wlt_t1; PASS=$((PASS + P)); FAIL=$((FAIL + F))
rm -rf "$T1"

echo "==> Test 2: second acquire from a foreign live pid is refused"
T2="$(new_tmp)"
(
    cd "$T2"
    # Spawn a long-running peer process and pin its pid into the lockfile.
    sleep 30 &
    peer_pid=$!
    cat >.worktree-lock <<EOF
{"pid": $peer_pid, "agent_id": "peer", "started_at": "2026-06-06T00:00:00Z", "branch": "main"}
EOF
    set +e
    bash "$LOCK_SCRIPT" acquire intruder 2>/dev/null
    rc=$?
    set -e
    kill "$peer_pid" 2>/dev/null || true
    wait "$peer_pid" 2>/dev/null || true
    if [ "$rc" = "1" ]; then
        echo "1 0" >/tmp/wlt_t2
    else
        echo "0 1" >/tmp/wlt_t2
        echo "  FAIL  second acquire returned $rc, expected 1"
    fi
)
read P F </tmp/wlt_t2; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  second acquire refused with exit 1\n"
rm -rf "$T2"

echo "==> Test 3: release removes lockfile (and is idempotent)"
T3="$(new_tmp)"
(
    cd "$T3"
    bash "$LOCK_SCRIPT" acquire t3 >/dev/null
    bash "$LOCK_SCRIPT" release
    if [ ! -f .worktree-lock ]; then
        echo "1 0" >/tmp/wlt_t3a
    else
        echo "0 1" >/tmp/wlt_t3a
    fi
    bash "$LOCK_SCRIPT" release  # second time — must not fail
    rc=$?
    echo "$rc" >/tmp/wlt_t3b
)
read P F </tmp/wlt_t3a; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  release removed lockfile\n"
rc2=$(cat /tmp/wlt_t3b)
if [ "$rc2" = "0" ]; then PASS=$((PASS + 1)); printf "  PASS  release is idempotent (exit 0)\n";
else FAIL=$((FAIL + 1)); printf "  FAIL  idempotent release exit=%s\n" "$rc2"; fi
rm -rf "$T3"

echo "==> Test 4: WORLDVIEW_DISABLE_WORKTREE_LOCK=1 is a no-op"
T4="$(new_tmp)"
(
    cd "$T4"
    export WORLDVIEW_DISABLE_WORKTREE_LOCK=1
    bash "$LOCK_SCRIPT" acquire t4
    rc=$?
    # Must NOT create a lockfile when opt-out is set.
    if [ ! -f .worktree-lock ] && [ "$rc" = "0" ]; then
        echo "1 0" >/tmp/wlt_t4
    else
        echo "0 1" >/tmp/wlt_t4
        echo "  FAIL  rc=$rc lockfile_exists=$([ -f .worktree-lock ] && echo y || echo n)"
    fi
)
read P F </tmp/wlt_t4; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  opt-out env var bypasses lock\n"
rm -rf "$T4"

echo "==> Test 5: stale lock (pid not alive) — acquire clobbers and succeeds"
T5="$(new_tmp)"
(
    cd "$T5"
    # 999999 is overwhelmingly likely to be a dead pid.
    cat >.worktree-lock <<'EOF'
{"pid": 999999, "agent_id": "ghost", "started_at": "2026-01-01T00:00:00Z", "branch": "main"}
EOF
    bash "$LOCK_SCRIPT" acquire newcomer
    rc=$?
    # Verify our pid replaced the stale one.
    new_pid=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' .worktree-lock | head -1)
    if [ "$rc" = "0" ] && [ "$new_pid" != "999999" ]; then
        echo "1 0" >/tmp/wlt_t5
    else
        echo "0 1" >/tmp/wlt_t5
        echo "  FAIL  rc=$rc new_pid=$new_pid"
    fi
)
read P F </tmp/wlt_t5; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  stale lock clobbered\n"
rm -rf "$T5"

rm -f /tmp/wlt_t1 /tmp/wlt_t2 /tmp/wlt_t3a /tmp/wlt_t3b /tmp/wlt_t4 /tmp/wlt_t5

echo
echo "==================================="
printf "Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "==================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
