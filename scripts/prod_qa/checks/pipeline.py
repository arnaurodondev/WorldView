"""Outcome-based pipeline liveness (v4) — freshness by OUTPUT, not by lag.

Consumer lag can look healthy (offsets committing) while a worker silently
persists nothing — the D1 "stamps success, writes nothing" class — or lag can be
huge yet the pipeline is fine (a draining backfill). Counting the ROWS each stage
actually produced in the last 24h is the signal that most directly answers "is
this stage still turning input into output?", and it collapses to ~0 the moment a
worker wedges regardless of what its offsets say.

Each floor sits far below the observed 24h throughput (calibrated 2026-07-16), so
these WARN on a genuine output collapse without flapping on normal churn. Kept
SOFT (WARN): a single quiet window is worth surfacing, not exit-code-failing, and
NER-mentions/24h already has its own HARD gate in the nlp layer.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx

SVC = "pipeline"

# (db, key, sql, floor, human label) — one query per DB, batched per DB below.
_STREAMS = [
    ("content_store_db", "documents ingested", "documents", "ingested_at", T.PIPE_DOCS_24H_FLOOR),
    ("intelligence_db", "relations created", "relations", "created_at", T.PIPE_RELATIONS_24H_FLOOR),
    ("nlp_db", "chunk embeddings created", "chunk_embeddings", "created_at", T.PIPE_EMBEDDINGS_24H_FLOOR),
    (
        "market_data_db",
        "prediction snapshots written",
        "prediction_market_snapshots",
        "snapshot_at",
        T.PIPE_PRED_SNAPS_24H_FLOOR,
    ),
]


def run(ctx: Ctx) -> None:
    R = ctx.report
    # Group queries by DB so each DB is a single batched exec (round-trip cost).
    by_db: dict[str, dict[str, str]] = {}
    meta: dict[str, tuple[str, int]] = {}
    for db, label, table, ts_col, floor in _STREAMS:
        key = f"{db}:{table}"
        by_db.setdefault(db, {})[key] = (
            f"SELECT count(*) FROM {table} WHERE {ts_col} > now() - interval '24 hours'"
        )
        meta[key] = (label, floor)

    for db, queries in by_db.items():
        res = H.psql_many(db, queries)
        for key, val in res.items():
            label, floor = meta[key]
            n = H.as_int(val, -1)
            if n < 0:
                R.warn(SVC, f"{label} / 24h", f"query failed / table absent ({db})")
                continue
            R.floor(SVC, f"{label} / 24h (worker producing output)", n, floor, soft=True)
