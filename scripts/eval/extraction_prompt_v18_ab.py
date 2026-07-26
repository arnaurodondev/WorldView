#!/usr/bin/env python3
"""Prompt A/B: deep_extraction @1.7 (BASELINE) vs @1.8-trim (CANDIDATE).

Validation-only harness for the v1.8 prompt-trim proposal
(docs/audits/2026-07-26-extraction-prompt-v18-trim-ab.md). READ-ONLY: it never
mutates the pipeline, DB, adapter, or any container. It only:
  * READS nlp_db to assemble a STRATIFIED sample of real news articles (the exact
    {entities} allow-list + {text} window the production pipeline builds), and
  * makes its own DeepInfra HTTP calls (extractor + judge), and
  * applies the REAL production code gate (relation_validation.validate_relations)
    to BOTH arms' raw output.

NO CONFOUND: both arms use the SAME extractor + SAME reasoning_effort (the live
production config). The ONLY thing that differs is the system prompt (v1.7 vs v1.8),
so the measured delta is purely the prompt trim.

Extractor : deepseek-ai/DeepSeek-V4-Flash @ reasoning_effort=medium (live prod config)
Judge     : deepseek-ai/DeepSeek-V4-Flash (repo's budget-judge convention). Because BOTH
            arms are graded by the SAME judge on the SAME articles, any judge self-
            preference bias is COMMON-MODE and cancels in the BASELINE→CANDIDATE delta
            the GO decision depends on. Deterministic structural counters are judge-free.

USAGE
-----
  DEEPINFRA_API_KEY=... NLP_DB_URL=postgresql://postgres:PASS@localhost:5544/nlp_db \
      python scripts/eval/extraction_prompt_v18_ab.py --sample-size 50 \
      --out results/extraction_prompt_v18_ab
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
_EXTRACTOR_MODEL = "deepseek-ai/DeepSeek-V4-Flash"  # live production extractor
_EXTRACTOR_REASONING = "medium"  # live production reasoning_effort
_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"  # repo budget-judge convention
_MAX_TOKENS = 4096
_SINGLE_WINDOW_TOKEN_LIMIT = 24_000

# DeepInfra list price for DeepSeek-V4-Flash (per 1M tokens). Used only to turn the
# authoritative API prompt/completion token counts into a $/doc figure; the token
# counts themselves are the ground truth (usage.prompt_tokens from the API).
# DeepSeek-V4-Flash DeepInfra list price (libs/ml-clients/pricing.py, verified 2026-06).
_PRICE_IN_PER_1M = 0.14
_PRICE_OUT_PER_1M = 0.28

# Directional predicates: subject/object is NOT interchangeable, so a swap is a defect.
# (symmetric predicates competes_with/partner_of are excluded — no direction to invert.)
_DIRECTIONAL_PREDICATES = {
    "acquired_by",
    "analyst_rating",
    "appointed_as",
    "board_member_of",
    "credit_rating",
    "divested_from",
    "downgraded_by",
    "employs",
    "filed_lawsuit_against",
    "has_executive",
    "investment_in",
    "owns_stake_in",
    "price_target",
    "reported_revenue_of",
    "subsidiary_of",
    "supplier_of",
}
_SYMMETRIC_PREDICATES = {"competes_with", "partner_of"}


@dataclass
class Article:
    doc_id: str
    title: str | None
    source_type: str | None
    tier: str
    word_count: int
    entities: str
    text: str
    stratum: str  # "comention_heavy" | "regular"


# ── Stratified sample assembly ─────────────────────────────────────────────────
# Pull a large candidate pool of recent full_pipeline news, then bucket by title into
# co-mention-heavy (peer lists / market recaps / "best stocks" / "X vs Y" / bio) vs
# regular, and fill the sample ~50/50 so the co-mention failure mode (the one with NO
# code backstop) is heavily represented.

_POOL_SQL = """
WITH news AS (
    SELECT DISTINCT ON (rd.doc_id)
           rd.doc_id,
           COALESCE(rd.final_routing_tier, rd.routing_tier) AS tier,
           rd.decided_at
    FROM routing_decisions rd
    WHERE rd.processing_path = 'full_pipeline'
      AND COALESCE(rd.final_routing_tier, rd.routing_tier) IN ('deep','medium')
    ORDER BY rd.doc_id, rd.decided_at DESC
)
SELECT n.doc_id, n.tier, dsm.title, dsm.source_type, dsm.word_count
FROM news n
JOIN document_source_metadata dsm ON dsm.doc_id = n.doc_id
WHERE dsm.source_type IN ('eodhd_ticker_news','finnhub','eodhd','newsapi','eodhd_news','finnhub_news')
  AND COALESCE(dsm.word_count, 0) BETWEEN 150 AND 4000
