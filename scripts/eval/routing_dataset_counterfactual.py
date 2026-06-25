#!/usr/bin/env python3
"""Counterfactual LIGHT + negative-verification labels for the routing dataset (PLAN-0111 C-3b).

PURPOSE
-------
The C-3 routing dataset (``scripts/eval/routing_classifier_dataset.py`` →
``results/routing_dataset/``) has two known defects documented in the feasibility
report (``docs/audits/2026-06-12-routing-classifier-dataset-feasibility.md``):

  1. **Selection bias** — extraction only ever ran on ``full_pipeline`` (MEDIUM/DEEP)
     docs. Of 3,903 LIGHT (``section_embeddings_only``) docs, exactly 1 was ever
     extracted, so the LIGHT tier is effectively *unlabeled*. The classifier the
     router will use must score LIGHT docs, so we need real LIGHT yield labels.
  2. **Possibly-masked negatives** — before the silent-except fix (commit
     ``ee76aa957``), a timed-out extraction window was substituted as a clean
     all-zero result. A ``yielded=0`` row in the dataset *might* therefore be a
     false negative (the model timed out, not "found nothing").

This script spends a HARD-CAPPED extraction budget to fix both:

  * **LIGHT counterfactual** — extract N=400 random LIGHT docs through the SAME
    production path and record their real ``yielded`` label.
  * **Negative verification** — re-extract N=200 random docs currently labeled
    ``yielded=0`` and measure how many actually yield ≥1 (the false-negative rate
    of the existing negatives), with a Wilson confidence interval.

FAITHFULNESS
------------
The counterfactual labels MUST be produced by the SAME extraction path as
production or they are not comparable to the C-3 labels. We therefore REUSE
``scripts/eval/extraction_quality_eval.py`` — its ``GoldenArticle`` input model
(entities = order-preserving de-dup of ``entity_mentions.mention_text``; text =
``chunks.chunk_text`` joined in ``chunk_index`` order, truncated to the single-window
budget) and its ``run_model_on_article`` runner, which renders the real
``prompts.extraction.deep.DEEP_EXTRACTION`` template and calls the production
extraction model with the production decode params (temperature=0,
``response_format=json_object``, ``reasoning_effort=none``). We do NOT reinvent the
prompt or call the model ad-hoc. The model is the production
``extraction_api_model_id`` (``Qwen/Qwen3-235B-A22B-Instruct-2507``; confirmed in
``services/nlp-pipeline/configs/docker.env`` + ``config.py``).

TIMEOUT / DEGRADED HANDLING (don't re-contaminate the labels)
-------------------------------------------------------------
A timeout / rate-limit is **missing data, not a true negative** — recording it as
0-yield is exactly the bug the silent-except fix removed. The harness surfaces any
HTTP/timeout failure as ``status='api_error'`` (this includes 429 rate-limit, which
is common because we share the production DeepInfra key). We:
  * retry an ``api_error`` doc up to ``--max-retries`` times with exponential
    backoff (a 429 usually clears on retry), and
  * if it STILL fails, mark the doc ``degraded=true`` and EXCLUDE it from the label
    set — it is recorded separately in the run artefact and the report, never
    counted as a 0-yield.
A ``json_error`` (model returned non-JSON) is a genuine extraction outcome with no
artefacts → ``yielded=0`` (not degraded); this matches how the production block
treats an unparseable window (empty result).

HARD CAP
--------
Exactly N_LIGHT (default 400) + N_NEG (default 200) = 600 docs are extracted, once
each (plus bounded retries for degraded docs). The runner refuses to exceed the cap
and aborts with a clear message if the projected spend (tracked from real per-doc
``usage``) exceeds ``--abort-usd`` (default $1.00, well above the ~$0.36 estimate).

OUTPUT (all under ``--out``, default ``results/routing_dataset/counterfactual``)
--------------------------------------------------------------------------------
  light_sample.json        — frozen 400 LIGHT extraction inputs + features (seeded)
  negative_sample.json     — frozen 200 negative extraction inputs + old label (seeded)
  light_runs.json          — per-doc extraction result + tokens + degraded flag
  negative_runs.json       — per-doc extraction result + tokens + old/new label
  augmented_light_rows.csv  — the 400 newly-labeled LIGHT rows in the dataset schema
  negative_verification.json — FN rate + Wilson CI + old/new label per doc
  run_manifest.json        — sample sizes, ACTUAL $ + tokens, degraded counts, rates

The augmented full dataset (original 14,742 + 400 LIGHT) is written by the
``augment`` command to ``results/routing_dataset/routing_dataset_augmented.csv``
(gitignored, like the base CSV). We NEVER flip the 200 negative labels in-place —
the verification result is a separate manifest recording old vs new label.

USAGE
-----
  # 1. Pick the seeded samples (READ-ONLY; needs NLP_DB_URL + INTELLIGENCE_DB_URL)
  NLP_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/nlp_db \
  INTELLIGENCE_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/intelligence_db \
      python scripts/eval/routing_dataset_counterfactual.py select-samples

  # 2. Run the faithful extraction on all 600 (needs the extraction API key)
  DEEPINFRA_API_KEY=$NLP_PIPELINE_EXTRACTION_API_KEY \
      python scripts/eval/routing_dataset_counterfactual.py extract

  # 3. Analyse + write the verification manifest
  python scripts/eval/routing_dataset_counterfactual.py analyze

  # 4. Build the augmented dataset CSV (base + 400 LIGHT rows)
  python scripts/eval/routing_dataset_counterfactual.py augment
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Reuse the C-3 harness (faithful production extraction path) and the C-3 dataset
# builder (feature reconstruction + row schema) so we never drift from either.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extraction_quality_eval as eqe  # (path shim above is intentional)
import routing_classifier_dataset as rcd

# ── Hard caps + defaults ─────────────────────────────────────────────────────
_DEFAULT_N_LIGHT = 400
_DEFAULT_N_NEG = 200
_DEFAULT_SEED = 20260612  # fixed for reproducibility (the C-3b run date)
_HARD_CAP_DOCS = 600  # N_LIGHT + N_NEG ceiling — the runner refuses to exceed this
_DEFAULT_ABORT_USD = 1.00  # abort if real tracked spend exceeds this (est. is ~$0.36)
_DEFAULT_MAX_RETRIES = 3  # per-doc retries for api_error (429/timeout) before degraded
_PROD_MODEL = eqe._PROD_EXTRACTION_MODEL  # Qwen/Qwen3-235B-A22B-Instruct-2507

# DeepInfra 235B published rate (mirrors both sibling scripts) for the $ tally when
# the API response omits ``estimated_cost`` (it usually includes it; this is a fallback).
_IN_PER_M = rcd._EXTRACT_IN_PER_M  # 0.071
_OUT_PER_M = rcd._EXTRACT_OUT_PER_M  # 0.10


# ── SQL (READ-ONLY) ──────────────────────────────────────────────────────────

# LIGHT tier = docs routed to ``section_embeddings_only`` whose FINAL tier is 'light'
# (a handful of section_embeddings_only docs carry a 'medium' final tier — we exclude
# those so the sample is unambiguously the cheap tier the router most needs to learn).
# We pull the same persisted features + title + lede the C-3 builder uses, so each
# sampled doc slots straight into the dataset schema.
_LIGHT_CANDIDATES_SQL = """
WITH routed AS (
    SELECT DISTINCT ON (rd.doc_id)
           rd.doc_id::text                                  AS doc_id,
           COALESCE(rd.final_routing_tier, rd.routing_tier) AS tier,
           rd.feature_scores_json                           AS feats
    FROM routing_decisions rd
    WHERE rd.processing_path = 'section_embeddings_only'
    ORDER BY rd.doc_id, rd.decided_at DESC
)
SELECT r.doc_id, r.tier, r.feats,
       COALESCE(dsm.title, '')        AS title,
       dsm.source_name                AS source_name,
       dsm.published_at               AS published_at,
       COALESCE(dsm.word_count, 0)    AS word_count
