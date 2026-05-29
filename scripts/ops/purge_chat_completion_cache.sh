#!/usr/bin/env bash
# F-LIVE-NEW-003 — purge rag-chat completion cache.
#
# WHY: the completion cache stores fully-rendered LLM answers keyed by a
# hash of (message, thread_id, resolver_version). When resolver-gate
# semantics change (e.g. the SpaceX/Delta/Shell stop-word false-positive
# fix) ALL previously-cached answers built under the old gates are
# semantically stale. The resolver_version segment in completion_cache.py
# already auto-evicts those keys on next READ — this script forces a
# one-shot flush so the next user request issues a fresh LLM call instead
# of (silently) waiting for read-driven eviction to drain the keyspace.
#
# Cache lives in: valkey DB **0** (rag-chat default; see
# services/rag-chat/configs/docker.env: RAG_CHAT_VALKEY_URL=redis://valkey:6379/0).
#
# Usage (from project root, with platform up):
#   ./scripts/ops/purge_chat_completion_cache.sh
#
# Or against a remote valkey:
#   VALKEY_HOST=valkey.prod.local VALKEY_DB=0 ./scripts/ops/purge_chat_completion_cache.sh
#
# Safe to re-run — only the rag-chat completion-cache keys are removed.
# Other rag-chat keys (HyDE cache, briefing cache, deploy token, rate
# limit windows) are NOT touched.

set -euo pipefail

VALKEY_HOST="${VALKEY_HOST:-valkey}"
VALKEY_PORT="${VALKEY_PORT:-6379}"
VALKEY_DB="${VALKEY_DB:-0}"

# Match every completion-cache entry across past + present key versions.
# Mirrors the pattern used by the deploy-token flush in app.py.
PATTERN="rag:v*:completion:*"

# Where to find valkey-cli — prefer host install, then exec into the
# valkey container if the host has no client.
if command -v valkey-cli >/dev/null 2>&1; then
    CMD=(valkey-cli -h "$VALKEY_HOST" -p "$VALKEY_PORT" -n "$VALKEY_DB")
elif command -v redis-cli >/dev/null 2>&1; then
    CMD=(redis-cli -h "$VALKEY_HOST" -p "$VALKEY_PORT" -n "$VALKEY_DB")
elif command -v docker >/dev/null 2>&1; then
    # Fallback: run valkey-cli inside the valkey container.
    CMD=(docker exec valkey valkey-cli -n "$VALKEY_DB")
else
    echo "ERROR: no valkey-cli, redis-cli, or docker available" >&2
    exit 1
fi

echo "Scanning for keys matching ${PATTERN} on ${VALKEY_HOST}:${VALKEY_PORT}/db${VALKEY_DB} ..."

# Use SCAN + DEL pipeline (not KEYS — KEYS blocks the server on large
# keyspaces; SCAN streams in chunks).
CURSOR=0
TOTAL=0
while :; do
    # SCAN returns (cursor, [keys...]); xargs DEL each batch.
    OUT=$("${CMD[@]}" SCAN "$CURSOR" MATCH "$PATTERN" COUNT 500)
    CURSOR=$(echo "$OUT" | head -n1)
    KEYS=$(echo "$OUT" | tail -n +2)
    if [ -n "$KEYS" ]; then
        COUNT=$(echo "$KEYS" | wc -l | tr -d ' ')
        # shellcheck disable=SC2086
        echo "$KEYS" | xargs "${CMD[@]}" DEL >/dev/null
        TOTAL=$((TOTAL + COUNT))
    fi
    if [ "$CURSOR" = "0" ]; then
        break
    fi
done

echo "Purged ${TOTAL} completion-cache key(s)."
