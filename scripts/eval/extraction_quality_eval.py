#!/usr/bin/env python3
"""Offline LLM-as-judge extraction-quality A/B harness.

PURPOSE
-------
Decide whether a faster/cheaper DeepInfra model (e.g. ``deepseek-ai/DeepSeek-V4-Flash``
or ``Qwen/Qwen3.6-35B-A3B``) matches the current production extraction model
``Qwen/Qwen3-235B-A22B-Instruct-2507`` on **extraction quality** BEFORE we swap it
in. Extraction drives the KG (events / claims / relations), so a wrong swap
silently degrades the graph. This harness screens candidates with an independent
LLM judge — no human labelling required for a verdict (a human spot-check sheet
is emitted as an optional secondary signal).

This is a STANDALONE tool. It does not import, mutate, or wire into the live
pipeline, the adapter, ``config.py``, or any model env var. It only:
  * READS nlp_db + content_store_db to assemble a frozen golden input set, and
  * makes its own OpenAI-compatible / Anthropic HTTP calls.

PIPELINE
--------
  1. assemble  — pull ~N DEEP-tier articles from the live DBs, capture the EXACT
                 extraction inputs the pipeline would build (entity allow-list +
                 doc text), freeze them to ``golden_set.json``.
  2. run       — run each candidate model through the SAME prompt + decode params
                 the production adapter uses (temperature=0, json_object,
                 reasoning_effort=none), capturing raw JSON output + latency.
  3. judge     — score every (article, model_output) with an INDEPENDENT strong
                 judge model on a precision / recall / adherence rubric. The judge
                 is NEVER the model being judged (self-preference guard).
  4. report    — aggregate into a markdown comparison table + ranked verdict, plus
                 a human spot-check CSV.

Each stage persists its output, so stages can be re-run independently and cheaply.

USAGE
-----
  # 1. Freeze the golden set (reads the DBs; needs NLP_DB_URL + CONTENT_STORE_DB_URL)
  NLP_DB_URL=postgresql://... CONTENT_STORE_DB_URL=postgresql://... \
      python scripts/eval/extraction_quality_eval.py assemble --sample-size 100 \
      --out results/extraction_eval

  # 2. Run candidate models against the frozen inputs (needs DEEPINFRA_API_KEY)
  DEEPINFRA_API_KEY=... python scripts/eval/extraction_quality_eval.py run \
      --out results/extraction_eval \
      --models "Qwen/Qwen3-235B-A22B-Instruct-2507,deepseek-ai/DeepSeek-V4-Flash"

  # 3. Judge every output (judge picked automatically; see --judge-model)
  ANTHROPIC_API_KEY=... python scripts/eval/extraction_quality_eval.py judge \
      --out results/extraction_eval

  # 4. Build the report + verdict
  python scripts/eval/extraction_quality_eval.py report --out results/extraction_eval

  # Convenience: estimate token cost without spending anything
  python scripts/eval/extraction_quality_eval.py estimate-cost --out results/extraction_eval \
      --models "Qwen/Qwen3-235B-A22B-Instruct-2507,deepseek-ai/DeepSeek-V4-Flash"

  # Convenience: a tiny end-to-end smoke run on the first 3 frozen articles
  DEEPINFRA_API_KEY=... python scripts/eval/extraction_quality_eval.py dry-run \
      --out results/extraction_eval --models "..."

See scripts/eval/README.md for the full design write-up and methodology notes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# ── Constants mirroring the production extraction path ───────────────────────
# These MUST match libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py
# and services/nlp-pipeline/config.py so that what we measure is what production
# would actually do. If the adapter changes, update these (and say so in the report).
_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
_PROD_EXTRACTION_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # the 235B baseline
# adapter uses max_tokens=4096; overridable for eval-only experiments (e.g. testing
# whether a reasoning model truncates its JSON when reasoning_content eats the budget).
# This is the EVAL harness only — it does NOT change the production adapter.
_EXTRACTION_MAX_TOKENS = int(os.environ.get("EVAL_EXTRACTION_MAX_TOKENS", "4096"))
_EXTRACTION_TEMPERATURE = 0.0  # adapter uses temperature=0
_EXTRACTION_TIMEOUT_S = 180.0  # generous; adapter caps at 150s in prod
_SINGLE_WINDOW_TOKEN_LIMIT = 24_000  # deep_extraction.py: ≤24k tokens → single window

# reasoning_effort for the EXTRACTION calls (not the judge — the judge is always
# "none"). Production currently runs the adapter at "low" (raised 2026-06-15 for
# relation-extraction recall). For the A/B we keep it identical across all three
# models so the comparison is apples-to-apples; override per run via
# EVAL_EXTRACTION_REASONING_EFFORT or --reasoning-effort. NOTE: gpt-oss-120b is a
# reasoning model that ONLY emits answer text in `content` when reasoning_effort is
# explicitly set (verified: default leaves content="" with finish_reason=length),
# so this knob is load-bearing for that candidate.
_EXTRACTION_REASONING_EFFORT = os.environ.get("EVAL_EXTRACTION_REASONING_EFFORT", "none")

# ── Judge configuration ──────────────────────────────────────────────────────
# The judge MUST be independent of the candidate being judged (self-preference
# bias). Default judge = Anthropic Claude Opus 4.8 when ANTHROPIC_API_KEY is set
# (a different model family from every DeepInfra candidate — the cleanest
# independence guarantee). Otherwise fall back to the 235B on DeepInfra, which is
# still independent of every NON-235B candidate; the harness refuses to let the
# judge grade its own output (see _resolve_judge_for_model).
_ANTHROPIC_JUDGE_MODEL = "claude-opus-4-8"
_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/messages"
_DEEPINFRA_FALLBACK_JUDGE = _PROD_EXTRACTION_MODEL  # strong, independent of candidates

# Controlled vocabularies copied from deep_extraction.py so the judge can verify
# schema adherence deterministically (the prompt also lists them, but having them
# here lets us cross-check counts in code without a second model call).
_VALID_EVENT_TYPES = {
    "EARNINGS_RELEASE",
    "M_AND_A",
    "REGULATORY_ACTION",
    "MACRO",
    "MANAGEMENT_CHANGE",
    "PRODUCT_LAUNCH",
    "CAPITAL_RAISE",
    "LEGAL",
    "ANALYST_RATING",
    "GUIDANCE_RAISE",
    "NATURAL_DISASTER",
    "GEOPOLITICAL",
    "SANCTIONS",
    "OTHER",
}
_VALID_PREDICATES = {
    "acquired_by",
    "analyst_rating",
    "appointed_as",
    "board_member_of",
    "competes_with",
    "corporate_action",
    "credit_rating",
    "divested_from",
    "downgraded_by",
    "earnings_guidance",
    "earnings_released",
    "employs",
    "filed_lawsuit_against",
    "has_executive",
    "headquartered_in",
    "investment_in",
    "is_in_industry",
    "is_in_sector",
    "issues_debt",
    "listed_on",
    "market_share_claim",
    "operates_in_country",
    "owns_stake_in",
    "partner_of",
    "price_target",
    "produces",
    "regulates",
    "reported_revenue_of",
    "revenue_from_country",
    "sentiment_signal",
    "subsidiary_of",
    "supplier_of",
}


# ── Golden-set data model ─────────────────────────────────────────────────────


@dataclass
class GoldenArticle:
    """One frozen extraction input — exactly what the pipeline would feed the LLM.

    ``entities`` and ``text`` are the literal {entities} / {text} prompt fills,
    reconstructed the same way deep_extraction.py does:
      * entities = order-preserving de-dup of entity_mentions.mention_text for the doc
      * text     = chunks.chunk_text joined in chunk_index order (the window text)
    Persisting these means every candidate model runs on byte-identical inputs.
    """

    doc_id: str
    title: str | None
    source_name: str | None
    published_at: str | None
    routing_tier: str | None
    span_bucket: str  # heuristic category for coverage reporting (earnings / m&a / thin / …)
    word_count: int
    entity_count: int
    entities: str  # the {entities} prompt fill (comma-joined allow-list)
    text: str  # the {text} prompt fill (the extraction window)


# ── Stage 1: assemble the golden set ─────────────────────────────────────────


def _normalize_sync_url(url: str) -> str:
    """Strip SQLAlchemy async-driver suffixes so sync psycopg accepts the URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _db_url(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return _normalize_sync_url(v)
    return None


def _classify_span(title: str | None, text: str, word_count: int) -> str:
    """Cheap keyword/length bucketing for coverage variety in the report.

    Not used for scoring — only to confirm the golden set spans earnings, M&A,
    management changes, macro, and thin articles (so we test that good models
    correctly return little on low-content docs).
    """
    if word_count < 120:
        return "thin"
    hay = f"{title or ''} {text[:1500]}".lower()
    if any(k in hay for k in ("acquire", "merger", "takeover", "buyout", "acquisition")):
        return "m_and_a"
    if any(k in hay for k in ("earnings", "quarterly", "revenue", "eps", "guidance", "profit")):
        return "earnings"
    if any(k in hay for k in ("ceo", "cfo", "appointed", "resign", "steps down", "named")):
        return "management"
    if any(k in hay for k in ("inflation", "fed", "rate", "gdp", "tariff", "sanction", "central bank")):
        return "macro"
    return "general"


_ASSEMBLE_SQL = """
WITH deep_docs AS (
    -- Pick docs that were routed DEEP (final tier wins if present), most
    -- recent first. processing_path full_pipeline == the deep-extraction path.
    SELECT DISTINCT ON (rd.doc_id)
           rd.doc_id,
           COALESCE(rd.final_routing_tier, rd.routing_tier) AS tier,
           rd.processing_path,
           rd.decided_at
    FROM routing_decisions rd
    -- Tier labels are stored lowercase ('deep') in nlp_db; compare case-insensitively
    -- so the filter is robust to either casing (live DB uses lowercase).
    WHERE lower(COALESCE(rd.final_routing_tier, rd.routing_tier)) = 'deep'
    ORDER BY rd.doc_id, rd.decided_at DESC
)
SELECT dd.doc_id, dd.tier
FROM deep_docs dd
ORDER BY dd.decided_at DESC
LIMIT %(limit)s;
"""

# Reconstruct the extraction window text from chunks (the same text the pipeline
# split into windows), plus the entity allow-list from entity_mentions. We pull a
# generous pool then balance across span buckets in Python.
_DOC_TEXT_SQL = """
SELECT string_agg(c.chunk_text, ' ' ORDER BY c.chunk_index) AS doc_text
FROM chunks c
WHERE c.doc_id = %(doc_id)s AND c.chunk_text IS NOT NULL;
"""

_DOC_MENTIONS_SQL = """
SELECT em.mention_text
FROM entity_mentions em
WHERE em.doc_id = %(doc_id)s
ORDER BY em.char_start, em.mention_id;
"""

_DOC_META_SQL = """
SELECT title, source_name, published_at, word_count
FROM document_source_metadata
WHERE doc_id = %(doc_id)s;
"""


def assemble_golden_set(sample_size: int, pool_multiplier: int = 4) -> list[GoldenArticle]:
    """Read the live DBs and freeze ~``sample_size`` DEEP-tier extraction inputs.

    Mirrors deep_extraction.py exactly: entities = order-preserving de-dup of
    mention_text; text = chunk_text joined by chunk_index. We pull a pool of
    ``sample_size * pool_multiplier`` candidates and balance across span buckets
    so the golden set has earnings / M&A / management / macro / thin variety.
    """
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        sys.exit("psycopg not installed — run: pip install psycopg")

    nlp_url = _db_url("NLP_DB_URL_TEST", "NLP_DB_URL")
    if not nlp_url:
        sys.exit("NLP_DB_URL (or NLP_DB_URL_TEST) must be set to assemble the golden set.")

    pool: list[GoldenArticle] = []
    with psycopg.connect(nlp_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(_ASSEMBLE_SQL, {"limit": sample_size * pool_multiplier})
            doc_rows = cur.fetchall()
        if not doc_rows:
            sys.exit("No DEEP-tier documents found in routing_decisions. " "Is this pointed at a populated nlp_db?")

        for doc_id, tier in doc_rows:
            doc_id_s = str(doc_id)
            with conn.cursor() as cur:
                cur.execute(_DOC_TEXT_SQL, {"doc_id": doc_id})
                row = cur.fetchone()
            doc_text = (row[0] if row else None) or ""
            if not doc_text.strip():
                continue  # text not reconstructable from chunks → skip
            # Truncate to the single-window budget the pipeline uses for ≤24k docs.
            # (We evaluate the first window; multi-window docs are rare and the
            # first window is the representative extraction unit.)
            words = doc_text.split()
            window_truncated = len(words) > _SINGLE_WINDOW_TOKEN_LIMIT
            if window_truncated:
                doc_text = " ".join(words[:_SINGLE_WINDOW_TOKEN_LIMIT])

            with conn.cursor() as cur:
                cur.execute(_DOC_MENTIONS_SQL, {"doc_id": doc_id})
                mention_rows = cur.fetchall()
            # order-preserving de-dup, exactly like deep_extraction.py
            mention_names = list(dict.fromkeys(r[0] for r in mention_rows if r[0]))
            entities_str = ", ".join(mention_names) if mention_names else "none identified"

            with conn.cursor() as cur:
                cur.execute(_DOC_META_SQL, {"doc_id": doc_id})
                meta = cur.fetchone()
            title = meta[0] if meta else None
            source_name = meta[1] if meta else None
            published_at = meta[2].isoformat() if meta and meta[2] else None
            word_count = meta[3] if meta and meta[3] else len(doc_text.split())

            pool.append(
                GoldenArticle(
                    doc_id=doc_id_s,
                    title=title,
                    source_name=source_name,
                    published_at=published_at,
                    routing_tier=str(tier),
                    span_bucket=_classify_span(title, doc_text, word_count),
                    word_count=int(word_count),
                    entity_count=len(mention_names),
                    entities=entities_str,
                    text=doc_text,
                )
            )

    return _balance_by_bucket(pool, sample_size)


def _balance_by_bucket(pool: list[GoldenArticle], sample_size: int) -> list[GoldenArticle]:
    """Round-robin across span buckets so no single bucket dominates the sample."""
    by_bucket: dict[str, list[GoldenArticle]] = {}
    for art in pool:
        by_bucket.setdefault(art.span_bucket, []).append(art)
    selected: list[GoldenArticle] = []
    buckets = sorted(by_bucket.keys())
    idx = {b: 0 for b in buckets}
    while len(selected) < sample_size and any(idx[b] < len(by_bucket[b]) for b in buckets):
        for b in buckets:
            if idx[b] < len(by_bucket[b]):
                selected.append(by_bucket[b][idx[b]])
                idx[b] += 1
                if len(selected) >= sample_size:
                    break
    return selected


# ── Prompt construction (mirrors deep_extraction._build_prompt) ──────────────


def _render_extraction_prompt(entities: str, text: str) -> str:
    """Render the DEEP_EXTRACTION template exactly as the pipeline does.

    Imports the real template from libs/prompts so we never drift from
    production. Falls back to a sys.path shim if the lib isn't importable.
    """
    from prompts.extraction.deep import DEEP_EXTRACTION  # type: ignore[import-untyped]

    return DEEP_EXTRACTION.render(entities=entities, text=text)


def _ensure_prompts_importable() -> None:
    """Add libs/prompts to sys.path so the real DEEP_EXTRACTION template imports."""
    try:
        import prompts.extraction.deep  # noqa: F401  type: ignore[import-untyped]

        return
    except ImportError:
        repo_root = Path(__file__).resolve().parents[2]
        lib_src = repo_root / "libs" / "prompts" / "src"
        if lib_src.is_dir():
            sys.path.insert(0, str(lib_src))


# ── Stage 2: run candidate models ────────────────────────────────────────────


@dataclass
class ModelRunResult:
    """Raw output + telemetry for one (model, article) extraction call."""

    doc_id: str
    model_id: str
    status: str  # "ok" | "json_error" | "api_error"
    latency_s: float
    tokens_in: int
    tokens_out: int
    raw_response: str
    parsed: dict[str, Any] | None
    error: str | None
    # convenience counts (None if unparseable)
    n_events: int | None = None
    n_claims: int | None = None
    n_relations: int | None = None


def _deepinfra_chat(
    client: httpx.Client,
    api_key: str,
    base_url: str,
    model_id: str,
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int,
    force_json: bool,
    reasoning_effort: str = "none",
) -> tuple[str, int, int]:
    """One OpenAI-compatible chat completion. Returns (content, tokens_in, tokens_out).

    Mirrors the production adapter's decode params: temperature=0,
    response_format=json_object. ``reasoning_effort`` is parameterised: extraction
    calls pass the A/B-wide value (default "none"); the judge always passes "none".
    ``force_json`` lets the judge call opt out of strict json_object if a model
    rejects it.
    """
    body: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": _EXTRACTION_TEMPERATURE,
        "max_tokens": max_tokens,
        # reasoning_effort controls Qwen3.x / gpt-oss chain-of-thought. With "none"
        # the answer lands in `content` (same as a non-reasoning model); for reasoning
        # models it must be set so `content` is non-empty (see module note).
        "reasoning_effort": reasoning_effort,
    }
    if force_json:
        body["response_format"] = {"type": "json_object"}

    # Retry on transient DeepInfra 429 `engine_overloaded` / 5xx with exponential
    # backoff. The 235B baseline is served on a small/oversubscribed pool and bursts
    # `engine_overloaded` under any load (verified during smoke testing) — without
    # this retry the baseline would be scored as all-`api_error` and the A/B would be
    # invalid. Backoff: 5s, 15s, 30s, 45s, 60s (caps total added wait ~2.5min/call).
    backoffs = [5.0, 15.0, 30.0, 45.0, 60.0]
    last_exc: Exception | None = None
    for attempt in range(len(backoffs) + 1):
        resp = client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            last_exc = httpx.HTTPStatusError(
                f"transient {resp.status_code}: {resp.text[:200]}", request=resp.request, response=resp
            )
            if attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                continue
            raise last_exc
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        return content, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
    # Unreachable (loop either returns or raises), but satisfies the type checker.
    raise last_exc if last_exc else RuntimeError("retry loop exited unexpectedly")


def _strip_json_fences(raw: str) -> str:
    """Defense-in-depth: strip ```json fences before parsing (adapter does this too)."""
    return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())