FROM routed r
LEFT JOIN document_source_metadata dsm ON dsm.doc_id = r.doc_id::uuid
WHERE r.tier = 'light'
  AND EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id = r.doc_id::uuid AND c.chunk_text IS NOT NULL);
"""

# Reconstruct one doc's extraction inputs exactly like the C-3 harness / production:
# text = chunk_text joined by chunk_index; entities = order-preserving mention de-dup.
_DOC_TEXT_SQL = """
SELECT string_agg(c.chunk_text, ' ' ORDER BY c.chunk_index) AS doc_text
FROM chunks c
WHERE c.doc_id = %(doc_id)s::uuid AND c.chunk_text IS NOT NULL;
"""
_DOC_MENTIONS_SQL = """
SELECT em.mention_text
FROM entity_mentions em
WHERE em.doc_id = %(doc_id)s::uuid
ORDER BY em.char_start, em.mention_id;
"""
_DOC_LEDE_SQL = """
SELECT c.chunk_text FROM chunks c
WHERE c.doc_id = %(doc_id)s::uuid AND c.chunk_text IS NOT NULL
ORDER BY c.chunk_index LIMIT 1;
"""


# ── Sample-row models ────────────────────────────────────────────────────────


@dataclass
class LightSample:
    """One frozen LIGHT extraction input + the 5 hand-features (for dataset slotting)."""

    doc_id: str
    title: str
    subtitle: str
    entity_density: float
    source_reliability: float
    recency: float
    document_type: float
    extraction_yield: float
    routed_tier: str
    word_count: int
    # frozen extraction inputs (identical reconstruction to the C-3 harness)
    entities: str
    text: str


@dataclass
class NegativeSample:
    """One frozen negative (current yielded=0) extraction input + its old label."""

    doc_id: str
    title: str
    old_yielded: bool  # always False (we sample from yielded=0)
    old_n_relations: int
    old_n_claims: int
    old_n_events: int
    entities: str
    text: str


@dataclass
class DocRun:
    """Extraction outcome for one sampled doc (LIGHT or negative)."""

    doc_id: str
    status: str  # "ok" | "json_error" | "degraded" (api_error after retries)
    n_events: int
    n_claims: int
    n_relations: int
    yielded: bool  # (n_events+n_claims+n_relations) >= 1 — only meaningful if not degraded
    degraded: bool
    attempts: int
    tokens_in: int
    tokens_out: int
    usd: float
    error: str | None = None


# ── Sample selection (deterministic, READ-ONLY) ──────────────────────────────


def _freeze_inputs(cur: Any, doc_id: str) -> tuple[str, str] | None:
    """Reconstruct (entities, text) for a doc exactly like the C-3 harness.

    Returns None if the doc has no reconstructable chunk text (skip it).
    """
    cur.execute(_DOC_TEXT_SQL, {"doc_id": doc_id})
    row = cur.fetchone()
    doc_text = (row[0] if row else None) or ""
    if not doc_text.strip():
        return None
    # Truncate to the single-window budget the pipeline uses for ≤24k-token docs
    # (LIGHT docs average ~553 words so this almost never triggers — kept for parity).
    words = doc_text.split()
    if len(words) > eqe._SINGLE_WINDOW_TOKEN_LIMIT:
        doc_text = " ".join(words[: eqe._SINGLE_WINDOW_TOKEN_LIMIT])

    cur.execute(_DOC_MENTIONS_SQL, {"doc_id": doc_id})
    mention_names = list(dict.fromkeys(r[0] for r in cur.fetchall() if r[0]))
    entities_str = ", ".join(mention_names) if mention_names else "none identified"
    return entities_str, doc_text


def select_light_sample(nlp_url: str, n: int, seed: int) -> list[LightSample]:
    """Pick ``n`` random LIGHT docs (seeded) and freeze their extraction inputs."""
    psycopg = rcd._require_psycopg()
    with psycopg.connect(nlp_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_LIGHT_CANDIDATES_SQL)
        candidates = cur.fetchall()
        if not candidates:
            sys.exit("No LIGHT (section_embeddings_only, final tier 'light') docs found.")
        # Deterministic: sort by doc_id for a stable universe, then seeded-sample.
        candidates.sort(key=lambda r: r[0])
        rng = random.Random(seed)  # noqa: S311 — reproducible sampling, not cryptographic
        picks = candidates if len(candidates) <= n else rng.sample(candidates, n)
        picks.sort(key=lambda r: r[0])  # stable output order

        out: list[LightSample] = []
        for doc_id, tier, feats, title, _src, _pub, word_count in picks:
            frozen = _freeze_inputs(cur, doc_id)
            if frozen is None:
                continue
            entities, text = frozen
            cur.execute(_DOC_LEDE_SQL, {"doc_id": doc_id})
            lede_row = cur.fetchone()
            feats = feats or {}
            out.append(
                LightSample(
                    doc_id=doc_id,
                    title=(title or "").strip(),
                    subtitle=rcd._subtitle_from_lede(lede_row[0] if lede_row else None),
                    entity_density=float(feats.get("entity_density", 0.0)),
                    source_reliability=float(feats.get("source_reliability", 0.0)),
                    recency=float(feats.get("recency", 0.0)),
                    document_type=float(feats.get("document_type", 0.0)),
                    extraction_yield=float(feats.get("extraction_yield", 0.0)),
                    routed_tier=str(tier or "light"),
                    word_count=int(word_count or len(text.split())),
                    entities=entities,
                    text=text,
                )
            )
    return out


def select_negative_sample(nlp_url: str, intel_url: str, n: int, seed: int) -> list[NegativeSample]:
    """Pick ``n`` random docs currently labeled yielded=0 (seeded) and freeze inputs.

    We recompute the current label the SAME way the C-3 builder does (left-join the
    KG yield counts onto the full_pipeline routed docs) so the "old label" we verify
    against is byte-identical to the shipped dataset.
    """
    psycopg = rcd._require_psycopg()
    rels, claims, events = rcd.load_yield_counts(intel_url)

    with psycopg.connect(nlp_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(rcd._ROUTED_SQL)
        routed = cur.fetchall()
        # The current negatives = full_pipeline docs whose KG yield count is 0.
        negatives = []
        for doc_id, _tier, _feats, title, _lede in routed:
            n_rel = rels.get(doc_id, 0)
            n_cl = claims.get(doc_id, 0)
            n_ev = events.get(doc_id, 0)
            if (n_rel + n_cl + n_ev) == 0:
                negatives.append((doc_id, title, n_rel, n_cl, n_ev))
        if not negatives:
            sys.exit("No yielded=0 docs found in the labelable population.")
        negatives.sort(key=lambda r: r[0])
        rng = random.Random(seed + 1)  # noqa: S311 — distinct reproducible stream from LIGHT
        picks = negatives if len(negatives) <= n else rng.sample(negatives, n)
        picks.sort(key=lambda r: r[0])

        out: list[NegativeSample] = []
        for doc_id, title, n_rel, n_cl, n_ev in picks:
            frozen = _freeze_inputs(cur, doc_id)
            if frozen is None:
                continue
            entities, text = frozen
            out.append(
                NegativeSample(
                    doc_id=doc_id,
                    title=(title or "").strip(),
                    old_yielded=False,
                    old_n_relations=n_rel,
                    old_n_claims=n_cl,
                    old_n_events=n_ev,
                    entities=entities,
                    text=text,
                )
            )
    return out


# ── Extraction (faithful, via the C-3 harness) ───────────────────────────────


def _usd_for(tokens_in: int, tokens_out: int, api_cost: float | None) -> float:
    """Prefer DeepInfra's reported ``estimated_cost``; fall back to the published rate."""
    if api_cost and api_cost > 0:
        return float(api_cost)
    return (tokens_in / 1e6) * _IN_PER_M + (tokens_out / 1e6) * _OUT_PER_M


