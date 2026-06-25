"""Correctness gate for GLiNER server-side micro-batching.

Loads the SAME model the server uses and asserts that
``batch_predict_entities([t1, t2, ...])`` returns entities byte-identical
(same spans, labels, scores within float tolerance) to the per-text
``[predict_entities(t) for t in ...]`` path that the server previously used.

This is the cutover safety gate — if batching mangled output (wrong offsets,
dropped/extra spans, score drift), the deploy must NOT proceed.

Run inside the gliner-server image:
    docker exec worldview-gliner-server-1 python /app/validate_batch.py
or standalone with the model available locally.

Exit code 0 = identical (safe to cut over); non-zero = mismatch (abort).
"""

# ruff: noqa: T201 — this is a CLI validation script; prints are the output.
from __future__ import annotations

import os
import sys
from typing import Any

# The exact 11-class ontology + threshold the article-consumer sends (mirrors
# nlp_pipeline.application.blocks.ner.NER_CLASS_LABELS / GLINER_THRESHOLD).
LABELS = [
    "organization",
    "government_body",
    "regulatory_body",
    "financial_institution",
    "person",
    "financial_instrument",
    "location",
    "commodity",
    "index",
    "currency",
    "macroeconomic_indicator",
]
THRESHOLD = 0.35
SCORE_TOL = 1e-4

# Representative finance-news snippets — the realistic input distribution.
TEXTS = [
    "Apple Inc. reported record iPhone revenue while the Federal Reserve held rates steady.",
    "Goldman Sachs upgraded Nvidia to a buy as the S&P 500 hit a new all-time high.",
    "The European Central Bank warned that crude oil and gold prices could fuel inflation.",
    "Tesla shares fell after Elon Musk sold $4 billion of stock amid SEC scrutiny.",
    "JPMorgan Chase and Morgan Stanley both beat earnings, lifting the Dow Jones index.",
    "The U.S. Treasury sold 10-year bonds as the yield on government debt climbed.",
    "Microsoft and OpenAI deepened their partnership while regulators in Brussels watched.",
    "Saudi Aramco cut output, sending Brent crude higher against a weakening dollar.",
]


def _key(e: dict[str, Any]) -> tuple[str, str, int, int]:
    return (str(e["text"]), str(e["label"]), int(e["start"]), int(e["end"]))


def main() -> int:
    model_path = os.environ.get("GLINER_MODEL_PATH", "urchade/gliner_large-v2.1")
    from gliner import GLiNER  # type: ignore[import-not-found]

    print(f"[canary] loading {model_path} ...", flush=True)
    model = GLiNER.from_pretrained(model_path)

    serial = [model.predict_entities(t, LABELS, threshold=THRESHOLD) for t in TEXTS]
    batched = model.batch_predict_entities(TEXTS, LABELS, threshold=THRESHOLD)

    assert (
        len(batched) == len(serial) == len(TEXTS)
    ), f"length mismatch: batched={len(batched)} serial={len(serial)} texts={len(TEXTS)}"

    failures: list[str] = []
    for i, (s, b) in enumerate(zip(serial, batched, strict=True)):
        s_sorted = sorted(s, key=_key)
        b_sorted = sorted(b, key=_key)
        if len(s_sorted) != len(b_sorted):
            failures.append(f"text {i}: count serial={len(s_sorted)} batched={len(b_sorted)}")
            continue
        for es, eb in zip(s_sorted, b_sorted, strict=True):
            if _key(es) != _key(eb):
                failures.append(f"text {i}: span {_key(es)} != {_key(eb)}")
            elif abs(float(es["score"]) - float(eb["score"])) > SCORE_TOL:
                failures.append(f"text {i}: score drift {es['text']!r} {es['score']:.6f} vs {eb['score']:.6f}")
        print(f"[canary] text {i}: {len(s_sorted)} entities, serial==batched OK", flush=True)

    if failures:
        print("[canary] FAIL — batch != serial:", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1

    total = sum(len(s) for s in serial)
    print(f"[canary] PASS — {total} entities across {len(TEXTS)} texts identical (serial == batched)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