def _parse_arm(spec: str) -> tuple[str, str, str]:
    """Parse a model-arm spec ``physical_model[@reasoning_effort]``.

    Returns ``(physical_model, reasoning_effort, arm_id)``. The arm_id is the
    spec verbatim (e.g. ``Qwen/Qwen3-235B-A22B-Instruct-2507@low``) so the SAME
    physical model run at two different reasoning settings appears as two DISTINCT
    arms in every downstream artefact (runs, scores, aggregate, report). When no
    ``@effort`` suffix is given, the module-default ``_EXTRACTION_REASONING_EFFORT``
    is used and the arm_id is just the model id. NOTE: model slugs contain no '@',
    so splitting on the last '@' is unambiguous.
    """
    spec = spec.strip()
    if "@" in spec:
        physical, effort = spec.rsplit("@", 1)
        return physical.strip(), effort.strip(), spec
    return spec, _EXTRACTION_REASONING_EFFORT, spec


def run_model_on_article(
    client: httpx.Client,
    api_key: str,
    base_url: str,
    model_id: str,
    article: GoldenArticle,
) -> ModelRunResult:
    """Run one candidate model-arm on one frozen article; capture output + latency.

    ``model_id`` is an ARM SPEC (``physical_model[@reasoning_effort]``). The result's
    ``model_id`` is set to the arm spec so arms remain distinct downstream, while the
    HTTP call uses the physical model + that arm's reasoning_effort.
    """
    _ensure_prompts_importable()
    physical_model, reasoning_effort, arm_id = _parse_arm(model_id)
    prompt = _render_extraction_prompt(article.entities, article.text)
    t0 = time.perf_counter()
    try:
        content, tin, tout = _deepinfra_chat(
            client,
            api_key,
            base_url,
            physical_model,
            system_prompt=prompt,
            user_content=article.text,
            max_tokens=_EXTRACTION_MAX_TOKENS,
            force_json=True,
            reasoning_effort=reasoning_effort,
        )
    except Exception as exc:  # any HTTP/timeout error → record, don't crash the run
        return ModelRunResult(
            doc_id=article.doc_id,
            model_id=model_id,
            status="api_error",
            latency_s=round(time.perf_counter() - t0, 3),
            tokens_in=0,
            tokens_out=0,
            raw_response="",
            parsed=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    latency = round(time.perf_counter() - t0, 3)

    parsed: dict[str, Any] | None = None
    status = "ok"
    err: str | None = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(_strip_json_fences(content))
        except json.JSONDecodeError as exc:
            status = "json_error"
            err = f"JSONDecodeError: {exc}"
    if parsed is not None and not isinstance(parsed, dict):
        status, parsed, err = "json_error", None, "top-level JSON is not an object"

    n_e = n_c = n_r = None
    if parsed is not None:
        n_e = len(parsed.get("events") or [])
        n_c = len(parsed.get("claims") or [])
        n_r = len(parsed.get("relations") or [])

    return ModelRunResult(
        doc_id=article.doc_id,
        model_id=model_id,
        status=status,
        latency_s=latency,
        tokens_in=tin,
        tokens_out=tout,
        raw_response=content,
        parsed=parsed,
        error=err,
        n_events=n_e,
        n_claims=n_c,
        n_relations=n_r,
    )


# ── Stage 3: the LLM judge ────────────────────────────────────────────────────

# The judge prompt is the measurement instrument — its neutrality determines the
# validity of the whole result. It is deliberately:
#   * length-agnostic: rewards CORRECT coverage, penalises BOTH fabrication and
#     misses, so it favours neither verbose nor terse extraction.
#   * grounded: every judgement must cite the text; "supported" means a verbatim
#     phrase exists. Empty output on a thin article is explicitly the RIGHT answer.
#   * structured: 1-5 per dimension + counts + a short justification, returned as
#     strict JSON so aggregation is mechanical.
_JUDGE_SYSTEM_PROMPT = """\
You are a meticulous financial-NLP annotation reviewer. You are grading the output
of an automated extraction system that reads a news article and emits structured
JSON: events (typed), claims (typed, with polarity), and relations (with a
controlled predicate). You are NOT the system being graded — judge its output
strictly and impartially against the article.

You will receive:
  1. ARTICLE TEXT — the source passage.
  2. ENTITY ALLOW-LIST — the ONLY entity strings the system was permitted to use
     for entity_ref / subject_ref / object_ref. Anything outside this list is a
     constraint violation.
  3. EXTRACTION JSON — the system's output to grade.

Grade on THREE dimensions, each an integer 1-5 (5 = best):

A) PRECISION (correctness / no fabrication):
   Is every extracted event/claim/relation actually supported by a verbatim phrase
   in the article? Penalise hallucinated facts, invented numbers, dates not present
   in the text, and relationships the text does not assert. 5 = everything is
   faithful; 1 = mostly fabricated.

B) RECALL (coverage):
   Did it capture the events/claims/relations a careful analyst would extract from
   THIS article? Penalise obvious misses. IMPORTANT: a thin / low-content article
   genuinely contains little — correctly returning empty or near-empty arrays on
   such an article is a 5, NOT a miss. Do not reward padding. Judge against what
   the article actually supports, not against a fixed quota.

C) ADHERENCE (schema / constraint compliance):
   - Every entity_ref/subject_ref/object_ref is an EXACT string from the allow-list.
   - Dates (valid_from/valid_to) are ISO-8601 copied verbatim from the text (or null).
   - Predicates and event_types are from the controlled vocabularies.
   - person<->company direction is correct (company is subject, person is object for
     employs / has_executive / appointed_as).
   5 = fully compliant; 1 = pervasive violations.

NEUTRALITY RULES (read carefully):
  * Do NOT reward longer output. More items is only better if those items are
    correct AND supported. A short, fully-correct extraction outscores a long one
    padded with weak or fabricated items.
  * Do NOT reward shorter output either. Missing clearly-stated facts lowers RECALL.
  * Reward CALIBRATION: the right amount of extraction for the article's content.

Also report counts you observe: fabricated_items (items with no textual support),
allowlist_violations (refs not in the allow-list), missed_items (clear facts the
system failed to extract).

Return ONLY a JSON object, no prose around it:
{
  "precision": <1-5>,
  "recall": <1-5>,
  "adherence": <1-5>,
  "fabricated_items": <int>,
  "allowlist_violations": <int>,
  "missed_items": <int>,
  "justification": "<two or three sentences citing specifics>"
}"""


def _build_judge_user_message(article: GoldenArticle, extraction_json: str) -> str:
    """Assemble the judge's user turn from the article, allow-list, and output."""
    # Trim the article for the judge to keep judge cost bounded; the first ~6k words
    # carry the lede + body that the extraction was built from.
    text = article.text
    words = text.split()
    if len(words) > 6000:
        text = " ".join(words[:6000]) + " […truncated for judge…]"
    return (
        f"ARTICLE TEXT:\n{text}\n\n"
        f"ENTITY ALLOW-LIST (exact strings only):\n{article.entities}\n\n"
        f"EXTRACTION JSON TO GRADE:\n{extraction_json}\n"
    )


@dataclass
class JudgeScore:
    doc_id: str
    candidate_model: str
    judge_model: str
    status: str  # "ok" | "judge_error" | "skipped_unparseable_output"
    precision: int | None = None
    recall: int | None = None
    adherence: int | None = None
    fabricated_items: int | None = None
    allowlist_violations: int | None = None
    missed_items: int | None = None
    justification: str | None = None
    error: str | None = None


def _call_anthropic_judge(client: httpx.Client, api_key: str, system_prompt: str, user_msg: str) -> str:
    """Call Claude (Opus 4.8) via raw HTTP. temperature=0 for reproducibility."""
    resp = client.post(
        _ANTHROPIC_BASE_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _ANTHROPIC_JUDGE_MODEL,
            "max_tokens": 1024,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_msg}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


def _resolve_judge_for_model(candidate_model: str, configured_judge: str, judge_kind: str) -> tuple[str, str]:
    """Pick an independent judge for a given candidate (self-preference guard).

    Returns (judge_kind, judge_model). If the configured judge IS the candidate
    (only possible for the DeepInfra-fallback judge grading the 235B baseline), we
    cannot use it without self-preference bias — the caller must supply an
    Anthropic key or a different DeepInfra judge. We surface that as an error
    rather than silently grade-self.
    """
    if judge_kind == "anthropic":
        return "anthropic", _ANTHROPIC_JUDGE_MODEL  # always independent of DeepInfra candidates
    # DeepInfra fallback judge: independence requires judge != candidate
    if configured_judge == candidate_model:
        return "self_conflict", configured_judge
    return "deepinfra", configured_judge


def judge_extraction(
    anthropic_client: httpx.Client | None,
    anthropic_key: str | None,
    deepinfra_client: httpx.Client | None,
    deepinfra_key: str | None,
    deepinfra_judge_model: str,
    article: GoldenArticle,
    run: ModelRunResult,
) -> JudgeScore:
    """Score one (article, model output) with an independent judge."""
    # An unparseable model output is a deterministic quality failure — no judge
    # call needed; record it so it lowers the model's aggregate without spend.
    if run.parsed is None:
        return JudgeScore(
            doc_id=article.doc_id,
            candidate_model=run.model_id,
            judge_model="(none)",
            status="skipped_unparseable_output",
            precision=1,
            recall=1,
            adherence=1,
            fabricated_items=0,
            allowlist_violations=0,
            missed_items=0,
            justification="Model produced unparseable / non-JSON output — scored as floor.",
        )

    judge_kind = "anthropic" if (anthropic_client and anthropic_key) else "deepinfra"
    resolved_kind, judge_model = _resolve_judge_for_model(run.model_id, deepinfra_judge_model, judge_kind)
    if resolved_kind == "self_conflict":
        return JudgeScore(
            doc_id=article.doc_id,
            candidate_model=run.model_id,
            judge_model=judge_model,
            status="judge_error",
            error=(
                f"Judge model {judge_model} == candidate {run.model_id}: cannot self-grade. "
                "Set ANTHROPIC_API_KEY or pass a different --judge-model."
            ),
        )

    user_msg = _build_judge_user_message(article, json.dumps(run.parsed, ensure_ascii=False))
    try:
        if resolved_kind == "anthropic":
            assert anthropic_client and anthropic_key
            content = _call_anthropic_judge(anthropic_client, anthropic_key, _JUDGE_SYSTEM_PROMPT, user_msg)
        else:
            assert deepinfra_client and deepinfra_key
            content, _, _ = _deepinfra_chat(
                deepinfra_client,
                deepinfra_key,
                _DEEPINFRA_BASE_URL,
                judge_model,
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                user_content=user_msg,
                max_tokens=1024,
                force_json=True,
            )
        verdict = json.loads(_strip_json_fences(content))
    except Exception as exc:
        return JudgeScore(
            doc_id=article.doc_id,
            candidate_model=run.model_id,
            judge_model=judge_model,
            status="judge_error",
            error=f"{type(exc).__name__}: {exc}",
        )

    def _clamp(v: Any) -> int | None:
        try:
            return max(1, min(5, int(v)))
        except (TypeError, ValueError):
            return None

    return JudgeScore(
        doc_id=article.doc_id,
        candidate_model=run.model_id,
        judge_model=judge_model,
        status="ok",
        precision=_clamp(verdict.get("precision")),
        recall=_clamp(verdict.get("recall")),
        adherence=_clamp(verdict.get("adherence")),
        fabricated_items=_int_or_none(verdict.get("fabricated_items")),
        allowlist_violations=_int_or_none(verdict.get("allowlist_violations")),
        missed_items=_int_or_none(verdict.get("missed_items")),
        justification=str(verdict.get("justification", ""))[:1000],
    )


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── Stage 4: aggregation + report ─────────────────────────────────────────────


@dataclass
class ModelAggregate:
    model_id: str
    n_articles: int
    mean_precision: float | None
    mean_recall: float | None
    mean_adherence: float | None
    mean_overall: float | None  # equal-weighted mean of the three dimensions
    fabrication_rate: float  # fabricated_items per article
    allowlist_violation_rate: float
    json_parse_failure_rate: float
    api_error_rate: float
    mean_events: float
    mean_claims: float
    mean_relations: float
    p50_latency_s: float | None
    p95_latency_s: float | None
    total_tokens_in: int
    total_tokens_out: int


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 3) if xs else None


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 3)