def _extract_one(
    client: Any,
    api_key: str,
    base_url: str,
    article: eqe.GoldenArticle,
    max_retries: int,
) -> DocRun:
    """Run one doc through the production extraction path with 429/timeout retry.

    A persistent ``api_error`` (timeout / 429 / 5xx) after ``max_retries`` is marked
    ``degraded`` and EXCLUDED from the label set — it is missing data, not a true
    negative (respects the silent-except-fix semantics from commit ee76aa957).
    """
    last_err: str | None = None
    for attempt in range(1, max_retries + 1):
        run = eqe.run_model_on_article(client, api_key, base_url, _PROD_MODEL, article)
        # The harness's estimated_cost isn't surfaced on ModelRunResult; recompute
        # from the token usage it captured (DeepInfra bills per-token at the 235B rate).
        usd = _usd_for(run.tokens_in, run.tokens_out, None)
        if run.status == "api_error":
            last_err = run.error
            if attempt < max_retries:
                # Exponential backoff with jitter — 429s from the shared production
                # key usually clear within a few seconds.
                time.sleep(min(30.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0, 1.0))  # noqa: S311
                continue
            # Exhausted retries → degraded (excluded from labels), record separately.
            return DocRun(
                doc_id=article.doc_id,
                status="degraded",
                n_events=0,
                n_claims=0,
                n_relations=0,
                yielded=False,
                degraded=True,
                attempts=attempt,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                usd=usd,
                error=last_err,
            )
        # ok or json_error — both are genuine extraction outcomes.
        n_ev = run.n_events or 0
        n_cl = run.n_claims or 0
        n_rel = run.n_relations or 0
        return DocRun(
            doc_id=article.doc_id,
            status=run.status,  # "ok" | "json_error"
            n_events=n_ev,
            n_claims=n_cl,
            n_relations=n_rel,
            yielded=(n_ev + n_cl + n_rel) >= 1,
            degraded=False,
            attempts=attempt,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            usd=usd,
            error=run.error,
        )
    # Unreachable (loop always returns), but satisfies the type checker.
    return DocRun(article.doc_id, "degraded", 0, 0, 0, False, True, max_retries, 0, 0, 0.0, last_err)