ORDER BY n.decided_at DESC
LIMIT %(limit)s;
"""

_TEXT_SQL = (
    "SELECT string_agg(c.chunk_text, ' ' ORDER BY c.chunk_index) "
    "FROM chunks c WHERE c.doc_id = %(doc_id)s AND c.chunk_text IS NOT NULL;"
)
_MENTIONS_SQL = (
    "SELECT em.mention_text FROM entity_mentions em "
    "WHERE em.doc_id = %(doc_id)s ORDER BY em.char_start, em.mention_id;"
)

# Title patterns that correlate with co-mention-heavy articles: peer/comparison lists,
# market recaps, "best/top N stocks", "X vs Y", "stocks to buy", sector round-ups.
_COMENTION_TITLE_RE = re.compile(
    r"\b(vs\.?|versus|peers?|rivals?|compared?|comparison|best|top\s+\d|"
    r"\d+\s+(?:stocks?|companies|names|picks)|stocks?\s+to\s+(?:buy|watch|sell)|"
    r"trade[ds]?\s+(?:lower|higher|down|up)|market\s+recap|movers?|gainers?|losers?|"
    r"round[- ]?up|watchlist|screener|which\s+is\s+better|or\b.*\bstock)\b",
    re.IGNORECASE,
)


def _classify(title: str | None, text: str) -> str:
    """Bucket an article as co-mention-heavy or regular from its title + entity density."""
    if title and _COMENTION_TITLE_RE.search(title):
        return "comention_heavy"
    return "regular"


def assemble(sample_size: int) -> list[Article]:
    import psycopg

    url = os.environ.get("NLP_DB_URL", "postgresql://postgres:postgres@localhost:5544/nlp_db")
    url = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
    half = sample_size // 2
    comention: list[Article] = []
    regular: list[Article] = []
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(_POOL_SQL, {"limit": sample_size * 20})
            rows = cur.fetchall()
        for doc_id, tier, title, source_type, wc in rows:
            if len(comention) >= half and len(regular) >= sample_size - half:
                break
            with conn.cursor() as cur:
                cur.execute(_TEXT_SQL, {"doc_id": doc_id})
                r = cur.fetchone()
            text = (r[0] if r else None) or ""
            if not text.strip():
                continue
            words = text.split()
            if len(words) > _SINGLE_WINDOW_TOKEN_LIMIT:
                text = " ".join(words[:_SINGLE_WINDOW_TOKEN_LIMIT])
            with conn.cursor() as cur:
                cur.execute(_MENTIONS_SQL, {"doc_id": doc_id})
                mentions = [m[0] for m in cur.fetchall() if m[0]]
            mention_names = list(dict.fromkeys(mentions))
            if len(mention_names) < 2:
                continue
            stratum = _classify(title, text)
            art = Article(
                doc_id=str(doc_id),
                title=title,
                source_type=source_type,
                tier=str(tier),
                word_count=int(wc or len(words)),
                entities=", ".join(mention_names),
                text=text,
                stratum=stratum,
            )
            bucket = comention if stratum == "comention_heavy" else regular
            cap = half if stratum == "comention_heavy" else sample_size - half
            if len(bucket) < cap:
                bucket.append(art)
    return comention + regular


# ── Prompt rendering ────────────────────────────────────────────────────────────


def _render_v17(entities: str, text: str) -> tuple[str, str]:
    from prompts.extraction.deep import DEEP_EXTRACTION

    return DEEP_EXTRACTION.render(entities=entities, text=text), DEEP_EXTRACTION.identifier()


def _render_v18(entities: str, text: str) -> tuple[str, str]:
    from prompts.extraction.deep_v18 import DEEP_EXTRACTION_V18

    return DEEP_EXTRACTION_V18.render(entities=entities, text=text), DEEP_EXTRACTION_V18.identifier()


# ── DeepInfra call (captures authoritative token usage) ─────────────────────────


def _chat(
    client: httpx.Client,
    key: str,
    model: str,
    system: str,
    user: str,
    *,
    reasoning_effort: str,
    max_tokens: int = _MAX_TOKENS,
    force_json: bool = True,
) -> tuple[str, dict[str, int]]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if force_json:
        body["response_format"] = {"type": "json_object"}
    last = ""
    for attempt in range(1, 7):
        try:
            resp = client.post(
                f"{_DEEPINFRA_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body
            )
        except httpx.HTTPError as e:
            last = f"httpx {type(e).__name__}: {e}"
            time.sleep(min(2.0 * (2 ** (attempt - 1)), 30.0))
            continue
        if resp.status_code == 200:
            j = resp.json()
            content = j["choices"][0]["message"].get("content") or ""
            usage = j.get("usage") or {}
            return content, {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
        last = f"{resp.status_code}: {resp.text[:160]}"
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2.0 * (2 ** (attempt - 1)), 30.0))
            continue
        break
    raise RuntimeError(f"deepinfra call failed: {last}")


def _parse(raw: str) -> dict[str, Any] | None:
    for candidate in (raw, re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


# ── Deterministic structural defect counters (pre-gate, judge-free) ─────────────
# These mirror the production gate's structural checks so we can see whether the
# TRIMMED prompt is intrinsically looser BEFORE the code gate hides the symptom.


def _apply_code_gate(relations: list[Any], entity_classes: dict[str, str]) -> tuple[list[Any], dict[str, int]]:
    from nlp_pipeline.application.blocks.relation_validation import validate_relations

    return validate_relations(relations, entity_classes=entity_classes)


def raw_structural_defects(relations: list[Any]) -> dict[str, int]:
    """Objective pre-gate structural defects (no judge, no NER map needed)."""
    from nlp_pipeline.application.blocks.relation_validation import (
        _VALID_EXCHANGES,
        VALID_PREDICATES,
        _normalize,
        _normalize_exchange,
    )

    out = {"relations": 0, "self_loop": 0, "oov_predicate": 0, "invalid_listed_on": 0}
    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        out["relations"] += 1
        s = _normalize(rel.get("subject_ref"))
        o = _normalize(rel.get("object_ref"))
        p = str(rel.get("predicate") or "").strip()
        if s and o and s == o:
            out["self_loop"] += 1
        if p and p not in VALID_PREDICATES:
            out["oov_predicate"] += 1
        if p == "listed_on" and _normalize_exchange(rel.get("object_ref")) not in _VALID_EXCHANGES:
            out["invalid_listed_on"] += 1
    return out


# ── Independent judge (precision, recall, co-mention FP, direction inversion) ────

_JUDGE_SYSTEM = """\
You are a meticulous financial-NLP reviewer grading the RELATIONS array of an automated
extraction system. You are NOT the system being graded. Judge ONLY against the ARTICLE TEXT.

