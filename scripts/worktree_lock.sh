#!/usr/bin/env bash
# scripts/worktree_lock.sh — PLAN-0107 D-2
#
# Filesystem-level mutex for a single git checkout. Prevents two Claude sessions
# (or a Claude session + a manual terminal) from concurrently mutating the
# worktree. Writes a JSON sidecar file `.worktree-lock` at the worktree root.
#
# Subcommands:
#   acquire [agent_id]   — create lock; refuse if a peer pid is alive
#   release              — delete lock (idempotent)
#   check                — exit 0 alive, 1 absent, 2 stale (pid dead)
#
# Opt-out: WORLDVIEW_DISABLE_WORKTREE_LOCK=1 makes every subcommand a no-op.

set -euo pipefail

LOCK_FILE=".worktree-lock"

if [ "${WORLDVIEW_DISABLE_WORKTREE_LOCK:-0}" = "1" ]; then
    exit 0
fi

cmd="${1:-}"
agent_id="${2:-manual}"

read_pid() {
    # Extract "pid": N from the JSON lockfile without requiring jq.
    [ -f "$LOCK_FILE" ] || return 1
    sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$LOCK_FILE" | head -n 1
}

pid_alive() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

cmd_check() {
    local pid
    if [ ! -f "$LOCK_FILE" ]; then
        return 1
    fi
    pid="$(read_pid || true)"
    if pid_alive "$pid"; then
        return 0
    fi
    return 2
}

cmd_acquire() {
    if [ -f "$LOCK_FILE" ]; then
        local existing_pid
        existing_pid="$(read_pid || true)"
        if pid_alive "$existing_pid"; then
            cat >&2 <<EOF
worktree_lock: refused — another session holds the lock.
  lockfile: $(pwd)/$LOCK_FILE
  holder pid: $existing_pid (alive)
  contents:   $(cat "$LOCK_FILE")
To override (only if you are CERTAIN no peer session is active):
  rm $LOCK_FILE
Or opt out of the lock entirely for this shell:
  export WORLDVIEW_DISABLE_WORKTREE_LOCK=1
EOF
            exit 1
        fi
        # Stale lock — clobber.
        rm -f "$LOCK_FILE"
    fi
    local branch started
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    started="$(date -u +%FT%TZ)"
    cat >"$LOCK_FILE" <<EOF
{"pid": $$, "agent_id": "$agent_id", "started_at": "$started", "branch": "$branch"}
EOF
    return 0
}

cmd_release() {
    rm -f "$LOCK_FILE"
    return 0
}

case "$cmd" in
    acquire) cmd_acquire ;;
    release) cmd_release ;;
    check)   cmd_check ;;
    *)
        echo "usage: $0 {acquire [agent_id]|release|check}" >&2
        exit 64
        ;;
esac
