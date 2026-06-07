#!/usr/bin/env bash
# Unit tests for scripts/worktree_lock.sh (PLAN-0107 D-2).
# Plain bash with a tiny assert helper; runnable as:
#   bash scripts/tests/test_worktree_lock.sh

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK_SCRIPT="$REPO_ROOT/scripts/worktree_lock.sh"

PASS=0
FAIL=0

# Each test runs in a temp dir (isolated worktree) so we don't pollute the real lock.
new_tmp() {
    local d
    d="$(mktemp -d -t worktree-lock-test.XXXXXX)"
    (cd "$d" && git init -q .)
    echo "$d"
}

# Portable "now minus N seconds" as ISO-8601 UTC.
iso_minus() {
    local sec="$1"
    if date -u -d "@$(( $(date -u +%s) - sec ))" +%FT%TZ >/dev/null 2>&1; then
        date -u -d "@$(( $(date -u +%s) - sec ))" +%FT%TZ
    else
        # BSD / macOS date
        date -u -r "$(( $(date -u +%s) - sec ))" +%FT%TZ
    fi
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
    # `acquire` from the previous subshell wrote $$ of a now-dead bash. The
    # lockfile's started_at is fresh (well within TTL), so `check` must
    # still return 0 (held by TTL freshness — the whole point of D-2 fix).
    bash "$LOCK_SCRIPT" check
    rc_check=$?
    if [ "$rc_check" = "0" ]; then p=$((p+1)); printf "  PASS  check exit 0 while fresh-by-TTL\n"; else f=$((f+1)); printf "  FAIL  check exit=%s\n" "$rc_check"; fi
    echo "$p $f" >/tmp/wlt_t1
)
read P F </tmp/wlt_t1; PASS=$((PASS + P)); FAIL=$((FAIL + F))
rm -rf "$T1"

echo "==> Test 2: second acquire is refused when a fresh peer lock exists (no live pid required)"
T2="$(new_tmp)"
(
    cd "$T2"
    # Write a fresh lock manually with a dead pid — TTL freshness alone
    # must be enough to refuse. This is the regression test for the D-2
    # PID-liveness bug: previously this lock would be treated as stale
    # because pid 999999 is dead.
    now_iso="$(date -u +%FT%TZ)"
    cat >.worktree-lock <<EOF
{"pid": 999999, "agent_id": "peer", "started_at": "$now_iso", "branch": "main"}
EOF
    set +e
    bash "$LOCK_SCRIPT" acquire intruder 2>/dev/null
    rc=$?
    set -e
    if [ "$rc" = "1" ]; then
        echo "1 0" >/tmp/wlt_t2
    else
        echo "0 1" >/tmp/wlt_t2
        echo "  FAIL  second acquire returned $rc, expected 1"
    fi
)
read P F </tmp/wlt_t2; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  fresh-lock refusal works without live pid\n"
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

echo "==> Test 5: stale lock (past TTL + pid dead) — acquire clobbers and succeeds"
T5="$(new_tmp)"
(
    cd "$T5"
    # Old started_at (2026-01-01 is ~5 months in the past relative to today)
    # plus dead pid 999999. Under default TTL (1800s) this must be clobbered.
    cat >.worktree-lock <<'EOF'
{"pid": 999999, "agent_id": "ghost", "started_at": "2026-01-01T00:00:00Z", "branch": "main"}
EOF
    bash "$LOCK_SCRIPT" acquire newcomer 2>/dev/null
    rc=$?
    new_pid=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' .worktree-lock | head -1)
    if [ "$rc" = "0" ] && [ "$new_pid" != "999999" ]; then
        echo "1 0" >/tmp/wlt_t5
    else
        echo "0 1" >/tmp/wlt_t5
        echo "  FAIL  rc=$rc new_pid=$new_pid"
    fi
)
read P F </tmp/wlt_t5; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  stale lock (past TTL + dead pid) clobbered\n"
rm -rf "$T5"

