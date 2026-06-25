#!/usr/bin/env bash
# PLAN-0107 D-2: install the worktree-lock pre-commit hook prelude.
# Idempotent. Preserves any existing hook content (e.g. the pre-commit framework
# dispatcher); prepends the lock check at the top.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="${REPO_ROOT}/.git/hooks/pre-commit"
MARKER="# PLAN-0107 D-2: worktree-lock check"

if [ -f "$HOOK" ] && grep -qF "$MARKER" "$HOOK"; then
    echo "OK: worktree-lock hook already installed at $HOOK"
    exit 0
fi

PRELUDE='#!/usr/bin/env bash
# PLAN-0107 D-2: worktree-lock check — block commits while another session holds the lock.
# Opt out via WORLDVIEW_DISABLE_WORKTREE_LOCK=1.
__wv_worktree_lock_check() {
    if [ -n "${WORLDVIEW_DISABLE_WORKTREE_LOCK:-}" ]; then
        return 0
    fi
    if [ ! -x scripts/worktree_lock.sh ]; then
        return 0
    fi
    bash scripts/worktree_lock.sh check >/dev/null 2>&1
    local rc=$?
    if [ "$rc" = "1" ] || [ "$rc" = "2" ]; then
        return 0
    fi
    local holder_pid
    holder_pid="$(python3 -c "import json,sys; print(json.load(open('"'"'.worktree-lock'"'"'))['"'"'pid'"'"'])" 2>/dev/null || echo 0)"
    if [ "$holder_pid" = "$$" ] || [ "$holder_pid" = "$PPID" ]; then
        return 0
    fi
    echo "REFUSED: worktree lock held by another session (holder pid=$holder_pid)" >&2
    echo "Override: WORLDVIEW_DISABLE_WORKTREE_LOCK=1 git commit ..." >&2
    return 1
}
__wv_worktree_lock_check || exit 1
'

if [ -f "$HOOK" ]; then
    # Existing hook (probably the pre-commit framework dispatcher). Prepend
    # our prelude AFTER the shebang line if it has one; otherwise at the top.
    EXISTING="$(cat "$HOOK")"
    if head -1 "$HOOK" | grep -q "^#!"; then
        # strip the existing shebang since our prelude has its own
        EXISTING="$(tail -n +2 "$HOOK")"
    fi
    printf '%s\n%s\n' "$PRELUDE" "$EXISTING" > "$HOOK"
else
    printf '%s\n' "$PRELUDE" > "$HOOK"
fi
chmod +x "$HOOK"
echo "INSTALLED: worktree-lock prelude added to $HOOK"