def aggregate(runs: list[ModelRunResult], scores: list[JudgeScore], model_ids: list[str]) -> list[ModelAggregate]:
    """Roll up per-model means, rates, counts, and latency percentiles."""
    runs_by_model: dict[str, list[ModelRunResult]] = {m: [] for m in model_ids}
    for r in runs:
        runs_by_model.setdefault(r.model_id, []).append(r)
    scores_by_model: dict[str, list[JudgeScore]] = {m: [] for m in model_ids}
    for s in scores:
        scores_by_model.setdefault(s.candidate_model, []).append(s)

    aggs: list[ModelAggregate] = []
    for m in model_ids:
        mruns = runs_by_model.get(m, [])
        mscores = [s for s in scores_by_model.get(m, []) if s.status in ("ok", "skipped_unparseable_output")]
        n = len(mruns)
        prec = [s.precision for s in mscores if s.precision is not None]
        rec = [s.recall for s in mscores if s.recall is not None]
        adh = [s.adherence for s in mscores if s.adherence is not None]
        overall = [
            statistics.mean([s.precision, s.recall, s.adherence])
            for s in mscores
            if None not in (s.precision, s.recall, s.adherence)
        ]
        fabricated = sum(s.fabricated_items or 0 for s in mscores)
        violations = sum(s.allowlist_violations or 0 for s in mscores)
        json_errs = sum(1 for r in mruns if r.status == "json_error")
        api_errs = sum(1 for r in mruns if r.status == "api_error")
        ok_runs = [r for r in mruns if r.status == "ok"]
        latencies = [r.latency_s for r in mruns if r.status != "api_error"]

        aggs.append(
            ModelAggregate(
                model_id=m,
                n_articles=n,
                mean_precision=_mean([float(x) for x in prec]),
                mean_recall=_mean([float(x) for x in rec]),
                mean_adherence=_mean([float(x) for x in adh]),
                mean_overall=_mean(overall),
                fabrication_rate=round(fabricated / n, 3) if n else 0.0,
                allowlist_violation_rate=round(violations / n, 3) if n else 0.0,
                json_parse_failure_rate=round(json_errs / n, 3) if n else 0.0,
                api_error_rate=round(api_errs / n, 3) if n else 0.0,
                mean_events=round(statistics.mean([r.n_events or 0 for r in ok_runs]), 2) if ok_runs else 0.0,
                mean_claims=round(statistics.mean([r.n_claims or 0 for r in ok_runs]), 2) if ok_runs else 0.0,
                mean_relations=round(statistics.mean([r.n_relations or 0 for r in ok_runs]), 2) if ok_runs else 0.0,
                p50_latency_s=_pct(latencies, 50),
                p95_latency_s=_pct(latencies, 95),
                total_tokens_in=sum(r.tokens_in for r in mruns),
                total_tokens_out=sum(r.tokens_out for r in mruns),
            )
        )
    return aggs


