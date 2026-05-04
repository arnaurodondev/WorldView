#!/bin/bash
# check-api-drift.sh — Fail if the committed S9 OpenAPI spec has drifted from the live gateway.
#
# WHY THIS EXISTS: The committed infra/contracts/s9-openapi.json is the source of
# truth for generated TypeScript types. If the live S9 spec changes without
# regenerating types, the frontend will have stale type definitions.
#
# USAGE: Run after `make dev` in CI or locally.
#   bash scripts/check-api-drift.sh
#
# EXIT CODES:
#   0 — spec matches (no drift)
#   1 — drift detected — run `make generate-types` to regenerate types
#   2 — S9 is unreachable (CI may want to treat this as a warning, not hard failure)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMMITTED="${REPO_ROOT}/infra/contracts/s9-openapi.json"
S9_URL="${S9_BASE_URL:-http://localhost:8000}/openapi.json"

if [[ ! -f "${COMMITTED}" ]]; then
  echo "ERROR: committed spec not found at ${COMMITTED}"
  echo "Run: curl ${S9_URL} | python3 -m json.tool > ${COMMITTED}"
  exit 1
fi

# Fetch live spec — exit 2 (not 1) if S9 is unreachable so CI can distinguish
# "drift" from "service not running".
LIVE=$(curl -sf --max-time 10 "${S9_URL}" 2>/dev/null) || {
  echo "WARNING: S9 is unreachable at ${S9_URL} — skipping drift check"
  exit 2
}

# Normalise both copies through Python json.tool (removes formatting differences)
LIVE_NORMALISED=$(echo "${LIVE}" | python3 -m json.tool --sort-keys 2>/dev/null)
COMMITTED_NORMALISED=$(python3 -m json.tool --sort-keys < "${COMMITTED}" 2>/dev/null)

if [[ "${LIVE_NORMALISED}" != "${COMMITTED_NORMALISED}" ]]; then
  echo "DRIFT DETECTED: S9 OpenAPI spec has changed since last commit."
  echo ""
  echo "To fix:"
  echo "  1. curl ${S9_URL} | python3 -m json.tool > infra/contracts/s9-openapi.json"
  echo "  2. pnpm --filter worldview-web generate-types"
  echo "  3. Commit both files: infra/contracts/s9-openapi.json + apps/worldview-web/types/generated/api.ts"
  exit 1
fi

echo "OK: S9 OpenAPI spec is in sync with committed snapshot."
exit 0