echo "==> Test 6: TTL expiry — acquire succeeds on past-TTL lock even with a recent-but-old started_at"
T6="$(new_tmp)"
(
    cd "$T6"
    # 2 hours ago — well past default 1800s TTL.
    old_iso="$(iso_minus 7200)"
    cat >.worktree-lock <<EOF
{"pid": 999999, "agent_id": "yesterday", "started_at": "$old_iso", "branch": "main"}
EOF
    bash "$LOCK_SCRIPT" acquire newcomer 2>/dev/null
    rc=$?
    new_agent=$(sed -n 's/.*"agent_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    if [ "$rc" = "0" ] && [ "$new_agent" = "newcomer" ]; then
        echo "1 0" >/tmp/wlt_t6
    else
        echo "0 1" >/tmp/wlt_t6
        echo "  FAIL  rc=$rc new_agent=$new_agent"
    fi
)
read P F </tmp/wlt_t6; PASS=$((PASS + P)); FAIL=$((FAIL + F))
[ "$F" = "0" ] && printf "  PASS  past-TTL lock clobbered by newcomer\n"
rm -rf "$T6"

echo "==> Test 7: heartbeat refreshes started_at without changing other fields"
T7="$(new_tmp)"
(
    cd "$T7"
    bash "$LOCK_SCRIPT" acquire t7 >/dev/null
    before_started=$(sed -n 's/.*"started_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    before_agent=$(sed -n 's/.*"agent_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    before_pid=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' .worktree-lock | head -1)
    # Backdate so the refresh is observable.
    older_iso="$(iso_minus 600)"
    sed_in_place() {
        local tmp; tmp="$(mktemp)"
        sed "$1" .worktree-lock >"$tmp" && mv "$tmp" .worktree-lock
    }
    sed_in_place "s/\"started_at\"[[:space:]]*:[[:space:]]*\"[^\"]*\"/\"started_at\": \"$older_iso\"/"
    backdated=$(sed -n 's/.*"started_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    bash "$LOCK_SCRIPT" heartbeat
    rc=$?
    after_started=$(sed -n 's/.*"started_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    after_agent=$(sed -n 's/.*"agent_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    after_pid=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' .worktree-lock | head -1)
    p=0; f=0
    if [ "$rc" = "0" ]; then p=$((p+1)); printf "  PASS  heartbeat exit 0\n"; else f=$((f+1)); printf "  FAIL  heartbeat exit=%s\n" "$rc"; fi
    if [ "$after_started" != "$backdated" ]; then p=$((p+1)); printf "  PASS  started_at refreshed (was %s, now %s)\n" "$backdated" "$after_started"; else f=$((f+1)); printf "  FAIL  started_at not refreshed\n"; fi
    if [ "$after_agent" = "$before_agent" ] && [ "$after_pid" = "$before_pid" ]; then p=$((p+1)); printf "  PASS  agent_id+pid preserved\n"; else f=$((f+1)); printf "  FAIL  agent=%s pid=%s changed\n" "$after_agent" "$after_pid"; fi
    echo "$p $f" >/tmp/wlt_t7
)
read P F </tmp/wlt_t7; PASS=$((PASS + P)); FAIL=$((FAIL + F))
rm -rf "$T7"

echo "==> Test 8: autonomous_heartbeat refreshes started_at and exits on lock release (PLAN-0108 Wave D)"
T8="$(new_tmp)"
(
    cd "$T8"
    # Acquire lock so heartbeat has something to refresh.
    bash "$LOCK_SCRIPT" acquire t8 >/dev/null
    # Backdate started_at so the heartbeat refresh is observable.
    older_iso="$(iso_minus 600)"
    tmp="$(mktemp)"
    sed "s/\"started_at\"[[:space:]]*:[[:space:]]*\"[^\"]*\"/\"started_at\": \"$older_iso\"/" .worktree-lock >"$tmp" && mv "$tmp" .worktree-lock
    backdated=$(sed -n 's/.*"started_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    # Run autonomous_heartbeat with a short TTL so interval = TTL/3 = 1s.
    WORLDVIEW_WORKTREE_LOCK_TTL=3 bash "$LOCK_SCRIPT" autonomous_heartbeat &
    HB_PID=$!
    # Give it >1 interval to fire at least once.
    sleep 2
    after_started=$(sed -n 's/.*"started_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .worktree-lock | head -1)
    # Release the lock — daemon should detect missing file and exit cleanly.
    bash "$LOCK_SCRIPT" release
    # Wait up to 6s for the daemon to notice and exit. The interval is
    # TTL/3 = 1s, but the daemon may be in the middle of a sleep when we
    # release; give it ample room.
    for _ in 1 2 3 4 5 6; do
        if ! kill -0 "$HB_PID" 2>/dev/null; then break; fi
        sleep 1
    done
    if kill -0 "$HB_PID" 2>/dev/null; then
        # Daemon still running — fail (and clean up).
        kill "$HB_PID" 2>/dev/null
        wait "$HB_PID" 2>/dev/null
        echo "0 1" >/tmp/wlt_t8
        printf "  FAIL  autonomous_heartbeat did not exit after lock release\n"
    else
        wait "$HB_PID" 2>/dev/null
        # Verify started_at was refreshed (i.e. moved away from the backdate).
        if [ "$after_started" != "$backdated" ]; then
            echo "1 0" >/tmp/wlt_t8
            printf "  PASS  autonomous_heartbeat refreshed started_at and exited on release\n"
        else
            echo "0 1" >/tmp/wlt_t8
            printf "  FAIL  started_at was not refreshed (was %s, still %s)\n" "$backdated" "$after_started"
        fi
    fi
)
read P F </tmp/wlt_t8; PASS=$((PASS + P)); FAIL=$((FAIL + F))
rm -rf "$T8"

rm -f /tmp/wlt_t1 /tmp/wlt_t2 /tmp/wlt_t3a /tmp/wlt_t3b /tmp/wlt_t4 /tmp/wlt_t5 /tmp/wlt_t6 /tmp/wlt_t7 /tmp/wlt_t8

echo
echo "==================================="
printf "Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "==================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