def build_report_md(aggs: list[ModelAggregate], baseline: str) -> str:
    """Render the comparison table + ranked verdict as markdown."""
    ranked = sorted(aggs, key=lambda a: (a.mean_overall if a.mean_overall is not None else -1.0), reverse=True)
    lines: list[str] = []
    lines.append("# Extraction-quality A/B — LLM-as-judge report\n")
    lines.append(f"Baseline (production): `{baseline}`\n")
    lines.append("## Comparison table\n")
    header = (
        "| Model | N | Prec | Recall | Adher | Overall | Fab/art | Allowlist viol/art "
        "| JSON-fail | API-err | ev | cl | rel | p50 s | p95 s |"
    )
    lines.append(header)
    lines.append("|" + "---|" * 15)
    for a in ranked:
        lines.append(
            f"| `{a.model_id}`{' ⭐base' if a.model_id == baseline else ''} | {a.n_articles} "
            f"| {a.mean_precision} | {a.mean_recall} | {a.mean_adherence} | **{a.mean_overall}** "
            f"| {a.fabrication_rate} | {a.allowlist_violation_rate} | {a.json_parse_failure_rate} "
            f"| {a.api_error_rate} | {a.mean_events} | {a.mean_claims} | {a.mean_relations} "
            f"| {a.p50_latency_s} | {a.p95_latency_s} |"
        )
    lines.append("\n## Ranked verdict\n")
    base_agg = next((a for a in aggs if a.model_id == baseline), None)
    base_overall = base_agg.mean_overall if base_agg else None
    for i, a in enumerate(ranked, 1):
        verdict = ""
        if base_overall is not None and a.mean_overall is not None and a.model_id != baseline:
            delta = round(a.mean_overall - base_overall, 3)
            if delta >= -0.10:
                verdict = f" — **MATCHES baseline** (Δoverall={delta:+}); " "viable swap if latency/cost favourable"
            else:
                verdict = f" — **BELOW baseline** (Δoverall={delta:+}); do NOT swap"
        elif a.model_id == baseline:
            verdict = " — production baseline"
        lines.append(f"{i}. `{a.model_id}` overall={a.mean_overall}{verdict}")
    lines.append(
        "\n> Methodology: scores are 1-5 per dimension from an INDEPENDENT judge "
        "(never the model being judged). 'MATCHES' uses a -0.10 overall tolerance "
        "(≈2% of the 5-point scale) — tighten for a production go/no-go. Pair the "
        "quality verdict with the latency/cost columns for the swap decision.\n"
    )
    return "\n".join(lines)


