#!/usr/bin/env bash
# scripts/worktree_lock.sh — PLAN-0107 D-2
#
# Filesystem-level mutex for a single git checkout. Prevents two Claude sessions
# (or a Claude session + a manual terminal) from concurrently mutating the
# worktree. Writes a JSON sidecar file `.worktree-lock` at the worktree root.
#
# Lock semantics (TTL-based freshness — the primary signal):
#   - A lock is HELD if (now - started_at) < LOCK_TTL_SECONDS
#   - A lock is STALE if older than LOCK_TTL_SECONDS  → safe to clobber
#   - PID-liveness is a SECONDARY safety net: if the recorded pid is still
#     alive we always refuse, even past the TTL (catches long-running daemons).
#
# Rationale: $$ in bash is the subshell pid which dies the moment the script
# exits. Consecutive `bash worktree_lock.sh acquire` calls (the normal case
# under Claude Code's tool harness) would *all* see dead pids and treat
# every prior lock as stale — making the lock a no-op in practice. TTL
# freshness fixes this: the next call sees a young `started_at` and refuses.
#
# Subcommands:
#   acquire [agent_id]    — create lock; refuse if a fresh peer lock exists
#   release               — delete lock (idempotent)
#   check                 — exit 0 held, 1 absent, 2 stale (past TTL, pid dead)
#   heartbeat             — refresh started_at to NOW (keeps lock alive)
#   check_for_commit      — pre-commit hook entry point (PLAN-0108 Wave C);
#                           refuses (exit 1) when a fresh foreign-pid lock
#                           is present; exits 0 otherwise. Designed to be
#                           wired into `.pre-commit-config.yaml` as a
#                           `local` hook.
#   autonomous_heartbeat  — daemon mode (PLAN-0108 Wave D). Loops every
#                           TTL/3 seconds calling `heartbeat`. Exits when
#                           the lockfile disappears or a SIGTERM/INT is
#                           received. Pure bash — safe to background.
#
# Env knobs:
#   WORLDVIEW_DISABLE_WORKTREE_LOCK=1   no-op every subcommand
#   WORLDVIEW_WORKTREE_LOCK_TTL=<sec>   override TTL (default 1800 = 30 min)
#
# Long-running orchestrators (PLAN-0108 Wave D usage):
#   bash scripts/worktree_lock.sh acquire orchestrator-name
#   bash scripts/worktree_lock.sh autonomous_heartbeat &
#   HB_PID=$!
#   trap "kill $HB_PID 2>/dev/null; bash scripts/worktree_lock.sh release" EXIT

set -euo pipefail

LOCK_FILE=".worktree-lock"
LOCK_TTL_SECONDS="${WORLDVIEW_WORKTREE_LOCK_TTL:-1800}"

if [ "${WORLDVIEW_DISABLE_WORKTREE_LOCK:-0}" = "1" ]; then
    exit 0
fi

cmd="${1:-}"
agent_id="${2:-manual}"

read_field() {
    # Extract a string field (e.g. "started_at": "...") from the JSON lockfile
    # without depending on jq. Returns empty string if not found.
    local key="$1"
    [ -f "$LOCK_FILE" ] || return 1
    sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$LOCK_FILE" | head -n 1
}

read_pid() {
    # Numeric field — separate extractor (no surrounding quotes).
    [ -f "$LOCK_FILE" ] || return 1
    sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$LOCK_FILE" | head -n 1
}

pid_alive() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Convert an ISO-8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ) to epoch seconds.
# Tries GNU `date -d`, then BSD/macOS `date -j -f`, then python3 as fallback.
iso_to_epoch() {
    local iso="$1"
    [ -z "$iso" ] && { echo 0; return; }
    if date -u -d "$iso" +%s >/dev/null 2>&1; then
        date -u -d "$iso" +%s
        return
    fi
    if date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s >/dev/null 2>&1; then
        date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s
        return
    fi
    python3 -c "import sys,datetime;print(int(datetime.datetime.strptime(sys.argv[1],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()))" "$iso" 2>/dev/null || echo 0
}

lock_age_seconds() {
    # Returns the lock's age in seconds (now - started_at). Empty/missing
    # started_at yields a very large number (treated as stale).
    local started epoch_started epoch_now
    started="$(read_field started_at || true)"
    if [ -z "$started" ]; then
        echo 999999999
        return
    fi
    epoch_started="$(iso_to_epoch "$started")"
    epoch_now="$(date -u +%s)"
    echo $(( epoch_now - epoch_started ))
}

