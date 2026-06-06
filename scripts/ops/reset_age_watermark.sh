#!/usr/bin/env bash
# PLAN-0093 B-1 T-B-1-04: reset all AGE shadow-sync watermarks.
#
# Deletes the four Valkey keys used by AgeSyncWorker:
#   - s7:age:sync:watermark                  (legacy single key — kept for back-compat)
#   - s7:age:sync:watermark:entities         (per-phase, PLAN-0093 B-1)
#   - s7:age:sync:watermark:relations        (per-phase)
#   - s7:age:sync:watermark:temporal_events  (per-phase)
#
# When to run:
#   * After deploying the PLAN-0093 B-1 label bootstrap so the next worker
#     cycle does a full resync now that ``TemporalEvent`` + ``EVENT_EXPOSES``
#     labels exist.
#   * After any schema/label change that requires a full AGE rebuild.
#   * When ``age_sync_phase_stalled_total`` keeps incrementing for a phase
#     even though new rows are visible in the source table.
#
# What happens:
#   The next AgeSyncWorker run reads epoch (1970-01-01) for every missing key
#   and re-MERGEs the full corresponding table.  AGE MERGE is idempotent so
#   re-running over already-synced rows is safe (no duplicates).
#
# Risk:
#   None — the operation is read-only against Postgres and idempotent against AGE.
#   The first run after a reset will take longer than usual (full scan + MERGE).
set -euo pipefail

CONTAINER="${VALKEY_CONTAINER:-worldview-valkey-1}"

docker exec "${CONTAINER}" valkey-cli DEL \
  s7:age:sync:watermark \
  s7:age:sync:watermark:entities \
  s7:age:sync:watermark:relations \
  s7:age:sync:watermark:temporal_events
