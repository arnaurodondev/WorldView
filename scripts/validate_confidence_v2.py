#!/usr/bin/env python3
"""PLAN-0109 W1 — dry-run validation of the Beta/subjective-logic confidence (v2).

Computes the v2 confidence over a sample of REAL relations + their evidence and
compares the resulting distribution against the currently-stored (v1) confidence.
Does NOT persist anything. Run inside the knowledge-graph container:

    docker exec worldview-knowledge-graph-scheduler-1 \
        python /app/scripts/validate_confidence_v2.py
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter

import asyncpg  # type: ignore[import-untyped]
from knowledge_graph.domain.confidence import (
    EvidenceInput,
    compute_confidence_beta,
)
from knowledge_graph.domain.enums import SemanticMode

_KAPPA = 2.0
_SIGNAL_FLOOR = 0.1
_DEFAULT_TRUST = 0.5
_SAMPLE = 2000


def _dsn() -> str:
    url = os.environ["KNOWLEDGE_GRAPH_DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _bucket(x: float) -> str:
    return f"{int(x * 10) / 10:.1f}-{int(x * 10) / 10 + 0.1:.1f}"


async def main() -> None:
    conn = await asyncpg.connect(_dsn())
    trust = {
        r["source_type"]: float(r["trust_weight"])
        for r in await conn.fetch("SELECT source_type, trust_weight FROM source_trust_weights")
    }

    rels = await conn.fetch(
        """
        SELECT relation_id, subject_entity_id, object_entity_id, canonical_type,
               semantic_mode, decay_alpha, base_confidence, confidence
        FROM relations
        WHERE confidence IS NOT NULL
        ORDER BY relation_id
        LIMIT $1
        """,
        _SAMPLE,
    )

    v1_vals: list[float] = []
    v2_vals: list[float] = []
    v2_by_mode: dict[str, list[float]] = {"RELATION_STATE": [], "TEMPORAL_CLAIM": []}
    u_vals: list[float] = []

    for r in rels:
        ev_rows = await conn.fetch(
            """
            SELECT extraction_confidence, evidence_date, source_type
            FROM relation_evidence_raw
            WHERE subject_entity_id=$1 AND object_entity_id=$2 AND canonical_type=$3
              AND entity_provisional=false
            ORDER BY evidence_date DESC LIMIT 500
            """,
            r["subject_entity_id"],
            r["object_entity_id"],
            r["canonical_type"],
        )
        if not ev_rows:
            continue
        evidence = [
            EvidenceInput(
                source_weight=trust.get(e["source_type"] or "", _DEFAULT_TRUST),
                source_type=e["source_type"] or "unknown",
                source_name="x",
                evidence_date=e["evidence_date"],
                extraction_confidence=float(e["extraction_confidence"]),
            )
            for e in ev_rows
        ]
        beta = compute_confidence_beta(
            evidence,
            [],
            decay_alpha=float(r["decay_alpha"]),
            semantic_mode=SemanticMode(str(r["semantic_mode"])),
            base_confidence=float(r["base_confidence"]),
            prior_strength=_KAPPA,
            signal_decay_floor=_SIGNAL_FLOOR,
        )
        v1_vals.append(float(r["confidence"]))
        v2_vals.append(beta.final)
        u_vals.append(beta.uncertainty)
        v2_by_mode[str(r["semantic_mode"])].append(beta.final)

    await conn.close()

    def stats(xs: list[float]) -> str:
        if not xs:
            return "(empty)"
        return (
            f"n={len(xs)} min={min(xs):.3f} max={max(xs):.3f} "
            f"avg={sum(xs) / len(xs):.3f} distinct={len({round(x, 3) for x in xs})}"
        )

    print("=== v1 (stored) ===", stats(v1_vals))
    print("=== v2 (Beta)    ===", stats(v2_vals))
    print("=== v2 uncertainty ===", stats(u_vals))
    print("--- v2 by mode ---")
    for mode, xs in v2_by_mode.items():
        print(f"  {mode:16s}", stats(xs))
    print("--- v2 histogram (0.1 buckets) ---")
    hist = Counter(_bucket(x) for x in v2_vals)
    for b in sorted(hist):
        print(f"  {b}: {hist[b]:5d} {'#' * (hist[b] * 60 // max(hist.values()))}")
    print("--- v1 histogram (0.1 buckets) ---")
    hist1 = Counter(_bucket(x) for x in v1_vals)
    for b in sorted(hist1):
        print(f"  {b}: {hist1[b]:5d} {'#' * (hist1[b] * 60 // max(hist1.values()))}")


if __name__ == "__main__":
    asyncio.run(main())
