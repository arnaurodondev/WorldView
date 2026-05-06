#!/usr/bin/env python3
"""Retrieval evaluation harness — PLAN-0063 W5-1-02.

Reads the labelled golden set at tests/eval/golden/queries.jsonl, calls the
rag-chat /v1/internal/retrieve endpoint over HTTP for each query, and computes
retrieval-quality metrics (NDCG@10, MRR, P@5, Recall@20) overall and per
query_class. Writes a structured JSON + CSV report under results/.

Usage:
    python scripts/eval_retrieval.py \\
        --rag-url http://localhost:8003 \\
        --golden tests/eval/golden/queries.jsonl \\
        [--baseline results/baseline_pre_hybrid.json] \\
        [--query-embeddings tests/eval/golden/query_embeddings.parquet] \\
        [--mode default|vector_only|lexical_only|hybrid] \\
        [--top-k 20] \\
        [--fail-on-regression 0.03] \\
        [--output-dir results/]

Tolerance for partial labelling: rows with empty `relevant_doc_ids` are SKIPPED
with a stderr warning and excluded from metric aggregation. The script still
exits 0 in that case so it can run during the W5-1 iteration where labelling
is in flight (the CI gate is DISABLED in W5-1; it enables in W5-3 by which
point the dataset is fully labelled).

References:
- §0-bis.0 v2 (L1-L16) for locked decisions
- §0-bis.4-v2 for the 12 query_class buckets
- BP-235: explicit httpx timeouts to avoid silent 5s shadowing
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("eval_retrieval")

DEFAULT_RAG_URL = "http://localhost:8003"
DEFAULT_GOLDEN = "tests/eval/golden/queries.jsonl"
DEFAULT_OUTPUT_DIR = "results"
DEFAULT_TOP_K = 20
DEFAULT_TIMEOUT_SECONDS = 30.0  # BP-235: explicit, not the 5s default

VALID_MODES = ("default", "vector_only", "lexical_only", "hybrid", "hybrid_no_boost")


# ─── Metric primitives ────────────────────────────────────────────────────────


def dcg(gains: list[float], k: int) -> float:
    """DCG@k using gain = (2^rel - 1) / log2(rank + 1) for rank in 1..k."""
    return sum((2**g - 1) / math.log2(rank + 1) for rank, g in enumerate(gains[:k], start=1))


def ndcg_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 10) -> float:
    """Normalised DCG@k. retrieved is ranked doc_id list; relevant maps doc_id -> grade."""
    gains = [float(relevant.get(doc_id, 0)) for doc_id in retrieved[:k]]
    ideal = sorted(relevant.values(), reverse=True)[:k]
    actual_dcg = dcg(gains, k)
    ideal_dcg = dcg([float(g) for g in ideal], k)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def mean_reciprocal_rank(retrieved: list[str], relevant: dict[str, int]) -> float:
    """First rank where relevance >= 1; 0.0 if no relevant doc retrieved."""
    for rank, doc_id in enumerate(retrieved, start=1):
        if relevant.get(doc_id, 0) >= 1:
            return 1.0 / rank
    return 0.0


def precision_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 5) -> float:
    """Fraction of top-k with relevance >= 1."""
    if not retrieved or k == 0:
        return 0.0
    hits = sum(1 for doc_id in retrieved[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / k


def recall_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 20) -> float:
    """Fraction of all relevant docs that appear in top-k."""
    total_relevant = sum(1 for v in relevant.values() if v >= 1)
    if total_relevant == 0:
        return 0.0
    hits = sum(1 for doc_id in retrieved[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / total_relevant


# ─── Golden-set loader ────────────────────────────────────────────────────────


def load_golden_set(path: Path) -> list[dict[str, Any]]:
    """Load and validate the golden JSONL.

    Returns the list of query rows. Raises ValueError on duplicate query_id;
    tolerates empty relevant_doc_ids (caller handles).
    """
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            qid = row.get("query_id")
            if not qid:
                raise ValueError(f"{path}:{lineno}: missing query_id")
            if qid in seen_ids:
                raise ValueError(f"{path}:{lineno}: duplicate query_id {qid!r}")
            seen_ids.add(qid)
            rows.append(row)
    return rows


def load_query_embeddings(path: Path) -> dict[str, list[float]]:
    """Load precomputed query embeddings from parquet, keyed by query_id."""
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("pyarrow is required to load query_embeddings.parquet — pip install pyarrow") from exc

    table = pq.read_table(str(path))
    df = table.to_pylist()
    out: dict[str, list[float]] = {}
    for row in df:
        qid = row.get("query_id")
        emb = row.get("embedding")
        if qid and emb:
            out[qid] = list(emb)
    return out


# ─── HTTP retrieval driver ────────────────────────────────────────────────────


async def call_retrieve(
    client: httpx.AsyncClient,
    rag_url: str,
    query_text: str,
    *,
    query_embedding: list[float] | None = None,
    top_k: int = DEFAULT_TOP_K,
    internal_jwt: str | None = None,
) -> list[dict[str, Any]]:
    """Call POST /v1/internal/retrieve and return the candidates list.

    Raises httpx.HTTPStatusError on 4xx/5xx so the caller can record the
    per-query failure and continue.
    """
    body: dict[str, Any] = {"query_text": query_text, "top_k": top_k}
    if query_embedding is not None:
        body["query_embedding"] = query_embedding

    headers: dict[str, str] = {}
    if internal_jwt:
        headers["X-Internal-JWT"] = internal_jwt

    resp = await client.post(
        f"{rag_url.rstrip('/')}/v1/internal/retrieve",
        json=body,
        headers=headers,
    )
    resp.raise_for_status()
    payload = resp.json()
    candidates: list[dict[str, Any]] = payload.get("candidates", [])
    return candidates


# ─── Per-query evaluation ─────────────────────────────────────────────────────


def evaluate_query(
    row: dict[str, Any],
    candidates: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    """Compute metrics for one query against its retrieved candidates."""
    relevant: dict[str, int] = {}
    for rd in row.get("relevant_doc_ids", []):
        doc_id = rd.get("doc_id")
        relevance = rd.get("relevance")
        if doc_id is not None and relevance is not None:
            relevant[str(doc_id).lower()] = int(relevance)

    retrieved_doc_ids = [str(c.get("doc_id") or c.get("chunk_id") or "").lower() for c in candidates[:top_k]]

    return {
        "query_id": row.get("query_id"),
        "query_class": row.get("query_class") or row.get("intent") or "unknown",
        "intent": row.get("intent"),
        "n_retrieved": len(retrieved_doc_ids),
        "n_relevant_labelled": len(relevant),
        "ndcg_at_10": ndcg_at_k(retrieved_doc_ids, relevant, k=10),
        "mrr": mean_reciprocal_rank(retrieved_doc_ids, relevant),
        "p_at_5": precision_at_k(retrieved_doc_ids, relevant, k=5),
        "recall_at_20": recall_at_k(retrieved_doc_ids, relevant, k=20),
        "retrieved_top_5": retrieved_doc_ids[:5],
    }


# ─── Aggregation ──────────────────────────────────────────────────────────────


def _summarise(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    return {
        "mean": statistics.mean(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "n": len(values),
    }


def aggregate(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary + per-class breakdown."""
    summary = {
        "ndcg_at_10": _summarise([r["ndcg_at_10"] for r in per_query]),
        "mrr": _summarise([r["mrr"] for r in per_query]),
        "p_at_5": _summarise([r["p_at_5"] for r in per_query]),
        "recall_at_20": _summarise([r["recall_at_20"] for r in per_query]),
    }

    by_class: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"ndcg_values": [], "mrr_values": [], "p5_values": [], "r20_values": []}
    )
    for r in per_query:
        cls = r["query_class"]
        by_class[cls]["ndcg_values"].append(r["ndcg_at_10"])
        by_class[cls]["mrr_values"].append(r["mrr"])
        by_class[cls]["p5_values"].append(r["p_at_5"])
        by_class[cls]["r20_values"].append(r["recall_at_20"])

    by_class_out: dict[str, dict[str, Any]] = {}
    for cls, vals in by_class.items():
        by_class_out[cls] = {
            "n": len(vals["ndcg_values"]),
            "ndcg_at_10": statistics.mean(vals["ndcg_values"]) if vals["ndcg_values"] else 0.0,
            "mrr": statistics.mean(vals["mrr_values"]) if vals["mrr_values"] else 0.0,
            "p_at_5": statistics.mean(vals["p5_values"]) if vals["p5_values"] else 0.0,
            "recall_at_20": statistics.mean(vals["r20_values"]) if vals["r20_values"] else 0.0,
        }

    return {"summary": summary, "by_class": by_class_out}


