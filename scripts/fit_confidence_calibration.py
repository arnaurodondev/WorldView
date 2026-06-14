#!/usr/bin/env python3
"""PLAN-0109 W6 — fit Beta calibration for relation confidence (offline).

Builds a labelled set by asking an LLM adjudicator whether each sampled relation
is supported by its evidence text, fits the Beta calibrator, and reports ECE
before/after plus the (a, b, c) to set as
``KNOWLEDGE_GRAPH_CONFIDENCE_CALIBRATION_{A,B,C}``.

This is an OFFLINE one-shot — it makes one LLM call per sampled relation, so it
is slow and costs a little; run it deliberately, not on the hot path. A human
should spot-check a sample of the LLM labels before trusting the fitted params.

Run inside the knowledge-graph container:

    docker exec worldview-knowledge-graph-scheduler-1 \
        python /app/fit_confidence_calibration.py --sample 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg  # type: ignore[import-untyped]
import httpx
from knowledge_graph.domain.calibration import (
    expected_calibration_error,
    fit_beta_calibrator,
)

_JUDGE_SYSTEM = (
    "You are a strict fact-checker. Given a relation triple and the evidence text it was "
    "extracted from, answer with a single token: TRUE if the evidence clearly supports the "
    "relation, FALSE if it contradicts or does not support it. Answer only TRUE or FALSE."
)


def _dsn() -> str:
    return os.environ["KNOWLEDGE_GRAPH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


async def _judge(client: httpx.AsyncClient, base: str, key: str, model: str, prompt: str) -> int | None:
    try:
        r = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _JUDGE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 4,
            },
            timeout=30,
        )
        r.raise_for_status()
        ans = r.json()["choices"][0]["message"]["content"].strip().upper()
        if ans.startswith("TRUE"):
            return 1
        if ans.startswith("FALSE"):
            return 0
    except Exception as exc:
        print(f"  judge error: {exc}")
    return None


async def main(sample: int) -> None:
    conn = await asyncpg.connect(_dsn())
    rows = await conn.fetch(
        """
        SELECT r.confidence, r.canonical_type,
               se.canonical_name AS subj, oe.canonical_name AS obj,
               (SELECT evidence_text FROM relation_evidence_raw e
                 WHERE e.subject_entity_id=r.subject_entity_id
                   AND e.object_entity_id=r.object_entity_id
                   AND e.canonical_type=r.canonical_type
                 ORDER BY e.evidence_date DESC LIMIT 1) AS evidence
        FROM relations r
        JOIN canonical_entities se ON se.entity_id = r.subject_entity_id
        JOIN canonical_entities oe ON oe.entity_id = r.object_entity_id
        WHERE r.confidence IS NOT NULL
        ORDER BY random() LIMIT $1
        """,
        sample,
    )
    await conn.close()

    base = os.environ.get("EXTRACTION_API_BASE_URL", "https://api.deepinfra.com/v1/openai")
    key = os.environ.get("EXTRACTION_API_KEY") or os.environ.get("KNOWLEDGE_GRAPH_EXTRACTION_API_KEY", "")
    model = os.environ.get("EXTRACTION_API_MODEL_ID", "Qwen/Qwen3-235B-A22B-Instruct-2507")

    samples: list[tuple[float, int]] = []
    async with httpx.AsyncClient() as client:
        for row in rows:
            if not row["evidence"]:
                continue
            prompt = (
                f"Relation: {row['subj']} --{row['canonical_type']}--> {row['obj']}\n"
                f"Evidence: {row['evidence'][:600]}"
            )
            label = await _judge(client, base, key, model, prompt)
            if label is not None:
                samples.append((float(row["confidence"]), label))

    if len(samples) < 20:
        print(f"Too few labelled samples ({len(samples)}) — aborting.")
        return

    ece_before = expected_calibration_error(samples)
    cal = fit_beta_calibrator(samples)
    ece_after = expected_calibration_error([(cal.apply(s), y) for s, y in samples])
    print(
        json.dumps(
            {
                "labelled": len(samples),
                "positive_rate": round(sum(y for _, y in samples) / len(samples), 3),
                "ece_before": round(ece_before, 4),
                "ece_after": round(ece_after, 4),
                "calibration_a": round(cal.a, 4),
                "calibration_b": round(cal.b, 4),
                "calibration_c": round(cal.c, 4),
            },
            indent=2,
        )
    )
    print("\nSet to activate calibration:")
    print(f"  KNOWLEDGE_GRAPH_CONFIDENCE_CALIBRATION_A={cal.a:.4f}")
    print(f"  KNOWLEDGE_GRAPH_CONFIDENCE_CALIBRATION_B={cal.b:.4f}")
    print(f"  KNOWLEDGE_GRAPH_CONFIDENCE_CALIBRATION_C={cal.c:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    asyncio.run(main(ap.parse_args().sample))
