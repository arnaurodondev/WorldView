#!/usr/bin/env python3
"""GLiNER-bypass live validation of the new extraction pipeline on REAL news.

The local GLiNER NER server is CPU-bound (>300s/article on this host), so the live
end-to-end pipeline cannot be driven here. But previously-processed documents already
have their chunks + GLiNER mentions (with mention_class + resolution) persisted in
nlp_db. This script loads those REAL inputs and runs them straight through the NEW
``run_deep_extraction_block`` — v1.7 type-annotated prompt + the deterministic gates
(#3 type guard / #4 direction swap / #5 suppression) + the #6 Qwen3-235B co-mention
entailment check — so we can validate the new pipeline's OUTPUT on real article data
without the NER bottleneck.

Run:
  NLP_DB_URL=postgresql://... DEEPINFRA_API_KEY=... \
    python scripts/eval/validate_new_pipeline_live.py --docs 6
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import psycopg
import structlog

# structlog → stdout so the block's gate/entailment drop events are visible.
structlog.configure(processors=[structlog.processors.KeyValueRenderer(key_order=["event"])])

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "services", "nlp-pipeline", "src"))
for lib in ("ml-clients", "common", "contracts", "observability", "prompts", "messaging"):
    sys.path.insert(0, os.path.join(_REPO, "libs", lib, "src"))


async def _amain(n_docs: int) -> None:
    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter
    from nlp_pipeline.application.blocks.deep_extraction import EntailmentCheckConfig, run_deep_extraction_block
    from nlp_pipeline.application.blocks.suppression import ProcessingPath
    from nlp_pipeline.domain.enums import MentionClass
    from nlp_pipeline.domain.models import Chunk, EntityMention

    nlp_url = os.environ["NLP_DB_URL"].replace("postgresql+asyncpg://", "postgresql://")
    key = os.environ["DEEPINFRA_API_KEY"]
    base = "https://api.deepinfra.com/v1/openai"

    # Pick recent DEEP-tier docs that have BOTH chunks and >=3 mentions.
    with psycopg.connect(nlp_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.doc_id
            FROM chunks c JOIN entity_mentions em ON em.doc_id = c.doc_id
            WHERE c.chunk_text IS NOT NULL
            GROUP BY c.doc_id HAVING count(DISTINCT em.mention_id) >= 4 AND count(DISTINCT c.chunk_id) >= 1
            ORDER BY c.doc_id DESC LIMIT %s
            """,
            (n_docs,),
        )
        doc_ids = [r[0] for r in cur.fetchall()]

    sem = asyncio.Semaphore(4)
    ext = DeepSeekExtractionAdapter(api_key=key, model_id="openai/gpt-oss-120b", base_url=base, semaphore=sem,
                                    reasoning_effort="medium", max_tokens=8192)
    entail = DeepSeekExtractionAdapter(api_key=key, model_id="Qwen/Qwen3-235B-A22B-Instruct-2507", base_url=base,
                                       semaphore=sem, reasoning_effort="low", max_tokens=1024)
    cfg = EntailmentCheckConfig(enabled=True)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    totals = {"docs": 0, "relations": 0}
    for doc_id in doc_ids:
        with psycopg.connect(nlp_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT chunk_id, section_id, chunk_index, chunk_text, char_start, char_end "
                        "FROM chunks WHERE doc_id=%s AND chunk_text IS NOT NULL ORDER BY chunk_index", (doc_id,))
            chunks = [Chunk(chunk_id=r[0], doc_id=doc_id, section_id=r[1], chunk_index=r[2], text=r[3],
                            char_start=r[4] or 0, char_end=r[5] or len(r[3]), token_count=len(r[3].split())) for r in cur.fetchall()]
            cur.execute("SELECT mention_id, section_id, mention_text, mention_class, confidence, char_start, char_end, "
                        "resolved_entity_id FROM entity_mentions WHERE doc_id=%s", (doc_id,))
            mentions = [EntityMention(mention_id=r[0], doc_id=doc_id, section_id=r[1], mention_text=r[2],
                                      mention_class=MentionClass(r[3]), confidence=r[4] or 0.9, char_start=r[5] or 0,
                                      char_end=r[6] or 0, resolved_entity_id=r[7]) for r in cur.fetchall()]
        if not chunks or not mentions:
            continue
        print(f"\n===== doc {str(doc_id)[:8]} | {len(chunks)} chunks | {len(mentions)} mentions =====")
        try:
            result, _signals = await run_deep_extraction_block(
                doc_id=doc_id, chunks=chunks, mentions=mentions, processing_path=ProcessingPath.FULL_PIPELINE,
                extraction_client=ext, model_id="openai/gpt-oss-120b", published_at=None, extracted_at=now,
                outbox_topic_signal="nlp.signal.detected.v1", entailment_client=entail, entailment_config=cfg,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  EXTRACTION ERROR: {type(exc).__name__}: {exc}")
            continue
        rels = result.get("relations", [])
        totals["docs"] += 1
        totals["relations"] += len(rels)
        print(f"  FINAL relations kept: {len(rels)}")
        for r in rels[:8]:
            print(f"    - {r.get('subject_ref')} --{r.get('predicate')}--> {r.get('object_ref')}")

    print(f"\n=== TOTAL: {totals['docs']} docs, {totals['relations']} final relations "
          f"({round(totals['relations']/max(1,totals['docs']),1)}/doc) ===")
    await ext.aclose()
    await entail.aclose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=6)
    args = ap.parse_args()
    asyncio.run(_amain(args.docs))


if __name__ == "__main__":
    main()