# ─── Baseline diff ────────────────────────────────────────────────────────────


def compare_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    fail_on_regression: float,
    per_class_threshold: float = 0.05,
) -> tuple[bool, list[str]]:
    """Check whether current run regresses NDCG@10 from baseline.

    Returns (passed, messages). When fail_on_regression is positive (e.g.
    0.03), a drop ≥0.03 in global NDCG@10 fails. When negative (e.g. -0.05)
    it's interpreted as a REQUIRED IMPROVEMENT floor (post_hybrid must lift
    by at least 0.05 vs baseline).
    """
    msgs: list[str] = []
    passed = True

    cur_ndcg = current["summary"]["ndcg_at_10"]["mean"]
    base_ndcg = baseline["summary"]["ndcg_at_10"]["mean"]
    delta = cur_ndcg - base_ndcg

    if fail_on_regression >= 0:
        # Regression gate: current must not drop more than `fail_on_regression`.
        if delta < -fail_on_regression:
            msgs.append(
                f"REGRESSION: global NDCG@10 dropped by {-delta:.4f} "
                f"(>= threshold {fail_on_regression:.4f}); cur={cur_ndcg:.4f} base={base_ndcg:.4f}"
            )
            passed = False
        else:
            msgs.append(f"OK: global NDCG@10 delta {delta:+.4f} (cur={cur_ndcg:.4f} base={base_ndcg:.4f})")
    else:
        # Required improvement: current must lift by at least |fail_on_regression|.
        required = -fail_on_regression
        if delta < required:
            msgs.append(
                f"INSUFFICIENT_LIFT: global NDCG@10 lifted only {delta:+.4f} "
                f"(< required {required:.4f}); cur={cur_ndcg:.4f} base={base_ndcg:.4f}"
            )
            passed = False
        else:
            msgs.append(f"OK: global NDCG@10 lifted {delta:+.4f} (>= {required:.4f})")

    # Per-class regression guardrail (always applied with positive threshold).
    base_classes = baseline.get("by_class", {})
    cur_classes = current.get("by_class", {})
    for cls, cur_vals in cur_classes.items():
        base_vals = base_classes.get(cls)
        if not base_vals:
            continue
        cls_delta = cur_vals["ndcg_at_10"] - base_vals["ndcg_at_10"]
        if cls_delta < -per_class_threshold:
            msgs.append(
                f"PER_CLASS_REGRESSION: {cls} NDCG@10 dropped {-cls_delta:.4f} "
                f"(>= {per_class_threshold:.4f}); cur={cur_vals['ndcg_at_10']:.4f} "
                f"base={base_vals['ndcg_at_10']:.4f}"
            )
            passed = False

    return passed, msgs