write_lock() {
    local branch started
    # Run rev-parse with stderr+stdout merged then suppress; on failure the
    # captured stdout may still contain a partial "HEAD" line, so explicitly
    # fall back to "unknown" on non-zero exit.
    if branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" && [ -n "$branch" ]; then
        :
    else
        branch="unknown"
    fi
    # Strip any embedded newlines defensively (git sometimes prints multi-line).
    branch="$(printf '%s' "$branch" | tr -d '\n\r')"
    started="$(date -u +%FT%TZ)"
    cat >"$LOCK_FILE" <<EOF
{"pid": $$, "agent_id": "$agent_id", "started_at": "$started", "branch": "$branch"}
EOF
}

cmd_check() {
    if [ ! -f "$LOCK_FILE" ]; then
        return 1
    fi
    local age pid
    age="$(lock_age_seconds)"
    pid="$(read_pid || true)"
    if [ "$age" -lt "$LOCK_TTL_SECONDS" ]; then
        return 0
    fi
    # Past TTL — but a live pid still wins (daemon case).
    if pid_alive "$pid"; then
        return 0
    fi
    return 2
}

cmd_acquire() {
    if [ -f "$LOCK_FILE" ]; then
        local existing_pid existing_agent existing_started age
        existing_pid="$(read_pid || true)"
        existing_agent="$(read_field agent_id || true)"
        existing_started="$(read_field started_at || true)"
        age="$(lock_age_seconds)"

        # Primary check: TTL freshness. Young lock → refuse.
        if [ "$age" -lt "$LOCK_TTL_SECONDS" ]; then
            cat >&2 <<EOF
worktree_lock: refused — another session holds the lock (fresh by TTL).
  lockfile:    $(pwd)/$LOCK_FILE
  holder:      agent=$existing_agent pid=$existing_pid
  started_at:  $existing_started (age=${age}s, ttl=${LOCK_TTL_SECONDS}s)
  contents:    $(cat "$LOCK_FILE")
To override (only if you are CERTAIN no peer session is active):
  bash scripts/worktree_lock.sh release
Or opt out of the lock entirely for this shell:
  export WORLDVIEW_DISABLE_WORKTREE_LOCK=1
EOF
            exit 1
        fi

        # Secondary check: even past TTL, a live pid still wins.
        if pid_alive "$existing_pid"; then
            cat >&2 <<EOF
worktree_lock: refused — lock past TTL but holder pid is still alive.
  lockfile:    $(pwd)/$LOCK_FILE
  holder:      agent=$existing_agent pid=$existing_pid (ALIVE)
  started_at:  $existing_started (age=${age}s, ttl=${LOCK_TTL_SECONDS}s)
To override:
  bash scripts/worktree_lock.sh release
EOF
            exit 1
        fi

        # Stale lock — log and clobber.
        echo "worktree_lock: stale-lock-clobber (age=${age}s >= ttl=${LOCK_TTL_SECONDS}s, pid=$existing_pid dead) prior_agent=$existing_agent" >&2
        rm -f "$LOCK_FILE"
    fi
    write_lock
    return 0
}

cmd_release() {
    rm -f "$LOCK_FILE"
    return 0
}

cmd_heartbeat() {
    # Refresh started_at to NOW without touching agent_id/branch/pid. Used by
    # long-running orchestrators to keep their lock fresh past TTL.
    if [ ! -f "$LOCK_FILE" ]; then
        echo "worktree_lock: heartbeat — no lockfile present" >&2
        return 1
    fi
    local now
    now="$(date -u +%FT%TZ)"
    # In-place rewrite of "started_at": "..." → "started_at": "$now"
    # Use a tmpfile to stay portable across BSD/GNU sed.
    local tmp
    tmp="$(mktemp -t wlock.XXXXXX)"
    sed "s/\"started_at\"[[:space:]]*:[[:space:]]*\"[^\"]*\"/\"started_at\": \"$now\"/" "$LOCK_FILE" >"$tmp"
    mv "$tmp" "$LOCK_FILE"
    return 0
}