def _to_golden(doc_id: str, title: str, entities: str, text: str) -> eqe.GoldenArticle:
    """Adapt a sample row into the harness's GoldenArticle (only fields the runner reads)."""
    return eqe.GoldenArticle(
        doc_id=doc_id,
        title=title,
        source_name=None,
        published_at=None,
        routing_tier=None,
        span_bucket="",  # unused by run_model_on_article
        word_count=len(text.split()),
        entity_count=0,  # unused by run_model_on_article
        entities=entities,
        text=text,
    )


def _load_runs(path: Path) -> dict[str, DocRun]:
    """Load already-extracted DocRuns from a checkpoint file, keyed by doc_id."""
    if not path.exists():
        return {}
    return {d["doc_id"]: DocRun(**d) for d in _load_json(path)}


def run_extraction(
    light: list[LightSample],
    negatives: list[NegativeSample],
    *,
    out: Path,
    max_retries: int,
    abort_usd: float,
    checkpoint_every: int = 20,
) -> tuple[list[DocRun], list[DocRun], dict[str, Any]]:
    """Extract all LIGHT + negative docs once each. Hard-capped at 600 docs.

    RESUMABLE: re-loads any existing ``light_runs.json`` / ``negative_runs.json`` in
    ``out``, skips doc_ids already extracted, and flushes both files every
    ``checkpoint_every`` new docs — so a kill (e.g. the 600s agent watchdog) loses at
    most ``checkpoint_every`` docs of work and a re-run continues where it left off.

    Aborts mid-run if the REAL tracked spend exceeds ``abort_usd`` (a safety net far
    above the ~$0.36 estimate) so a pathological cost can never blow the budget.
    """
    api_key = os.environ.get("DEEPINFRA_API_KEY") or os.environ.get("NLP_PIPELINE_EXTRACTION_API_KEY")
    if not api_key:
        sys.exit("Set DEEPINFRA_API_KEY (or NLP_PIPELINE_EXTRACTION_API_KEY) to run extraction.")
    base_url = os.environ.get("DEEPINFRA_BASE_URL", eqe._DEEPINFRA_BASE_URL)

    total = len(light) + len(negatives)
    if total > _HARD_CAP_DOCS:
        sys.exit(f"Refusing to extract {total} docs — hard cap is {_HARD_CAP_DOCS}.")

    light_path = out / "light_runs.json"
    neg_path = out / "negative_runs.json"
    light_by_id = _load_runs(light_path)
    neg_by_id = _load_runs(neg_path)
    # Spend already incurred by checkpointed runs counts toward the budget cap.
    spent = sum(r.usd for r in (*light_by_id.values(), *neg_by_id.values()))
    done = set(light_by_id) | set(neg_by_id)
    aborted = False
    new_since_flush = 0

    def _flush() -> None:
        _write_json(light_path, [asdict(r) for r in light_by_id.values()])
        _write_json(neg_path, [asdict(r) for r in neg_by_id.values()])

    if done:
        print(f"Resuming: {len(done)} docs already extracted (cum spend ${spent:.4f}); skipping them.")

    with eqe._make_clients(eqe._EXTRACTION_TIMEOUT_S) as client:
        plan: list[tuple[str, Any]] = [("light", s) for s in light] + [("neg", s) for s in negatives]
        for i, (kind, sample) in enumerate(plan, 1):
            if sample.doc_id in done:
                continue
            if spent > abort_usd:
                print(f"!! ABORT: tracked spend ${spent:.4f} exceeded --abort-usd ${abort_usd:.2f}. Stopping.")
                aborted = True
                break
            article = _to_golden(sample.doc_id, sample.title, sample.entities, sample.text)
            run = _extract_one(client, api_key, base_url, article, max_retries)
            spent += run.usd
            (light_by_id if kind == "light" else neg_by_id)[sample.doc_id] = run
            new_since_flush += 1
            print(
                f"[{kind}] {i}/{total} doc={sample.doc_id[:8]} status={run.status} "
                f"y={run.yielded} ev/cl/rel={run.n_events}/{run.n_claims}/{run.n_relations} "
                f"att={run.attempts} ${run.usd:.5f} cum=${spent:.4f}"
            )
            if new_since_flush >= checkpoint_every:
                _flush()
                new_since_flush = 0
                print(f"  .. checkpoint flushed ({len(light_by_id) + len(neg_by_id)}/{total} done)")

    _flush()  # final flush
    light_runs = list(light_by_id.values())
    neg_runs = list(neg_by_id.values())

    tally = {
        "docs_extracted": len(light_runs) + len(neg_runs),
        "light_extracted": len(light_runs),
        "negatives_extracted": len(neg_runs),
        "total_tokens_in": sum(r.tokens_in for r in light_runs + neg_runs),
        "total_tokens_out": sum(r.tokens_out for r in light_runs + neg_runs),
        "actual_usd": round(spent, 5),
        "aborted_on_budget": aborted,
        "degraded_excluded": sum(1 for r in light_runs + neg_runs if r.degraded),
    }
    return light_runs, neg_runs, tally


