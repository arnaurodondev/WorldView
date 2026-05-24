#!/usr/bin/env bash
# PLAN-0093 F-2 driver — execute the F-1 PREPARE pass against live databases
# and print every drift error with file:line so an engineer can fix them.
#
# Usage:
#   INTELLIGENCE_DB_URL_TEST=postgresql://user:pass@host:5432/intelligence_db \
#   NLP_DB_URL_TEST=postgresql://user:pass@host:5432/nlp_db \
#   scripts/run_repository_prepare_audit.sh
#
# What it does
#   1. Confirms both DB URLs are set (skips otherwise so CI doesn't false-fail).
#   2. Runs alembic upgrade head against both DBs to guarantee HEAD schema
#      (R32 — never assume migration head).
#   3. Runs the PREPARE pass test (tests/architecture/test_repository_sql_prepare.py).
#   4. Exits non-zero if any repository SQL fails PREPARE; the test failure
#      message lists every offending file:line and the Postgres error.
#
# F-LOG-MIGRATION-001 — the audit observed ~10/min "column does not exist"
# errors. The PREPARE pass is the discovery mechanism: each failure produced
# by this script IS a F-2 work-item.
#
# Static-analysis triage (2026-05-23, F-2 commit):
#   The audit listed six columns reported missing in Postgres logs. Static
#   grep across all repository SQL did not surface clear column-reference
#   bugs for these names; the references fall into three buckets:
#
#     - gliner_score   → only used as SELECT alias and JSONB key (no column ref).
#     - updated_at     → real column on canonical_entities/relations/temporal_events,
#                        and on AGE vertices. AGE Cypher errors propagate as
#                        Postgres "column does not exist" when a vertex
#                        property is missing — out of F-1 PREPARE scope
#                        (skip-listed; see test_repository_sql_prepare.py).
#     - entity_provisional → real column on relation_evidence_raw. All static
#                        references match the schema.
#     - embedding_type → no static references in the codebase at all; likely
#                        an ORM/dynamic-SQL artifact only surfaceable at
#                        runtime PREPARE.
#     - published_at   → real column on document_source_metadata. All static
#                        references match the schema.
#     - label          → real column on market_data.screen_field_metadata.
#                        The audit's hits are most likely AGE/Cypher MATCH
#                        property errors (see F-DB-009: AGE label case gotcha).
#
#   Conclusion: the per-column F-2 patches the plan anticipated will only
#   surface once this script runs against a live HEAD-migrated DB. The F-1
#   integration test (scoped to plain SQL, skipping AGE/Cypher) is the
#   correct discovery engine; this script makes the run reproducible.

set -euo pipefail

if [[ -z "${INTELLIGENCE_DB_URL_TEST:-}" ]] && [[ -z "${INTELLIGENCE_DB_URL:-}" ]]; then
  echo "ERROR: INTELLIGENCE_DB_URL_TEST (or INTELLIGENCE_DB_URL) must be set." >&2
  exit 2
fi
if [[ -z "${NLP_DB_URL_TEST:-}" ]] && [[ -z "${NLP_DB_URL:-}" ]]; then
  echo "ERROR: NLP_DB_URL_TEST (or NLP_DB_URL) must be set." >&2
  exit 2
fi

# Resolve repo root (this script lives in scripts/).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
cd "${REPO_ROOT}"

# Use the project venv if available; fall back to whatever python is on PATH.
if [[ -f ".venv312/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv312/bin/activate
fi

echo "=== PLAN-0093 F-2 — running repository SQL PREPARE audit ==="
echo "    intelligence_db: ${INTELLIGENCE_DB_URL_TEST:-${INTELLIGENCE_DB_URL}}"
echo "    nlp_db        : ${NLP_DB_URL_TEST:-${NLP_DB_URL}}"
echo

# Step 1: HEAD-migrate both DBs (the F-1 fixture also does this, but doing it
# here gives the operator a clear log line if migrations fail BEFORE the
# (large) PREPARE pass starts).
echo "=== Step 1/2 — alembic upgrade head ==="
INTELLIGENCE_DB_URL="${INTELLIGENCE_DB_URL_TEST:-${INTELLIGENCE_DB_URL}}" \
  alembic -c services/intelligence-migrations/alembic.ini upgrade head

NLP_DB_URL="${NLP_DB_URL_TEST:-${NLP_DB_URL}}" \
  alembic -c services/nlp-pipeline/alembic.ini upgrade head

# Step 2: run the PREPARE pass. -v so each failing file:line is visible.
echo
echo "=== Step 2/2 — PREPARE every repository SQL ==="
python -m pytest \
  tests/architecture/test_repository_sql_prepare.py \
  -v \
  --no-header \
  -k "prepares_successfully or catches_known_column_typo"
