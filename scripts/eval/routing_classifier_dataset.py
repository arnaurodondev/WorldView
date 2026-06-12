#!/usr/bin/env python3
"""Build the labeled training dataset for the news-routing classifier (PLAN-0111 C-3).

PURPOSE
-------
PLAN-0111 Sub-Plan C replaces the 5-hand-feature weighted routing formula
(``services/nlp-pipeline/.../blocks/routing.py``) with an EmbeddingGemma-300m
classifier over ``title + subtitle``. Before we train (C-4) or run the ablation
(C-5), we need a **labeled dataset** and a **feasibility verdict**.

This script assembles, per historical routed document, one row:

    doc_id, title, subtitle, <5 hand-features>, routed_tier,
    n_relations, n_claims, n_events, yielded(bool), degraded(bool)

LABEL
-----
``yielded = (n_relations + n_claims + n_events) >= 1`` — i.e. did deep extraction
produce at least one structured artefact attributable to this source document?

The label can only be computed for docs that were actually EXTRACTED, which in
the current pipeline means ``processing_path = 'full_pipeline'`` (the MEDIUM/DEEP
tiers). LIGHT / SUPPRESS docs were never fed to the 235B extractor, so they have
NO yield label — this is the **selection-bias** problem documented in the
feasibility report. We emit ONLY full_pipeline rows here (the labelable
population) and quantify the bias in the report.

JOIN MODEL (verified against live schema, 2026-06-12)
-----------------------------------------------------
The 3 extraction artefacts live in ``intelligence_db`` (the KG), the routing
features live in ``nlp_db``. They share the document UUIDv7 as the join key:

  * relations → ``relation_evidence_raw.source_document_id``   (also relation_evidence.doc_id)
  * claims    → ``claims.doc_id``
  * events    → ``events.doc_id``

(``temporal_events`` is a derived/macro table keyed by a ``source_article_ids``
array and is intentionally EXCLUDED — it is not a per-doc extraction artefact and
would over-count macro docs.)

Because the two databases live in separate Postgres logical DBs we cannot JOIN in
one SQL statement. We instead pull the per-doc yield COUNTS from intelligence_db
into an in-memory dict keyed by doc_id, then left-join against the nlp_db routing
rows in Python. Both DBs are queried READ-ONLY.

DEGRADED / TIMED-OUT DOCS
-------------------------
Commit ee76aa957 ("unmask deep-extraction timeouts") added a ``degraded`` /
``timed_out_windows`` flag to the *merged* extraction result so an LLM timeout is
no longer silently substituted as a clean ``{events:[],claims:[],relations:[]}``.
HOWEVER — that merged result is only LOGGED (``deep_extraction.complete``); it is
NOT persisted to any nlp_db / intelligence_db table. So we cannot read a per-doc
``degraded`` flag back out of the DB.

What IS persisted is the ``dead_letter_queue``: when EVERY window times out the
article consumer re-raises and the doc lands in the DLQ with
``message_processing_timeout``. The DLQ payload only carries the *event_id* of the
article-stored event, not the doc_id, so it cannot be mapped 1:1 to a routing row.

Consequence for labels: a full_pipeline doc with ZERO yield is *usually* a genuine
"model found nothing" but MAY be a partially-timed-out (degraded) doc whose good
windows still produced nothing. We therefore:
  * set ``degraded = False`` for all rows we can positively confirm (yield ≥ 1
    proves extraction ran to completion on at least one window), and
  * leave ``degraded = False`` (not True) on zero-yield rows but emit a manifest
    warning + a DLQ timeout count so the C-4 trainer can choose to down-weight or
    drop a held-out slice. We do NOT fabricate a per-doc degraded flag we cannot
    source. See the feasibility report for the recommended mitigation (persist the
    merged result in a future migration so C-4+ has clean labels).

THE 5 HAND FEATURES (persisted in ``routing_decisions.feature_scores_json``)
----------------------------------------------------------------------------
All five are computed PRE-extraction (Block 5 runs before Block 10 deep
extraction), so none observes the label directly. The one to scrutinise:

  * ``extraction_yield`` — NAME IS MISLEADING. It is NOT this doc's realised yield.
    It is ``0.6*min(1, mention_count/20) + 0.4*min(1, section_count/8)`` — a PRIOR
    proxy built from Block-4 mention count + Block-3 section count, both available
    before extraction. It does NOT leak the label, but the trainer should treat it
    as the "structural richness" prior it actually is. We surface it but flag it in
    the manifest so a cautious ablation can drop it.

OUTPUT
------
  <out>/routing_dataset.csv      — one row per labelable (full_pipeline) doc
  <out>/routing_dataset_manifest.json — counts, positive rate, tier breakdown,
                                        leakage flags, selection-bias stats,
                                        LIGHT-extraction cost estimate

The script is idempotent: re-running overwrites the two artefacts. It never writes
to either database.

USAGE
-----
  NLP_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/nlp_db \
  INTELLIGENCE_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/intelligence_db \
      python scripts/eval/routing_classifier_dataset.py build --out results/routing_dataset

  # estimate the cost of extracting a de-biasing LIGHT sample without spending:
  NLP_DB_URL=... python scripts/eval/routing_classifier_dataset.py estimate-light-cost \
      --sample-size 400
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ── DeepInfra 235B published rate (mirrors scripts/eval/extraction_quality_eval.py) ──
# Used ONLY for the LIGHT-sample counterfactual cost estimate — we never call the API.
_EXTRACT_IN_PER_M = 0.071  # USD per 1M input tokens
_EXTRACT_OUT_PER_M = 0.10  # USD per 1M output tokens
_EXTRACT_MAX_OUT_TOKENS = 4096  # deep_extraction adapter cap (worst-case output)
_PROMPT_OVERHEAD_TOKENS = 1500  # rendered DEEP_EXTRACTION instruction template
_WORD_TO_TOKEN = 1.3  # conservative subword multiplier (same as the A/B harness)

# The 5 LIVE routing signals (the 3 dead ones — novelty/watchlist/price_impact —
# are also present in feature_scores_json but are permanently 1.0/0.0/0.0 in
# single-pass routing, so we drop them from the feature set; see routing.py).
_LIVE_FEATURES: tuple[str, ...] = (
    "entity_density",
    "source_reliability",
    "recency",
    "document_type",
    "extraction_yield",
)
# Feature whose NAME suggests label leakage but which is actually a pre-extraction
# prior (mentions+sections). Flagged in the manifest so the ablation can drop it.
_LEAKAGE_SUSPECT_FEATURE = "extraction_yield"


# ── Row model ─────────────────────────────────────────────────────────────────


@dataclass
class DatasetRow:
    """One labelable document = classifier input (title+subtitle) + features + label."""

    doc_id: str
    title: str
    subtitle: str  # lede proxy = first chunk text (chunk_index = 0)
    # the 5 persisted pre-extraction hand features
    entity_density: float
    source_reliability: float
    recency: float
    document_type: float
    extraction_yield: float  # PRE-extraction prior, NOT realised yield (see module docstring)
    routed_tier: str  # final tier wins (post novelty correction)
    n_relations: int
    n_claims: int
    n_events: int
    yielded: bool
    degraded: bool  # always False here — not DB-sourceable; see module docstring


# ── URL helpers (mirror extraction_quality_eval._normalize_sync_url) ─────────────


def _normalize_sync_url(url: str) -> str:
    """Strip SQLAlchemy async-driver suffixes so sync psycopg accepts the URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _db_url(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return _normalize_sync_url(v)
    return None


def _require_psycopg() -> Any:
    try:
        import psycopg

        return psycopg
    except ImportError:  # pragma: no cover - environment guard
        sys.exit("psycopg not installed — run: pip install psycopg")


# ── SQL (all READ-ONLY) ──────────────────────────────────────────────────────

# Per-doc yield counts from the KG. Three separate aggregates (the tables live in
# different partitioned families) returned as (doc_id, n) lists, merged in Python.
_REL_COUNTS_SQL = """
SELECT source_document_id::text AS doc_id, COUNT(*) AS n
FROM relation_evidence_raw
GROUP BY source_document_id;
"""
_CLAIM_COUNTS_SQL = """
SELECT doc_id::text AS doc_id, COUNT(*) AS n
FROM claims
GROUP BY doc_id;
"""
_EVENT_COUNTS_SQL = """
SELECT doc_id::text AS doc_id, COUNT(*) AS n
FROM events
GROUP BY doc_id;
"""

# Labelable population = full_pipeline routed docs, with their persisted features,
# title, and lede (first chunk). DISTINCT ON keeps the most recent routing row per
# doc (a doc can be re-routed). final_routing_tier wins when present.
_ROUTED_SQL = """
WITH routed AS (
    SELECT DISTINCT ON (rd.doc_id)
           rd.doc_id::text                                  AS doc_id,
           COALESCE(rd.final_routing_tier, rd.routing_tier) AS tier,
           rd.feature_scores_json                           AS feats
    FROM routing_decisions rd
    WHERE rd.processing_path = 'full_pipeline'
    ORDER BY rd.doc_id, rd.decided_at DESC
)
SELECT r.doc_id,
       r.tier,
       r.feats,
       COALESCE(dsm.title, '')                              AS title,
       (
           SELECT c.chunk_text
           FROM chunks c
           WHERE c.doc_id = r.doc_id::uuid AND c.chunk_text IS NOT NULL
           ORDER BY c.chunk_index
           LIMIT 1
       )                                                    AS lede
FROM routed r
LEFT JOIN document_source_metadata dsm ON dsm.doc_id = r.doc_id::uuid;
"""

# DLQ timeout count (degraded-doc proxy; cannot be mapped to specific doc_ids).
_DLQ_TIMEOUT_SQL = """
SELECT COUNT(*) FROM dead_letter_queue WHERE error_detail LIKE 'message_processing_timeout%';
"""

# Average word_count of LIGHT (section_embeddings_only) docs — basis for the
# counterfactual extraction-cost estimate of a de-biasing sample.
_LIGHT_WORDCOUNT_SQL = """
SELECT COALESCE(AVG(dsm.word_count), 0)::float, COUNT(*)
FROM document_source_metadata dsm
JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
WHERE rd.processing_path = 'section_embeddings_only' AND dsm.word_count IS NOT NULL;
"""


# ── Yield-count assembly ─────────────────────────────────────────────────────


def _fetch_counts(cur: Any, sql: str) -> dict[str, int]:
    cur.execute(sql)
    return {row[0]: int(row[1]) for row in cur.fetchall()}


def load_yield_counts(intel_url: str) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Pull per-doc (relations, claims, events) counts from intelligence_db."""
    psycopg = _require_psycopg()
    with psycopg.connect(intel_url, autocommit=True) as conn, conn.cursor() as cur:
        rels = _fetch_counts(cur, _REL_COUNTS_SQL)
        claims = _fetch_counts(cur, _CLAIM_COUNTS_SQL)
        events = _fetch_counts(cur, _EVENT_COUNTS_SQL)
    return rels, claims, events


def _subtitle_from_lede(lede: str | None, max_chars: int = 300) -> str:
    """Derive a subtitle/lede string from the first chunk text.

    The schema has no dedicated subtitle column, so the article lede (first chunk)
    is the best available stand-in for the EmbeddingGemma ``title + subtitle``
    input. Trim to a sentence-ish window so the classifier input stays compact.
    """
    if not lede:
        return ""
    text = " ".join(lede.split())  # collapse whitespace
    if len(text) <= max_chars:
        return text
    # cut at the last sentence boundary before max_chars, else hard-cut
    head = text[:max_chars]
    dot = head.rfind(". ")
    return head[: dot + 1] if dot > 60 else head


def build_rows(nlp_url: str, intel_url: str) -> tuple[list[DatasetRow], dict[str, Any]]:
    """Assemble the full labelable dataset + the manifest stats. READ-ONLY."""
    psycopg = _require_psycopg()
    rels, claims, events = load_yield_counts(intel_url)

    rows: list[DatasetRow] = []
    tier_counts: dict[str, int] = {}
    tier_positive: dict[str, int] = {}
    missing_title = 0
    missing_subtitle = 0

    with psycopg.connect(nlp_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(_ROUTED_SQL)
            routed = cur.fetchall()
        with conn.cursor() as cur:
            cur.execute(_DLQ_TIMEOUT_SQL)
            dlq_timeouts = int(cur.fetchone()[0])
        with conn.cursor() as cur:
            cur.execute(_LIGHT_WORDCOUNT_SQL)
            light_avg_words, light_count = cur.fetchone()

    for doc_id, tier, feats, title, lede in routed:
        feats = feats or {}
        n_rel = rels.get(doc_id, 0)
        n_cl = claims.get(doc_id, 0)
        n_ev = events.get(doc_id, 0)
        yielded = (n_rel + n_cl + n_ev) >= 1

        title_s = (title or "").strip()
        subtitle = _subtitle_from_lede(lede)
        if not title_s:
            missing_title += 1
        if not subtitle:
            missing_subtitle += 1

        tier_norm = str(tier or "unknown")
        tier_counts[tier_norm] = tier_counts.get(tier_norm, 0) + 1
        if yielded:
            tier_positive[tier_norm] = tier_positive.get(tier_norm, 0) + 1

        rows.append(
            DatasetRow(
                doc_id=doc_id,
                title=title_s,
                subtitle=subtitle,
                entity_density=float(feats.get("entity_density", 0.0)),
                source_reliability=float(feats.get("source_reliability", 0.0)),
                recency=float(feats.get("recency", 0.0)),
                document_type=float(feats.get("document_type", 0.0)),
                extraction_yield=float(feats.get("extraction_yield", 0.0)),
                routed_tier=tier_norm,
                n_relations=n_rel,
                n_claims=n_cl,
                n_events=n_ev,
                yielded=yielded,
                degraded=False,  # not DB-sourceable — see module docstring
            )
        )

    n = len(rows)
    n_pos = sum(1 for r in rows if r.yielded)
    manifest: dict[str, Any] = {
        "generated_by": "scripts/eval/routing_classifier_dataset.py (PLAN-0111 C-3)",
        "label_definition": "yielded = (n_relations + n_claims + n_events) >= 1",
        "join_keys": {
            "relations": "intelligence_db.relation_evidence_raw.source_document_id",
            "claims": "intelligence_db.claims.doc_id",
            "events": "intelligence_db.events.doc_id",
            "features": "nlp_db.routing_decisions.feature_scores_json",
        },
        "labelable_population": "processing_path = 'full_pipeline' (MEDIUM/DEEP only)",
        "n_rows": n,
        "n_positive": n_pos,
        "positive_rate": round(n_pos / n, 4) if n else 0.0,
        "tier_breakdown": {
            t: {
                "n": tier_counts[t],
                "positive": tier_positive.get(t, 0),
                "positive_rate": round(tier_positive.get(t, 0) / tier_counts[t], 4) if tier_counts[t] else 0.0,
            }
            for t in sorted(tier_counts)
        },
        "title_coverage": {
            "with_title": n - missing_title,
            "missing_title": missing_title,
            "title_coverage_rate": round((n - missing_title) / n, 4) if n else 0.0,
            "with_subtitle": n - missing_subtitle,
            "missing_subtitle": missing_subtitle,
        },
        "leakage_assessment": {
            "leakage_suspect_feature": _LEAKAGE_SUSPECT_FEATURE,
            "verdict": (
                "extraction_yield is a PRE-extraction prior "
                "(0.6*min(1,mentions/20)+0.4*min(1,sections/8)), NOT realised yield — "
                "does NOT leak the label, but flagged so the ablation can drop it."
            ),
            "all_features_pre_extraction": True,
        },
        "degraded_handling": {
            "persisted_per_doc": False,
            "dlq_timeout_rows": dlq_timeouts,
            "note": (
                "Merged extraction result with degraded/timed_out_windows is logged "
                "(deep_extraction.complete) but NOT persisted. DLQ timeouts cannot be "
                "mapped to specific doc_ids. Zero-yield rows may include silently "
                "partial-timed-out docs; recommend persisting the merged result for "
                "clean labels in C-4+."
            ),
        },
        "light_extraction_cost_basis": {
            "light_doc_count": int(light_count or 0),
            "light_avg_word_count": round(float(light_avg_words or 0.0), 1),
        },
    }
    return rows, manifest


# ── LIGHT-sample cost estimate (no spend) ────────────────────────────────────


def estimate_light_cost(avg_words: float, sample_size: int) -> dict[str, Any]:
    """Estimate the USD cost of extracting ``sample_size`` LIGHT docs at the 235B rate.

    Gives the counterfactual yield labels for the cheap tier the router most needs
    to get right (de-biasing). We do NOT run extraction — this is an estimate only.
    """
    in_tokens_per_doc = (avg_words + _PROMPT_OVERHEAD_TOKENS) * _WORD_TO_TOKEN
    out_tokens_per_doc = _EXTRACT_MAX_OUT_TOKENS  # worst-case (real output is lower)
    total_in = in_tokens_per_doc * sample_size
    total_out = out_tokens_per_doc * sample_size
    usd = (total_in / 1e6) * _EXTRACT_IN_PER_M + (total_out / 1e6) * _EXTRACT_OUT_PER_M
    return {
        "sample_size": sample_size,
        "avg_words_per_doc": round(avg_words, 1),
        "est_input_tokens": int(total_in),
        "est_output_tokens_worst_case": int(total_out),
        "rate_in_per_1m_usd": _EXTRACT_IN_PER_M,
        "rate_out_per_1m_usd": _EXTRACT_OUT_PER_M,
        "est_usd_worst_case": round(usd, 4),
    }


# ── Persistence ──────────────────────────────────────────────────────────────


def _out_dir(out: str) -> Path:
    p = Path(out)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_csv(path: Path, rows: list[DatasetRow]) -> None:
    fieldnames = list(asdict(rows[0]).keys()) if rows else [f.name for f in DatasetRow.__dataclass_fields__.values()]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


# ── CLI commands ─────────────────────────────────────────────────────────────


def cmd_build(args: argparse.Namespace) -> None:
    nlp_url = _db_url("NLP_DB_URL_TEST", "NLP_DB_URL")
    intel_url = _db_url("INTELLIGENCE_DB_URL_TEST", "INTELLIGENCE_DB_URL")
    if not nlp_url:
        sys.exit("NLP_DB_URL (or NLP_DB_URL_TEST) must be set.")
    if not intel_url:
        sys.exit("INTELLIGENCE_DB_URL (or INTELLIGENCE_DB_URL_TEST) must be set.")

    out = _out_dir(args.out)
    rows, manifest = build_rows(nlp_url, intel_url)

    # Append the default-sized LIGHT-extraction cost estimate to the manifest.
    light = manifest["light_extraction_cost_basis"]
    manifest["light_extraction_cost_estimate"] = estimate_light_cost(
        float(light["light_avg_word_count"]), args.light_sample_size
    )

    write_csv(out / "routing_dataset.csv", rows)
    (out / "routing_dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} labelable rows → {out / 'routing_dataset.csv'}")
    print(
        f"Positive rate: {manifest['positive_rate']:.1%} "
        f"({manifest['n_positive']}/{manifest['n_rows']})  |  "
        f"title coverage: {manifest['title_coverage']['title_coverage_rate']:.1%}"
    )
    for t, st in manifest["tier_breakdown"].items():
        print(f"  {t}: n={st['n']} positive_rate={st['positive_rate']:.1%}")
    print(f"Manifest → {out / 'routing_dataset_manifest.json'}")


def cmd_estimate_light_cost(args: argparse.Namespace) -> None:
    nlp_url = _db_url("NLP_DB_URL_TEST", "NLP_DB_URL")
    if not nlp_url:
        sys.exit("NLP_DB_URL (or NLP_DB_URL_TEST) must be set to read the LIGHT word-count basis.")
    psycopg = _require_psycopg()
    with psycopg.connect(nlp_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_LIGHT_WORDCOUNT_SQL)
        avg_words, _ = cur.fetchone()
    est = estimate_light_cost(float(avg_words or 0.0), args.sample_size)
    print(json.dumps(est, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="build the labeled dataset + manifest from the live DBs")
    pb.add_argument("--out", default="results/routing_dataset")
    pb.add_argument("--light-sample-size", type=int, default=400, help="LIGHT de-bias sample size for cost estimate")
    pb.set_defaults(func=cmd_build)

    pe = sub.add_parser("estimate-light-cost", help="estimate USD to extract N LIGHT docs (no spend)")
    pe.add_argument("--sample-size", type=int, default=400)
    pe.set_defaults(func=cmd_estimate_light_cost)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