def build_human_spotcheck(
    articles: list[GoldenArticle], runs: list[ModelRunResult], model_ids: list[str], n: int = 20
) -> str:
    """Emit a markdown side-by-side sheet for an optional human spot-check.

    Human review is SECONDARY — the harness produces a verdict from the LLM judge
    alone. This sheet just lets a human sanity-check the top disagreements.
    """
    runs_idx: dict[tuple[str, str], ModelRunResult] = {(r.doc_id, r.model_id): r for r in runs}
    lines = ["# Human spot-check sheet (optional secondary signal)\n"]
    for art in articles[:n]:
        lines.append(f"## {art.doc_id} — {art.span_bucket} — {art.title or '(no title)'}")
        lines.append(f"**Allow-list:** {art.entities[:400]}")
        lines.append(f"**Text (excerpt):** {art.text[:600]}…\n")
        for m in model_ids:
            r = runs_idx.get((art.doc_id, m))
            if r is None:
                continue
            out = json.dumps(r.parsed, indent=2)[:1200] if r.parsed else f"({r.status}: {r.error})"
            lines.append(f"<details><summary>`{m}` (ev/cl/rel={r.n_events}/{r.n_claims}/{r.n_relations})</summary>\n")
            lines.append(f"```json\n{out}\n```\n</details>")
        lines.append("\n---\n")
    return "\n".join(lines)