# ── Analysis ─────────────────────────────────────────────────────────────────


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for a binomial proportion (robust for small/extreme p)."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def analyze_light(light_runs: list[DocRun]) -> dict[str, Any]:
    """LIGHT positive rate over the NON-degraded docs (degraded excluded)."""
    labelable = [r for r in light_runs if not r.degraded]
    n = len(labelable)
    pos = sum(1 for r in labelable if r.yielded)
    lo, hi = _wilson_ci(pos, n)
    return {
        "n_extracted": len(light_runs),
        "n_degraded_excluded": sum(1 for r in light_runs if r.degraded),
        "n_labelable": n,
        "n_positive": pos,
        "positive_rate": round(pos / n, 4) if n else 0.0,
        "positive_rate_ci95": [round(lo, 4), round(hi, 4)],
    }


def analyze_negatives(neg_runs: list[DocRun], samples: list[NegativeSample]) -> dict[str, Any]:
    """False-negative rate: of docs labeled yielded=0, how many now yield ≥1."""
    by_id = {s.doc_id: s for s in samples}
    labelable = [r for r in neg_runs if not r.degraded]
    n = len(labelable)
    flipped = [r for r in labelable if r.yielded]
    k = len(flipped)
    lo, hi = _wilson_ci(k, n)
    return {
        "n_extracted": len(neg_runs),
        "n_degraded_excluded": sum(1 for r in neg_runs if r.degraded),
        "n_labelable": n,
        "n_flipped_to_positive": k,
        "false_negative_rate": round(k / n, 4) if n else 0.0,
        "false_negative_rate_ci95": [round(lo, 4), round(hi, 4)],
        "recommendation": (
            "RE-EXTRACT ALL NEGATIVES — FN rate exceeds the ~15% usability threshold."
            if (n and k / n > 0.15)
            else "USE AS-IS — FN rate is below the ~15% threshold; the negatives are usable."
        ),
        "flipped_examples": [
            {
                "doc_id": r.doc_id,
                "title": (by_id[r.doc_id].title[:120] if r.doc_id in by_id else ""),
                "new_yield": {"events": r.n_events, "claims": r.n_claims, "relations": r.n_relations},
            }
            for r in flipped[:10]
        ],
    }


