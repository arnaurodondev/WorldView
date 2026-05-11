#!/usr/bin/env python3
"""Precompute embeddings for the golden eval set — PLAN-0063 W5-1-05.

Reads tests/eval/golden/queries.jsonl, calls DeepInfra (or any other
configured embedding provider) once per query, and writes a parquet file
to tests/eval/golden/query_embeddings.parquet for the eval harness to
consume in CI (L5: deterministic, $0/run on cache hit).

Parquet schema:
- query_id: string
- model_id: string  (e.g. "BAAI/bge-large-en-v1.5")
- model_revision: string  (provider-reported revision; "unknown" allowed)
- embedding_dim: int32  (e.g. 1024)
- embedding: list<float32>
- generated_at_utc: string  (ISO 8601)
- query_text_sha256: string  (for drift detection)

Default provider: DeepInfra. The DEEPINFRA_API_KEY env var is required.
The script also accepts --provider ollama for local fallback (dev only).

Usage:
    DEEPINFRA_API_KEY=... python scripts/generate_query_embeddings.py \\
        --golden tests/eval/golden/queries.jsonl \\
        --output tests/eval/golden/query_embeddings.parquet \\
        --model BAAI/bge-large-en-v1.5
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("generate_query_embeddings")

DEFAULT_GOLDEN = "tests/eval/golden/queries.jsonl"
DEFAULT_OUTPUT = "tests/eval/golden/query_embeddings.parquet"
DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"
DEFAULT_TIMEOUT = 30.0
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


async def _embed_one_deepinfra(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    text: str,
) -> list[float]:
    """Call DeepInfra's OpenAI-compatible embeddings endpoint."""
    resp = await client.post(
        f"{DEEPINFRA_BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": text, "encoding_format": "float"},
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or []
    if not data:
        raise RuntimeError(f"DeepInfra returned no embedding for input (model={model})")
    embedding = data[0].get("embedding") or []
    if not embedding:
        raise RuntimeError("DeepInfra returned empty embedding vector")
    return list(embedding)


async def _embed_one_ollama(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    text: str,
) -> list[float]:
    """Call Ollama's embeddings endpoint (dev fallback)."""
    resp = await client.post(
        f"{base_url.rstrip('/')}/api/embeddings",
        json={"model": model, "prompt": text},
    )
    resp.raise_for_status()
    payload = resp.json()
    embedding = payload.get("embedding") or []
    if not embedding:
        raise RuntimeError("Ollama returned empty embedding vector")
    return list(embedding)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_queries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


async def generate_all(
    queries: list[dict[str, Any]],
    *,
    provider: str,
    model: str,
    api_key: str | None,
    ollama_base_url: str,
    revision: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    timeout = httpx.Timeout(DEFAULT_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i, row in enumerate(queries, start=1):
            qid = row["query_id"]
            text = row["query_text"]
            try:
                if provider == "deepinfra":
                    if not api_key:
                        raise RuntimeError("DEEPINFRA_API_KEY env var is required for --provider deepinfra")
                    embedding = await _embed_one_deepinfra(client, api_key, model, text)
                elif provider == "ollama":
                    embedding = await _embed_one_ollama(client, ollama_base_url, model, text)
                else:
                    raise RuntimeError(f"unknown provider: {provider}")
            except Exception as exc:
                print(f"WARN: query {qid} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            out.append(
                {
                    "query_id": qid,
                    "model_id": model,
                    "model_revision": revision,
                    "embedding_dim": len(embedding),
                    "embedding": embedding,
                    "generated_at_utc": datetime.now(tz=UTC).isoformat(),
                    "query_text_sha256": _sha256(text),
                }
            )
            if i % 10 == 0:
                print(f"  generated {i}/{len(queries)} embeddings", file=sys.stderr)
    return out


def write_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write parquet via pyarrow."""
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("pyarrow is required — pip install pyarrow") from exc

    if not rows:
        raise RuntimeError("no rows to write")

    schema = pa.schema(
        [
            pa.field("query_id", pa.string()),
            pa.field("model_id", pa.string()),
            pa.field("model_revision", pa.string()),
            pa.field("embedding_dim", pa.int32()),
            pa.field("embedding", pa.list_(pa.float32())),
            pa.field("generated_at_utc", pa.string()),
            pa.field("query_text_sha256", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(output_path))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", default=DEFAULT_GOLDEN)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default="deepinfra", choices=("deepinfra", "ollama"))
    parser.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument(
        "--revision",
        default=os.getenv("EMBEDDING_MODEL_REVISION", "unknown"),
        help="Provider model revision string; documented in the parquet for drift checks",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap number of queries (debug)")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    api_key = os.getenv("DEEPINFRA_API_KEY") or os.getenv("RAG_CHAT_DEEPINFRA_API_KEY")
    queries = load_queries(Path(args.golden))
    if args.limit:
        queries = queries[: args.limit]
    print(f"loading {len(queries)} queries from {args.golden}", file=sys.stderr)

    rows = asyncio.run(
        generate_all(
            queries,
            provider=args.provider,
            model=args.model,
            api_key=api_key,
            ollama_base_url=args.ollama_base_url,
            revision=args.revision,
        )
    )
    if not rows:
        print("ERROR: no embeddings generated", file=sys.stderr)
        return 1

    write_parquet(rows, Path(args.output))
    print(f"wrote {len(rows)} embeddings to {args.output}", file=sys.stderr)
    print(
        f"  model={args.model} dim={rows[0]['embedding_dim']} provider={args.provider}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