For EACH relation decide whether the article text ASSERTS that relationship with a
relation-bearing verb/phrase linking the two named entities. Merely co-mentioning both
entities (a market recap, a 'peers such as X, Y, Z' list, a résumé/background enumeration,
an index/sector grouping) does NOT count as an asserted relationship.

Also, for DIRECTIONAL predicates (has_executive, employs, appointed_as, board_member_of,
analyst_rating, price_target, credit_rating, downgraded_by, acquired_by, subsidiary_of,
supplier_of, owns_stake_in, investment_in, divested_from) decide whether subject and
object are in the CORRECT order per normal financial convention (e.g. has_executive:
subject=company, object=person; acquired_by: subject=acquired company, object=acquirer;
supplier_of: subject=supplier, object=buyer). A reversed subject/object is an inversion.

You will receive: ARTICLE TEXT, the ENTITY ALLOW-LIST, and the RELATIONS JSON.

Return ONLY this JSON object, no prose:
{
  "n_relations": <int — relations you were given>,
  "n_supported": <int — relations the text actually ASSERTS (correct predicate, either direction)>,
  "n_comention_fp": <int — relations that are mere co-mention with NO asserted link (a false positive)>,
  "n_directional": <int — relations whose predicate is directional (per the list above)>,
  "n_directional_inverted": <int — of those directional relations, how many have subject/object REVERSED>,
  "recall_grade": <1-5, 5=captured the relationships a careful analyst would; a thin/low-signal article correctly returning [] is a 5>,
  "justification": "<two sentences citing specifics>"
}"""


def _judge_user(art: Article, relations: list[Any]) -> str:
    text = art.text
    words = text.split()
    if len(words) > 6000:
        text = " ".join(words[:6000]) + " […truncated…]"
    return (
        f"ARTICLE TEXT:\n{text}\n\nENTITY ALLOW-LIST:\n{art.entities}\n\n"
        f"RELATIONS JSON:\n{json.dumps(relations, ensure_ascii=False)}\n"
    )


@dataclass
class JudgeResult:
    n_relations: int = 0
    n_supported: int = 0
    n_comention_fp: int = 0
    n_directional: int = 0
    n_directional_inverted: int = 0
    recall_grade: int | None = None
    justification: str = ""
    error: str | None = None


def judge(client: httpx.Client, key: str, art: Article, gated_relations: list[Any]) -> JudgeResult:
    try:
        raw, _ = _chat(
            client,
            key,
            _JUDGE_MODEL,
            _JUDGE_SYSTEM,
            _judge_user(art, gated_relations),
            reasoning_effort="none",
            max_tokens=768,
        )
        v = _parse(raw)
        if v is None:
            return JudgeResult(error="judge produced unparseable JSON")
        return JudgeResult(
            n_relations=_int(v.get("n_relations")) if v.get("n_relations") is not None else len(gated_relations),
            n_supported=_int(v.get("n_supported")) or 0,
            n_comention_fp=_int(v.get("n_comention_fp")) or 0,
            n_directional=_int(v.get("n_directional")) or 0,
            n_directional_inverted=_int(v.get("n_directional_inverted")) or 0,
            recall_grade=_clamp(v.get("recall_grade")),
            justification=str(v.get("justification", ""))[:400],
        )
    except Exception as e:
        return JudgeResult(error=f"{type(e).__name__}: {e}")


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _clamp(v: Any) -> int | None:
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    return max(1, min(5, iv))


# ── Per-arm accumulation ────────────────────────────────────────────────────────


@dataclass
class ArmResult:
    raw_defects: list[dict[str, int]] = field(default_factory=list)
    gate_drops: list[dict[str, int]] = field(default_factory=list)
    gated_counts: list[int] = field(default_factory=list)
    judge: list[JudgeResult] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-size", type=int, default=50)
    ap.add_argument("--out", default="results/extraction_prompt_v18_ab")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    key = os.environ.get("DEEPINFRA_API_KEY")
    if not key:
        sys.exit("DEEPINFRA_API_KEY required.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    gp = out / "sample.json"
    if gp.exists():
        arts = [Article(**a) for a in json.loads(gp.read_text())]
        print(f"[reuse] {len(arts)} articles from {gp}")
    else:
        arts = assemble(args.sample_size)
        gp.write_text(json.dumps([a.__dict__ for a in arts], indent=2, ensure_ascii=False))
        print(f"[assemble] froze {len(arts)} articles → {gp}")
    n_com = sum(1 for a in arts if a.stratum == "comention_heavy")
    print(f"[strata] comention_heavy={n_com}  regular={len(arts) - n_com}")
    if args.limit:
        arts = arts[: args.limit]

    _, v17_id = _render_v17("x", "y")
    _, v18_id = _render_v18("x", "y")
    print(f"[prompts] BASELINE={v17_id}  CANDIDATE={v18_id}")
    if v17_id == v18_id:
        sys.exit("BASELINE and CANDIDATE prompt identifiers are identical.")

    import threading
    from concurrent.futures import ThreadPoolExecutor

    base = ArmResult()
    cand = ArmResult()
    # httpx.Client is thread-safe (shared connection pool); run docs concurrently to
    # cut wall-clock — each doc is 4 sequential-within-worker LLM calls. Both arms use
    # the SAME extractor config, so concurrency does not affect the measured delta.
    client = httpx.Client(
        timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10),
        limits=httpx.Limits(max_connections=24, max_keepalive_connections=24),
    )
    print_lock = threading.Lock()

    def run_arm(art: Article, classes: dict[str, str], render_fn: Any) -> dict[str, Any]:
        sys_prompt, _ = render_fn(art.entities, art.text)
        raw_text, usage = _chat(
            client, key, _EXTRACTOR_MODEL, sys_prompt, art.text, reasoning_effort=_EXTRACTOR_REASONING
        )
        parsed = _parse(raw_text) or {}
        raw_rels = parsed.get("relations") or []
        defects = raw_structural_defects(raw_rels)
        gated, drops = _apply_code_gate(list(raw_rels), classes)
        jr = judge(client, key, art, gated)
        return {"defects": defects, "usage": usage, "gated": gated, "drops": drops, "judge": jr}

    def process(idx_art: tuple[int, Article]) -> tuple[int, dict[str, Any]]:
        i, art = idx_art
        classes = _entity_classes_from_allowlist(art.entities)
        b = run_arm(art, classes, _render_v17)
        a = run_arm(art, classes, _render_v18)
        with print_lock:
            print(
                f"[{i}/{len(arts)}] {art.doc_id[:8]} {art.stratum[:4]} | "
                f"BASE raw={b['defects']['relations']} gated={len(b['gated'])} sup={b['judge'].n_supported} "
                f"comFP={b['judge'].n_comention_fp} inv={b['judge'].n_directional_inverted} ptok={b['usage']['prompt_tokens']} "
                f"|| CAND raw={a['defects']['relations']} gated={len(a['gated'])} sup={a['judge'].n_supported} "
                f"comFP={a['judge'].n_comention_fp} inv={a['judge'].n_directional_inverted} ptok={a['usage']['prompt_tokens']}",
                flush=True,
            )
        return i, {"baseline": b, "candidate": a, "art": art}

    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in ex.map(process, list(enumerate(arts, 1))):
            results[i] = res
    client.close()

    rows: list[dict[str, Any]] = []
    for i in sorted(results):
        res = results[i]
        art = res["art"]
        b, a = res["baseline"], res["candidate"]
        for arm, d in [(base, b), (cand, a)]:
            arm.raw_defects.append(d["defects"])
            arm.gate_drops.append(d["drops"])
            arm.gated_counts.append(len(d["gated"]))
            arm.judge.append(d["judge"])
            arm.prompt_tokens.append(d["usage"]["prompt_tokens"])
            arm.completion_tokens.append(d["usage"]["completion_tokens"])
        rows.append(
            {
                "doc_id": art.doc_id,
                "title": art.title,
                "stratum": art.stratum,
                "tier": art.tier,
                "baseline": {
                    "raw_defects": b["defects"],
                    "gate_drops": b["drops"],
                    "gated_relations": len(b["gated"]),
                    "usage": b["usage"],
                    "judge": b["judge"].__dict__,
                },
                "candidate": {
                    "raw_defects": a["defects"],
                    "gate_drops": a["drops"],
                    "gated_relations": len(a["gated"]),
                    "usage": a["usage"],
                    "judge": a["judge"].__dict__,
                },
            }
        )

    (out / "rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    report = build_report(arts, base, cand, v17_id, v18_id)
    (out / "report.md").write_text(report)
    print("\n" + report)
    print(f"\nWrote {out / 'rows.json'}, {out / 'report.md'}")


def _entity_classes_from_allowlist(entities: str) -> dict[str, str]:
    """Parse the '{name} [{type}]' allow-list back into a {name: class} map for the gate.

    Mirrors how deep_extraction._build_prompt tags entities; lets the code gate run its
    entity-type guard + direction auto-swap exactly as production would for these docs.
    Falls back silently for any token that isn't tagged.
    """
    out: dict[str, str] = {}
    for tok in entities.split(", "):
        m = re.match(r"^(.*?)\s*\[([a-z_]+)\]\s*$", tok.strip())
        if m:
            out[m.group(1).strip()] = m.group(2)
    return out


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def build_report(arts: list[Article], base: ArmResult, cand: ArmResult, base_id: str, cand_id: str) -> str:
    n = len(arts)

    def stats(arm: ArmResult) -> dict[str, Any]:
        raw_rel = sum(d["relations"] for d in arm.raw_defects)
        self_loop = sum(d["self_loop"] for d in arm.raw_defects)
        oov = sum(d["oov_predicate"] for d in arm.raw_defects)
        bad_listed = sum(d["invalid_listed_on"] for d in arm.raw_defects)
        gated_total = sum(arm.gated_counts)
        arts_with_gated = sum(1 for c in arm.gated_counts if c > 0)
        j_ok = [j for j in arm.judge if j.error is None]
        j_rel = sum(j.n_relations for j in j_ok)
        j_sup = sum(j.n_supported for j in j_ok)
        j_com = sum(j.n_comention_fp for j in j_ok)
        j_dir = sum(j.n_directional for j in j_ok)
        j_inv = sum(j.n_directional_inverted for j in j_ok)
        recalls = [j.recall_grade for j in j_ok if j.recall_grade is not None]
        ptok = sum(arm.prompt_tokens)
        ctok = sum(arm.completion_tokens)
        cost = ptok / 1e6 * _PRICE_IN_PER_1M + ctok / 1e6 * _PRICE_OUT_PER_1M
        return {
            "raw_rel": raw_rel,
            "self_loop": self_loop,
            "oov": oov,
            "bad_listed": bad_listed,
            "gated_total": gated_total,
            "arts_with_gated": arts_with_gated,
            "recall_proxy": _safe_div(arts_with_gated, n),
            "precision": _safe_div(j_sup, j_rel),
            "j_rel": j_rel,
            "j_sup": j_sup,
            "comention_fp": j_com,
            "comention_fp_rate": _safe_div(j_com, j_rel),
            "n_directional": j_dir,
            "inv": j_inv,
            "inv_rate": _safe_div(j_inv, j_dir),
            "mean_recall_grade": _safe_div(sum(recalls), len(recalls)) if recalls else None,
            "judge_errors": len(arm.judge) - len(j_ok),
            "ptok": ptok,
            "ctok": ctok,
            "cost": round(cost, 5),
            "ptok_per_doc": _safe_div(ptok, n),
            "cost_per_doc": round(cost / n, 6) if n else None,
        }

    b, c = stats(base), stats(cand)
    L: list[str] = []
    L.append("# Prompt A/B — deep_extraction @1.7 (BASELINE) vs @1.8-trim (CANDIDATE)\n")
    L.append(f"- BASELINE : `{base_id}`")
    L.append(f"- CANDIDATE: `{cand_id}`")
    L.append(f"- Extractor (BOTH arms): `{_EXTRACTOR_MODEL}` @ reasoning_effort={_EXTRACTOR_REASONING} — no confound")
    L.append(
        f"- Judge: `{_JUDGE_MODEL}` (same judge both arms → self-preference bias is common-mode, cancels in delta)"
    )
    n_com = sum(1 for a in arts if a.stratum == "comention_heavy")
    L.append(f"- Sample: {n} real full_pipeline news docs — {n_com} co-mention-heavy / {n - n_com} regular\n")

    L.append("## Precision metrics (post-gate survivors — what reaches the KG)\n")
    L.append("| metric | BASELINE v1.7 | CANDIDATE v1.8 | Δ |")
    L.append("|---|---|---|---|")
    L.append(
        f"| judge precision (supported/emitted) | {b['precision']} ({b['j_sup']}/{b['j_rel']}) | {c['precision']} ({c['j_sup']}/{c['j_rel']}) | {_delta(b['precision'], c['precision'])} |"
    )
    L.append(
        f"| **co-mention FP rate** (FP/emitted) | {b['comention_fp_rate']} ({b['comention_fp']}) | {c['comention_fp_rate']} ({c['comention_fp']}) | {_delta(b['comention_fp_rate'], c['comention_fp_rate'])} |"
    )
    L.append(
        f"| **direction-inversion rate** (inv/directional) | {b['inv_rate']} ({b['inv']}/{b['n_directional']}) | {c['inv_rate']} ({c['inv']}/{c['n_directional']}) | {_delta(b['inv_rate'], c['inv_rate'])} |"
    )
    L.append("\n## Recall metrics\n")
    L.append("| metric | BASELINE v1.7 | CANDIDATE v1.8 |")
    L.append("|---|---|---|")
    L.append(
        f"| gated relations / doc (yield) | {_safe_div(b['gated_total'], n)} ({b['gated_total']}) | {_safe_div(c['gated_total'], n)} ({c['gated_total']}) |"
    )
    L.append(
        f"| articles with ≥1 gated relation | {b['recall_proxy']} ({b['arts_with_gated']}/{n}) | {c['recall_proxy']} ({c['arts_with_gated']}/{n}) |"
    )
    L.append(f"| mean judge recall grade (1-5) | {b['mean_recall_grade']} | {c['mean_recall_grade']} |")
    L.append("\n## Deterministic structural defects — PRE-GATE (intrinsic prompt looseness)\n")
    L.append("| defect (raw, before code gate) | BASELINE v1.7 | CANDIDATE v1.8 |")
    L.append("|---|---|---|")
    L.append(f"| raw relations emitted | {b['raw_rel']} | {c['raw_rel']} |")
    L.append(f"| self-loops | {b['self_loop']} | {c['self_loop']} |")
    L.append(f"| out-of-vocab predicates | {b['oov']} | {c['oov']} |")
    L.append(f"| listed_on → non-exchange | {b['bad_listed']} | {c['bad_listed']} |")
    L.append("\n## Token cost per doc (authoritative — DeepInfra usage.prompt_tokens)\n")
    L.append("| metric | BASELINE v1.7 | CANDIDATE v1.8 | Δ |")
    L.append("|---|---|---|---|")
    L.append(
        f"| mean prompt tokens / doc | {b['ptok_per_doc']} | {c['ptok_per_doc']} | {_delta(b['ptok_per_doc'], c['ptok_per_doc'])} |"
    )
    L.append(f"| total prompt tokens | {b['ptok']} | {c['ptok']} | {c['ptok'] - b['ptok']} |")
    L.append(f"| total completion tokens | {b['ctok']} | {c['ctok']} | {c['ctok'] - b['ctok']} |")
    L.append(
        f"| est. cost / doc (USD) | {b['cost_per_doc']} | {c['cost_per_doc']} | {round((c['cost_per_doc'] or 0) - (b['cost_per_doc'] or 0), 6)} |"
    )
    L.append(f"\n- judge parse errors: baseline={b['judge_errors']} candidate={c['judge_errors']}")
    return "\n".join(L)


def _delta(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "—"
    return f"{b - a:+.4f}"


if __name__ == "__main__":
    main()