# ─── Output writers ───────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S603, S607
    except Exception:
        return "unknown"


def write_outputs(
    output_dir: Path,
    timestamp: str,
    golden_path: Path,
    n_queries: int,
    aggregated: dict[str, Any],
    per_query: list[dict[str, Any]],
    skipped: list[str],
    failed: list[str],
    mode: str,
    embedding_model: str | None,
    rrf_k: int | None = None,
) -> Path:
    """Write JSON + CSV outputs. Returns the JSON path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"eval_{timestamp}.json"
    csv_path = output_dir / f"eval_{timestamp}.csv"

    payload = {
        "timestamp": timestamp,
        "git_sha": _git_sha(),
        "mode": mode,
        "embedding_model": embedding_model,
        "rrf_k": rrf_k,
        "golden_set_path": str(golden_path),
        "n_queries_total": n_queries,
        "n_queries_evaluated": len(per_query),
        "n_queries_skipped_unlabelled": len(skipped),
        "n_queries_failed": len(failed),
        "skipped_query_ids": skipped,
        "failed_query_ids": failed,
        "summary": aggregated["summary"],
        "by_class": aggregated["by_class"],
        "per_query": per_query,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "query_id",
                "query_class",
                "intent",
                "n_retrieved",
                "n_relevant_labelled",
                "ndcg_at_10",
                "mrr",
                "p_at_5",
                "recall_at_20",
            ]
        )
        for r in per_query:
            writer.writerow(
                [
                    r["query_id"],
                    r["query_class"],
                    r["intent"],
                    r["n_retrieved"],
                    r["n_relevant_labelled"],
                    f"{r['ndcg_at_10']:.4f}",
                    f"{r['mrr']:.4f}",
                    f"{r['p_at_5']:.4f}",
                    f"{r['recall_at_20']:.4f}",
                ]
            )

    return json_path


def print_summary(aggregated: dict[str, Any], n_evaluated: int, n_skipped: int) -> None:
    summary = aggregated["summary"]
    print(
        f"NDCG@10: {summary['ndcg_at_10']['mean']:.4f} ± {summary['ndcg_at_10']['std']:.4f} "
        f"| MRR: {summary['mrr']['mean']:.4f} "
        f"| P@5: {summary['p_at_5']['mean']:.4f} "
        f"| Recall@20: {summary['recall_at_20']['mean']:.4f} "
        f"(n_evaluated={n_evaluated}, n_skipped={n_skipped})"
    )
    print()
    print(f"{'query_class':<28} {'n':>4} {'ndcg@10':>8} {'mrr':>8} {'p@5':>8} {'r@20':>8}")
    for cls, vals in sorted(aggregated["by_class"].items()):
        print(
            f"{cls:<28} {vals['n']:>4} "
            f"{vals['ndcg_at_10']:>8.4f} {vals['mrr']:>8.4f} "
            f"{vals['p_at_5']:>8.4f} {vals['recall_at_20']:>8.4f}"
        )


# ─── Main ─────────────────────────────────────────────────────────────────────


async def run_eval(args: argparse.Namespace) -> int:
    rows = load_golden_set(Path(args.golden))
    embeddings: dict[str, list[float]] = {}
    if args.query_embeddings:
        embeddings_path = Path(args.query_embeddings)
        if embeddings_path.exists():
            embeddings = load_query_embeddings(embeddings_path)
            print(f"loaded {len(embeddings)} precomputed embeddings", file=sys.stderr)
        else:
            print(
                f"WARN: --query-embeddings path {embeddings_path} not found; "
                "endpoint will compute embeddings server-side",
                file=sys.stderr,
            )

    skipped: list[str] = []
    failed: list[str] = []
    per_query: list[dict[str, Any]] = []

    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)
    internal_jwt = os.getenv("EVAL_INTERNAL_JWT")
    async with httpx.AsyncClient(timeout=timeout) as client:
        for row in rows:
            qid = row["query_id"]
            relevant = row.get("relevant_doc_ids", [])
            if not relevant:
                skipped.append(qid)
                continue

            try:
                candidates = await call_retrieve(
                    client,
                    args.rag_url,
                    row["query_text"],
                    query_embedding=embeddings.get(qid),
                    top_k=args.top_k,
                    internal_jwt=internal_jwt,
                )
            except httpx.HTTPStatusError as exc:
                print(f"WARN: query {qid} -> HTTP {exc.response.status_code}", file=sys.stderr)
                failed.append(qid)
                continue
            except (TimeoutError, httpx.RequestError) as exc:
                print(f"WARN: query {qid} -> {type(exc).__name__}: {exc}", file=sys.stderr)
                failed.append(qid)
                continue

            per_query.append(evaluate_query(row, candidates, args.top_k))

    if skipped:
        print(
            f"NOTE: {len(skipped)} queries skipped (no relevant_doc_ids labelled yet); first 5: {skipped[:5]}",
            file=sys.stderr,
        )

    if len(failed) > 5:
        print(
            f"ERROR: {len(failed)} queries failed at retrieval — retrieval is broken, not a regression. Exiting 1.",
            file=sys.stderr,
        )
        return 1

    if not per_query:
        print(
            "ERROR: no queries evaluated (all rows skipped or failed). Have you labelled the golden set?",
            file=sys.stderr,
        )
        # Exit 0 because in W5-1 the labelling is in flight; the CI gate is
        # disabled during this period.
        return 0

    aggregated = aggregate(per_query)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = write_outputs(
        Path(args.output_dir),
        timestamp,
        Path(args.golden),
        len(rows),
        aggregated,
        per_query,
        skipped,
        failed,
        args.mode,
        args.embedding_model,
    )
    print(f"wrote {json_path}", file=sys.stderr)

    print_summary(aggregated, n_evaluated=len(per_query), n_skipped=len(skipped))

    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(
                f"WARN: baseline {baseline_path} not found — first run is by definition the baseline",
                file=sys.stderr,
            )
            return 0
        baseline_data = json.loads(baseline_path.read_text())
        passed, msgs = compare_to_baseline(
            aggregated,
            baseline_data,
            fail_on_regression=args.fail_on_regression,
        )
        for m in msgs:
            print(m, file=sys.stderr)
        if not passed:
            return 1

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rag-url", default=os.getenv("RAG_CHAT_URL", DEFAULT_RAG_URL))
    parser.add_argument("--golden", default=DEFAULT_GOLDEN)
    parser.add_argument("--baseline", default=None)
    parser.add_argument(
        "--query-embeddings", default=None, help="Path to tests/eval/golden/query_embeddings.parquet (L5)"
    )
    parser.add_argument("--mode", default="default", choices=VALID_MODES)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--fail-on-regression",
        type=float,
        default=0.03,
        help="If positive, fail when global NDCG@10 drops by >= this delta. "
        "If negative, treat |value| as required improvement floor (W5-3 mode).",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("RAG_CHAT_EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"),
        help="Recorded in the report header; not used at runtime.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(run_eval(args))


if __name__ == "__main__":
    sys.exit(main())