# ── Persistence ──────────────────────────────────────────────────────────────


def _out_dir(out: str) -> Path:
    p = Path(out)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ── CLI commands ─────────────────────────────────────────────────────────────


def cmd_select_samples(args: argparse.Namespace) -> None:
    nlp_url = rcd._db_url("NLP_DB_URL_TEST", "NLP_DB_URL")
    intel_url = rcd._db_url("INTELLIGENCE_DB_URL_TEST", "INTELLIGENCE_DB_URL")
    if not nlp_url or not intel_url:
        sys.exit("NLP_DB_URL and INTELLIGENCE_DB_URL must both be set.")
    out = _out_dir(args.out)

    light = select_light_sample(nlp_url, args.n_light, args.seed)
    negatives = select_negative_sample(nlp_url, intel_url, args.n_neg, args.seed)
    _write_json(out / "light_sample.json", [asdict(s) for s in light])
    _write_json(out / "negative_sample.json", [asdict(s) for s in negatives])
    _write_json(
        out / "sample_selection_meta.json",
        {
            "seed": args.seed,
            "requested_light": args.n_light,
            "requested_negatives": args.n_neg,
            "selected_light": len(light),
            "selected_negatives": len(negatives),
            "model": _PROD_MODEL,
            "note": "Seeded, deterministic. Re-running select-samples reproduces these exact doc_ids.",
        },
    )
    print(f"Selected {len(light)} LIGHT + {len(negatives)} negative docs (seed={args.seed}) → {out}")