cmd_check_for_commit() {
    # PLAN-0108 Wave C — pre-commit hook integration.
    # Refuses (exit 1) when a fresh lock owned by a foreign pid is present.
    # "Foreign" = pid that is NOT the current shell's parent process chain,
    # detected conservatively by comparing to $PPID. The point is to flag the
    # case where a SECOND session tries to commit while a different session
    # already owns the lock — not to block the lock holder from committing.
    if [ ! -f "$LOCK_FILE" ]; then
        return 0
    fi
    local age existing_pid existing_agent existing_started
    age="$(lock_age_seconds)"
    existing_pid="$(read_pid || true)"
    existing_agent="$(read_field agent_id || true)"
    existing_started="$(read_field started_at || true)"

    # Stale lock — let the commit through; another `acquire` would clobber it
    # anyway, and we don't want to block legitimate work on dead-session debris.
    if [ "$age" -ge "$LOCK_TTL_SECONDS" ] && ! pid_alive "$existing_pid"; then
        return 0
    fi

    # If the lock's pid matches the current shell's parent (the pre-commit
    # framework process), this is the lock holder committing — allow.
    if [ -n "$existing_pid" ] && [ "$existing_pid" = "$PPID" ]; then
        return 0
    fi

    cat >&2 <<EOF
worktree_lock: REFUSED — commit blocked by foreign lock holder.
  lockfile:   $(pwd)/$LOCK_FILE
  holder:     agent=$existing_agent pid=$existing_pid
  started_at: $existing_started (age=${age}s, ttl=${LOCK_TTL_SECONDS}s)
A peer session owns this worktree. Wait for it to release or override:
  bash scripts/worktree_lock.sh release
Or opt out for this shell:
  export WORLDVIEW_DISABLE_WORKTREE_LOCK=1
EOF
    return 1
}

cmd_autonomous_heartbeat() {
    # PLAN-0108 Wave D — daemon-style heartbeat.
    # Loops every TTL/3 seconds, calling cmd_heartbeat. Exits cleanly when:
    #   - the lockfile disappears (release happened)
    #   - SIGTERM / SIGINT received (trap fires)
    # Interval defaults to TTL/3 so we refresh well before stale-out.
    local interval=$(( LOCK_TTL_SECONDS / 3 ))
    [ "$interval" -lt 1 ] && interval=1

    # Clean exit on signals — no message to stderr to keep background usage tidy.
    trap 'exit 0' TERM INT

    while true; do
        if [ ! -f "$LOCK_FILE" ]; then
            # Lock was released — daemon's job is done.
            return 0
        fi
        # Refresh started_at. Suppress "no lockfile" errors that may race
        # with a concurrent release.
        cmd_heartbeat 2>/dev/null || true
        # `sleep` is interrupted by signals and returns ~128+signo; the trap
        # will fire and exit before the next iteration.
        sleep "$interval"
    done
}

case "$cmd" in
    acquire)              cmd_acquire ;;
    release)              cmd_release ;;
    check)                cmd_check ;;
    heartbeat)            cmd_heartbeat ;;
    check_for_commit)     cmd_check_for_commit ;;
    autonomous_heartbeat) cmd_autonomous_heartbeat ;;
    *)
        cat >&2 <<EOF
usage: $0 {acquire [agent_id]|release|check|heartbeat|check_for_commit|autonomous_heartbeat}

  acquire [agent_id]    create lock; refuse if a fresh peer lock exists
                        (freshness = age < \$WORLDVIEW_WORKTREE_LOCK_TTL,
                         default 1800s). Past-TTL locks are clobbered unless
                         their pid is still alive.
  release               delete lockfile (idempotent)
  check                 exit 0 held / 1 absent / 2 stale (past TTL, pid dead)
  heartbeat             refresh started_at to NOW (keeps a long-running
                        session's lock fresh past TTL)
  check_for_commit      PLAN-0108 Wave C pre-commit hook entry point.
                        Exit 1 when a fresh foreign-pid lock exists; 0 else.
  autonomous_heartbeat  PLAN-0108 Wave D daemon mode. Loops every TTL/3s,
                        calling heartbeat. Exits when lockfile is removed
                        or on SIGTERM/INT.

env:
  WORLDVIEW_DISABLE_WORKTREE_LOCK=1   skip every subcommand
  WORLDVIEW_WORKTREE_LOCK_TTL=<sec>   override TTL (default 1800)
EOF
        exit 64
        ;;
esac
