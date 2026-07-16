"""Granular functional checks for nlp-pipeline (S6 / nlp_db).

Covers the enrichment pipeline health: chunks + embeddings ready, NER mention
liveness (near-zero = GLiNER stalled/OOM), routing-tier distribution, relevance
scoring coverage, no stuck poison embeddings, all expected source types flowing,
and the read APIs (news top, trending entities, ANN chunk search, resolve) plus
the synthetic CJK embedding-worker E2E.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx
from . import assert_api_ok

SVC = "nlp-pipeline"


def run(ctx: Ctx) -> None:
    _db(ctx)
    _api(ctx)


def _db(ctx: Ctx) -> None:
    R = ctx.report
    q = H.psql_many(
        "nlp_db",
        {
            "chunks": "SELECT count(*) FROM chunks",
            "emb_ready": "SELECT count(*) FILTER (WHERE embedding_status='ready') FROM chunk_embeddings",
            "emb_total": "SELECT count(*) FROM chunk_embeddings",
            "mentions_24h": "SELECT count(*) FROM entity_mentions WHERE created_at > now() - interval '24 hours'",
            "routing": "SELECT count(*) FROM routing_decisions",
            "tiers": "SELECT string_agg(final_routing_tier||':'||c, ',') FROM (SELECT final_routing_tier, count(*) c FROM routing_decisions GROUP BY 1) t",
            "dsm": "SELECT count(*) FROM document_source_metadata",
            "dsm_rel": "SELECT count(*) FILTER (WHERE llm_relevance_score IS NOT NULL) FROM document_source_metadata",
            "dsm_rel_24h": "SELECT count(*) FILTER (WHERE llm_scored_at > now() - interval '24 hours') FROM document_source_metadata",
            "src_types": "SELECT string_agg(DISTINCT source_type, ',') FROM document_source_metadata",
            "stuck_embed": "SELECT count(*) FROM embedding_pending WHERE retry_count >= 5",
        },
    )
    R.floor(SVC, "chunks", H.as_int(q["chunks"]), T.NLP_CHUNKS_FLOOR)
    R.floor(SVC, "chunk embedding ready %", H.pct(q["emb_ready"], q["emb_total"]), T.NLP_EMBED_READY_WARN, unit="%")

    m24 = H.as_int(q["mentions_24h"], -1)
    R.check(
        SVC,
        "entity mentions flowing (24h, NER alive)",
        m24 >= T.NLP_MENTIONS_24H_FAIL,
        f"{m24} mentions/24h (floor {T.NLP_MENTIONS_24H_FAIL})",
    )

    R.floor(SVC, "routing_decisions", H.as_int(q["routing"]), T.NLP_ROUTING_FLOOR)
    R.check(
        SVC,
        "routing produces all 3 tiers",
        all(t in (q["tiers"] or "") for t in ("deep", "medium", "light")),
        f"tiers: {q['tiers']}",
        soft=True,
    )
    # Coverage % is diluted by backfill/dedup docs that legitimately bypass
    # scoring (a 195k-doc news backfill drove it to ~17%), so it is only a loose
    # drift floor. The real signal that the LLM relevance scorer is ALIVE is a
    # non-trivial recent scoring RATE, which is immune to backfill dilution.
    R.floor(SVC, "relevance-scoring coverage %", H.pct(q["dsm_rel"], q["dsm"]), T.NLP_RELEVANCE_COVERAGE_WARN, unit="%")
    R.floor(
        SVC,
        "relevance scorer active (scored/24h)",
        H.as_int(q["dsm_rel_24h"], 0),
        T.NLP_RELEVANCE_SCORED_24H_FLOOR,
    )

    src = set((q["src_types"] or "").split(","))
    missing = T.NLP_EXPECTED_SOURCE_TYPES - src
    R.check(
        SVC,
        "all expected source types enriched",
        not missing,
        f"missing {missing}" if missing else f"{sorted(src)}",
        soft=True,
    )

    stuck = H.as_int(q["stuck_embed"], -1)
    R.check(
        SVC,
        "no poison embeddings (retry≥5)",
        stuck <= T.NLP_STUCK_EMBED_WARN,
        f"{stuck} rows stuck at max retries",
        soft=True,
    )


def _api(ctx: Ctx) -> None:
    R = ctx.report
    ok, body = assert_api_ok(ctx, SVC, "news top", "nlp_top")
    if ok and isinstance(body, dict):
        arts = body.get("articles") or []
        R.check(
            SVC,
            "news top items have title+url",
            bool(arts) and all(a.get("title") and a.get("url") for a in arts[:5]),
            f"{len(arts)} articles",
        )

    ok, body = assert_api_ok(ctx, SVC, "trending entities", "nlp_trend")
    if ok and isinstance(body, dict):
        ents = body.get("entities") or []
        R.check(
            SVC,
            "trending entities carry counts",
            bool(ents) and all("count" in e for e in ents[:3]),
            f"{len(ents)} entities",
        )

    assert_api_ok(ctx, SVC, "signals feed", "nlp_signals", soft_on_missing=True)

    ok, body = assert_api_ok(ctx, SVC, "entity resolve (Apple)", "nlp_resolve")
    ok, body = assert_api_ok(ctx, SVC, "ANN chunk search", "nlp_chunks")

    # Synthetic embedding-worker E2E: raw-CJK exercises bge truncation + provider path.
    row = ctx.api_row("nlp_embed_cjk")
    if row:
        s = row.get("status")
        if s == 200:
            R.ok(SVC, "embedding path (synthetic CJK)", "200 — bge truncation + provider OK on raw CJK")
        elif s == 400:
            R.fail(SVC, "embedding path (synthetic CJK)", "400 — token-budget truncation regressed (CJK under-count)")
        else:
            R.warn(SVC, "embedding path (synthetic CJK)", f"HTTP {s} {row.get('error', '')}")