# ── Cost estimation ───────────────────────────────────────────────────────────


def estimate_cost(articles: list[GoldenArticle], model_ids: list[str], with_judge: bool = True) -> str:
    """Estimate token volume + rough USD for a full run. Prints, returns the text.

    Token estimate uses word-count * 1.3 (a conservative subword multiplier).
    Pricing is the 235B's published DeepInfra rate ($0.071/$0.10 per 1M) as a
    representative figure; candidate rates vary — treat as an order-of-magnitude.
    """
    _ensure_prompts_importable()
    in_per_m, out_per_m = 0.071, 0.10  # representative DeepInfra $/1M (235B)
    # Per-article prompt = rendered template (~1.5k tokens of instructions) + text.
    # Output capped at 4096. Judge adds one input (~article+output) + ~300 out.
    total_in = total_out = 0
    judge_in = judge_out = 0
    for art in articles:
        prompt_tokens = int((len(art.text.split()) + 1500) * 1.3)
        out_tokens = _EXTRACTION_MAX_TOKENS  # worst case
        total_in += prompt_tokens * len(model_ids)
        total_out += out_tokens * len(model_ids)
        if with_judge:
            # judge sees article(≤6k words) + allow-list + extraction JSON, per model
            j_in = int((min(len(art.text.split()), 6000) + 500 + 1000) * 1.3)
            judge_in += j_in * len(model_ids)
            judge_out += 300 * len(model_ids)
    usd_extract = (total_in / 1e6) * in_per_m + (total_out / 1e6) * out_per_m
    usd_judge = (judge_in / 1e6) * in_per_m + (judge_out / 1e6) * out_per_m
    lines = [
        f"Cost estimate for {len(articles)} articles x {len(model_ids)} models:",
        f"  Extraction:  ~{total_in:,} in + ~{total_out:,} out tokens  ≈ ${usd_extract:.3f}",
    ]
    if with_judge:
        lines.append(
            f"  Judge:       ~{judge_in:,} in + ~{judge_out:,} out tokens  ≈ ${usd_judge:.3f} "
            "(DeepInfra judge; Anthropic Opus 4.8 judge ~70x this -- see README)"
        )
        lines.append(f"  TOTAL (DeepInfra judge): ≈ ${usd_extract + usd_judge:.3f}")
    lines.append("  NB: 'out' assumes the 4096-token cap on every call (worst case); real spend is lower.")
    text = "\n".join(lines)
    print(text)
    return text