def cmd_extract(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    light = [LightSample(**s) for s in _load_json(out / "light_sample.json")]
    negatives = [NegativeSample(**s) for s in _load_json(out / "negative_sample.json")]
    if args.limit:  # cheap-run cap for smoke tests
        light = light[: args.limit]
        negatives = negatives[: args.limit]
    light_runs, neg_runs, tally = run_extraction(
        light, negatives, out=out, max_retries=args.max_retries, abort_usd=args.abort_usd
    )
    _write_json(out / "light_runs.json", [asdict(r) for r in light_runs])
    _write_json(out / "negative_runs.json", [asdict(r) for r in neg_runs])
    _write_json(out / "extraction_tally.json", tally)
    print(
        f"\nExtracted {tally['docs_extracted']} docs | ACTUAL ${tally['actual_usd']} | "
        f"tokens in/out {tally['total_tokens_in']}/{tally['total_tokens_out']} | "
        f"degraded-excluded {tally['degraded_excluded']}"
    )


def cmd_analyze(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    light_runs = [DocRun(**r) for r in _load_json(out / "light_runs.json")]
    neg_runs = [DocRun(**r) for r in _load_json(out / "negative_runs.json")]
    neg_samples = [NegativeSample(**s) for s in _load_json(out / "negative_sample.json")]
    tally = _load_json(out / "extraction_tally.json")

    light_analysis = analyze_light(light_runs)
    neg_analysis = analyze_negatives(neg_runs, neg_samples)

    # Old-vs-new label record for the negatives (we NEVER flip in place).
    by_id = {s.doc_id: s for s in neg_samples}
    neg_label_records = [
        {
            "doc_id": r.doc_id,
            "old_yielded": False,
            "new_yielded": (r.yielded if not r.degraded else None),
            "degraded": r.degraded,
            "new_counts": {"events": r.n_events, "claims": r.n_claims, "relations": r.n_relations},
            "title": (by_id[r.doc_id].title[:160] if r.doc_id in by_id else ""),
        }
        for r in neg_runs
    ]
    _write_json(
        out / "negative_verification.json",
        {
            "generated_by": "scripts/eval/routing_dataset_counterfactual.py (PLAN-0111 C-3b)",
            "label": "yielded = (n_relations + n_claims + n_events) >= 1",
            **neg_analysis,
            "old_vs_new_labels": neg_label_records,
        },
    )

    # Example LIGHT titles by class for the report.
    light_by_id = {s.doc_id: s for s in (LightSample(**s) for s in _load_json(out / "light_sample.json"))}
    light_pos = [r for r in light_runs if not r.degraded and r.yielded]
    light_neg = [r for r in light_runs if not r.degraded and not r.yielded]
    light_examples = {
        "yield_examples": [light_by_id[r.doc_id].title[:120] for r in light_pos[:5] if r.doc_id in light_by_id],
        "no_yield_examples": [light_by_id[r.doc_id].title[:120] for r in light_neg[:5] if r.doc_id in light_by_id],
    }

    manifest = {
        "generated_by": "scripts/eval/routing_dataset_counterfactual.py (PLAN-0111 C-3b)",
        "model": _PROD_MODEL,
        "actual_spend": {
            "actual_usd": tally["actual_usd"],
            "total_tokens_in": tally["total_tokens_in"],
            "total_tokens_out": tally["total_tokens_out"],
            "estimate_usd_from_c3_report": 0.36,
            "aborted_on_budget": tally.get("aborted_on_budget", False),
        },
        "light_counterfactual": {**light_analysis, **light_examples},
        "negative_verification": neg_analysis,
    }
    _write_json(out / "run_manifest.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def cmd_augment(args: argparse.Namespace) -> None:
    """Append the 400 newly-labeled LIGHT rows to a copy of the base dataset CSV.

    Writes ``routing_dataset_augmented.csv`` (gitignored) = base 14,742 rows + the
    LIGHT rows, in the EXACT DatasetRow schema. The negatives are NOT touched here —
    their verification lives in negative_verification.json (old vs new label).
    """
    out = _out_dir(args.out)
    base_csv = Path(args.base_csv)
    light_samples = {s["doc_id"]: s for s in _load_json(out / "light_sample.json")}
    light_runs = [DocRun(**r) for r in _load_json(out / "light_runs.json")]

    # Build the augmented LIGHT rows in the DatasetRow schema (degraded excluded).
    fieldnames = [f.name for f in rcd.DatasetRow.__dataclass_fields__.values()]
    light_rows: list[dict[str, Any]] = []
    for r in light_runs:
        if r.degraded or r.doc_id not in light_samples:
            continue
        s = light_samples[r.doc_id]
        light_rows.append(
            asdict(
                rcd.DatasetRow(
                    doc_id=r.doc_id,
                    title=s["title"],
                    subtitle=s["subtitle"],
                    entity_density=s["entity_density"],
                    source_reliability=s["source_reliability"],
                    recency=s["recency"],
                    document_type=s["document_type"],
                    extraction_yield=s["extraction_yield"],
                    routed_tier=s["routed_tier"],  # 'light'
                    n_relations=r.n_relations,
                    n_claims=r.n_claims,
                    n_events=r.n_events,
                    yielded=r.yielded,
                    degraded=False,
                )
            )
        )

    # Always write the standalone LIGHT-rows CSV (small; can be committed if desired).
    light_csv = out / "augmented_light_rows.csv"
    with light_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(light_rows)
    print(f"Wrote {len(light_rows)} LIGHT rows → {light_csv}")

    # If the base dataset CSV exists, emit the full augmented CSV (gitignored).
    if base_csv.exists():
        aug_csv = base_csv.parent / "routing_dataset_augmented.csv"
        base_n = 0
        with (
            base_csv.open("r", encoding="utf-8", newline="") as bf,
            aug_csv.open("w", encoding="utf-8", newline="") as af,
        ):
            reader = csv.DictReader(bf)
            writer = csv.DictWriter(af, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                base_n += 1
            writer.writerows(light_rows)
        print(f"Augmented dataset: {base_n} base + {len(light_rows)} LIGHT = {base_n + len(light_rows)} → {aug_csv}")
    else:
        print(f"(base CSV {base_csv} not found — wrote LIGHT rows only; run routing_classifier_dataset.py build first)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    default_out = "results/routing_dataset/counterfactual"

    ps = sub.add_parser("select-samples", help="seeded LIGHT + negative sample selection (READ-ONLY)")
    ps.add_argument("--out", default=default_out)
    ps.add_argument("--n-light", type=int, default=_DEFAULT_N_LIGHT)
    ps.add_argument("--n-neg", type=int, default=_DEFAULT_N_NEG)
    ps.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    ps.set_defaults(func=cmd_select_samples)

    pe = sub.add_parser("extract", help="faithful extraction of the 600 sampled docs (HARD-CAPPED)")
    pe.add_argument("--out", default=default_out)
    pe.add_argument("--max-retries", type=int, default=_DEFAULT_MAX_RETRIES)
    pe.add_argument("--abort-usd", type=float, default=_DEFAULT_ABORT_USD)
    pe.add_argument("--limit", type=int, default=None, help="cap each sample (smoke test only)")
    pe.set_defaults(func=cmd_extract)

    pa = sub.add_parser("analyze", help="LIGHT positive rate + negative FN rate + CIs")
    pa.add_argument("--out", default=default_out)
    pa.set_defaults(func=cmd_analyze)

    pg = sub.add_parser("augment", help="append the 400 LIGHT rows to the dataset CSV")
    pg.add_argument("--out", default=default_out)
    pg.add_argument("--base-csv", default="results/routing_dataset/routing_dataset.csv")
    pg.set_defaults(func=cmd_augment)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
