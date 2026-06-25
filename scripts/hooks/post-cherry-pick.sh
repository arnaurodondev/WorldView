#!/usr/bin/env bash
# Post-cherry-pick hook — runs the orphan-commit watchdog after a cherry-pick.
# PLAN-0107 D-4: detect parallel-session HEAD rewinds.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$SCRIPT_DIR/orphan_commit_check.sh" "$@"