# ── Persistence helpers ───────────────────────────────────────────────────────


def _out_dir(out: str) -> Path:
    p = Path(out)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_golden(out: Path) -> list[GoldenArticle]:
    raw = json.loads((out / "golden_set.json").read_text(encoding="utf-8"))
    return [GoldenArticle(**a) for a in raw]


def _load_runs(out: Path) -> list[ModelRunResult]:
    raw = json.loads((out / "model_runs.json").read_text(encoding="utf-8"))
    return [ModelRunResult(**r) for r in raw]


def _load_scores(out: Path) -> list[JudgeScore]:
    raw = json.loads((out / "judge_scores.json").read_text(encoding="utf-8"))
    return [JudgeScore(**s) for s in raw]


# ── CLI commands ──────────────────────────────────────────────────────────────


def cmd_assemble(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    arts = assemble_golden_set(args.sample_size)
    _write_json(out / "golden_set.json", [asdict(a) for a in arts])
    buckets: dict[str, int] = {}
    for a in arts:
        buckets[a.span_bucket] = buckets.get(a.span_bucket, 0) + 1
    print(f"Froze {len(arts)} DEEP-tier articles → {out / 'golden_set.json'}")
    print(f"Span coverage: {buckets}")


def _make_clients(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(connect=10.0, read=timeout, write=30.0, pool=10.0))


def _run_models(out: Path, model_ids: list[str], limit: int | None) -> list[ModelRunResult]:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        sys.exit("DEEPINFRA_API_KEY must be set to run candidate models.")
    base_url = os.environ.get("DEEPINFRA_BASE_URL", _DEEPINFRA_BASE_URL)
    articles = _load_golden(out)
    if limit:
        articles = articles[:limit]
    results: list[ModelRunResult] = []
    with _make_clients(_EXTRACTION_TIMEOUT_S) as client:
        for m in model_ids:
            for i, art in enumerate(articles, 1):
                r = run_model_on_article(client, api_key, base_url, m, art)
                results.append(r)
                print(
                    f"[run] {m} {i}/{len(articles)} doc={art.doc_id[:8]} "
                    f"status={r.status} {r.latency_s}s ev/cl/rel={r.n_events}/{r.n_claims}/{r.n_relations}"
                )
    return results


def cmd_run(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    results = _run_models(out, model_ids, limit=args.limit)
    _write_json(out / "model_runs.json", [asdict(r) for r in results])
    print(f"Wrote {len(results)} run results → {out / 'model_runs.json'}")


def _judge_all(out: Path, deepinfra_judge_model: str, limit: int | None) -> list[JudgeScore]:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    deepinfra_key = os.environ.get("DEEPINFRA_API_KEY")
    if not anthropic_key and not deepinfra_key:
        sys.exit("Set ANTHROPIC_API_KEY (preferred judge) or DEEPINFRA_API_KEY (fallback judge).")
    articles = {a.doc_id: a for a in _load_golden(out)}
    runs = _load_runs(out)
    if limit:
        runs = runs[:limit]
    scores: list[JudgeScore] = []
    a_client = _make_clients(120.0) if anthropic_key else None
    d_client = _make_clients(120.0) if deepinfra_key else None
    judge_name = _ANTHROPIC_JUDGE_MODEL if anthropic_key else deepinfra_judge_model
    print(f"[judge] using judge model: {judge_name}")
    try:
        for i, run in enumerate(runs, 1):
            art = articles.get(run.doc_id)
            if art is None:
                continue
            s = judge_extraction(
                a_client,
                anthropic_key,
                d_client,
                deepinfra_key,
                deepinfra_judge_model,
                art,
                run,
            )
            scores.append(s)
            print(
                f"[judge] {i}/{len(runs)} {run.model_id} doc={run.doc_id[:8]} "
                f"status={s.status} P/R/A={s.precision}/{s.recall}/{s.adherence}"
            )
    finally:
        if a_client:
            a_client.close()
        if d_client:
            d_client.close()
    return scores


def cmd_judge(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    scores = _judge_all(out, args.judge_model, limit=args.limit)
    _write_json(out / "judge_scores.json", [asdict(s) for s in scores])
    print(f"Wrote {len(scores)} judge scores → {out / 'judge_scores.json'}")


def cmd_report(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    articles = _load_golden(out)
    runs = _load_runs(out)
    scores = _load_scores(out)
    model_ids = list(dict.fromkeys(r.model_id for r in runs))
    aggs = aggregate(runs, scores, model_ids)
    baseline = args.baseline if args.baseline in model_ids else (model_ids[0] if model_ids else "")
    report = build_report_md(aggs, baseline)
    (out / "report.md").write_text(report, encoding="utf-8")
    _write_json(out / "aggregate.json", [asdict(a) for a in aggs])
    (out / "human_spotcheck.md").write_text(build_human_spotcheck(articles, runs, model_ids), encoding="utf-8")
    print(report)
    print(f"\nWrote → {out / 'report.md'}, {out / 'aggregate.json'}, {out / 'human_spotcheck.md'}")


def cmd_estimate_cost(args: argparse.Namespace) -> None:
    out = _out_dir(args.out)
    articles = _load_golden(out)
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    estimate_cost(articles, model_ids)


def cmd_dry_run(args: argparse.Namespace) -> None:
    """Tiny end-to-end smoke test on the first N frozen articles (default 3)."""
    out = _out_dir(args.out)
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    n = args.limit or 3
    print(f"=== DRY RUN: {n} articles x {len(model_ids)} models ===")
    runs = _run_models(out, model_ids, limit=n)
    _write_json(out / "model_runs.json", [asdict(r) for r in runs])
    scores = _judge_all(out, args.judge_model, limit=None)
    _write_json(out / "judge_scores.json", [asdict(s) for s in scores])
    articles = _load_golden(out)[:n]
    aggs = aggregate(runs, scores, model_ids)
    baseline = args.baseline if args.baseline in model_ids else model_ids[0]
    report = build_report_md(aggs, baseline)
    (out / "report.md").write_text(report, encoding="utf-8")
    (out / "human_spotcheck.md").write_text(build_human_spotcheck(articles, runs, model_ids), encoding="utf-8")
    print("\n" + report)
    print(f"\nDry-run artefacts in {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("assemble", help="freeze the golden set from the live DBs")
    pa.add_argument("--out", default="results/extraction_eval")
    pa.add_argument("--sample-size", type=int, default=100)
    pa.set_defaults(func=cmd_assemble)

    pr = sub.add_parser("run", help="run candidate models against the frozen inputs")
    pr.add_argument("--out", default="results/extraction_eval")
    pr.add_argument("--models", default=f"{_PROD_EXTRACTION_MODEL},deepseek-ai/DeepSeek-V4-Flash")
    pr.add_argument("--limit", type=int, default=None, help="cap articles (for cheap re-runs)")
    pr.set_defaults(func=cmd_run)

    pj = sub.add_parser("judge", help="score every model output with the independent judge")
    pj.add_argument("--out", default="results/extraction_eval")
    pj.add_argument("--judge-model", default=_DEEPINFRA_FALLBACK_JUDGE, help="DeepInfra judge if no ANTHROPIC_API_KEY")
    pj.add_argument("--limit", type=int, default=None)
    pj.set_defaults(func=cmd_judge)

    prep = sub.add_parser("report", help="aggregate + render the comparison report")
    prep.add_argument("--out", default="results/extraction_eval")
    prep.add_argument("--baseline", default=_PROD_EXTRACTION_MODEL)
    prep.set_defaults(func=cmd_report)

    pe = sub.add_parser("estimate-cost", help="estimate token + USD cost without spending")
    pe.add_argument("--out", default="results/extraction_eval")
    pe.add_argument("--models", default=f"{_PROD_EXTRACTION_MODEL},deepseek-ai/DeepSeek-V4-Flash")
    pe.set_defaults(func=cmd_estimate_cost)

    pd = sub.add_parser("dry-run", help="tiny end-to-end smoke run (default 3 articles)")
    pd.add_argument("--out", default="results/extraction_eval")
    pd.add_argument("--models", default=f"{_PROD_EXTRACTION_MODEL},deepseek-ai/DeepSeek-V4-Flash")
    pd.add_argument("--judge-model", default=_DEEPINFRA_FALLBACK_JUDGE)
    pd.add_argument("--baseline", default=_PROD_EXTRACTION_MODEL)
    pd.add_argument("--limit", type=int, default=3)
    pd.set_defaults(func=cmd_dry_run)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
