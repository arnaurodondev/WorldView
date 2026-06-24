#!/usr/bin/env python3
"""Prompt A/B: deep_extraction @1.5 (BEFORE) vs @1.6 (AFTER) — recall + precision.

This is a STANDALONE, read-only measurement harness for the relation-extraction
quality work (docs/audits/2026-06-13/14 series). It does NOT mutate the pipeline,
the DB, the adapter, or any container. It only:
  * READS nlp_db to assemble a held-out sample of real news articles (the exact
    {entities} allow-list + {text} window the production pipeline would build), and
  * makes its own DeepInfra HTTP calls (extractor + independent judge).

WHY a dedicated harness (vs scripts/eval/extraction_quality_eval.py)?
  That harness is a MODEL-vs-model A/B (one prompt, N models). This is a
  PROMPT-vs-prompt A/B (one model = the production Qwen3-235B, two prompt
  versions). It renders @1.5 from ``git show HEAD:…/deep.py`` and @1.6 from the
  working tree, calling the SAME extractor under each — and pairs the v1.6 prompt
  with reasoning_effort="low" (the change that ships together) so the measured
  delta is what production will actually see.

INDEPENDENT JUDGE (self-preference guard):
  The extractor is ``Qwen/Qwen3-235B-A22B-Instruct-2507``. The judge is
  ``deepseek-ai/DeepSeek-V3.1`` — a DIFFERENT model family (DeepSeek MoE), so the
  judge never grades its own family's output. (Anthropic Opus would be the cleanest
  independence guarantee but no ANTHROPIC_API_KEY is available in this environment.)

DETERMINISTIC DEFECT COUNTERS (model-independent, objective):
  DeepInfra is non-deterministic at temperature=0 (the audits document this), so
  raw relation COUNTS are noisy. We therefore ALSO compute objective, code-side
  structural defect rates that do not depend on the judge: self-loops, out-of-vocab
  predicates, and index/ticker-as-listed_on. These are the precision signals the
  v1.6 prompt directly targets.

USAGE
-----
  DEEPINFRA_API_KEY=... NLP_DB_URL=postgresql://postgres:postgres@localhost:5432/nlp_db \
      python scripts/eval/extraction_prompt_v16_ab.py --sample-size 40 \
      --out results/extraction_prompt_v16_ab
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
_EXTRACTOR_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # production extractor
_JUDGE_MODEL = "deepseek-ai/DeepSeek-V3.1"  # independent — different family
_MAX_TOKENS = 4096
_SINGLE_WINDOW_TOKEN_LIMIT = 24_000

# The 32 valid predicates (mirrors deep_extraction.py / relation_type_registry).
_VALID_PREDICATES = {
    "acquired_by", "analyst_rating", "appointed_as", "board_member_of",
    "competes_with", "corporate_action", "credit_rating", "divested_from",
    "downgraded_by", "earnings_guidance", "earnings_released", "employs",
    "filed_lawsuit_against", "has_executive", "headquartered_in", "investment_in",
    "is_in_industry", "is_in_sector", "issues_debt", "listed_on",
    "market_share_claim", "operates_in_country", "owns_stake_in", "partner_of",
    "price_target", "produces", "regulates", "reported_revenue_of",
    "revenue_from_country", "sentiment_signal", "subsidiary_of", "supplier_of",
}
# Symmetric predicates most prone to co-mention hallucination (the v1.6 target).
_SYMMETRIC_PREDICATES = {"competes_with", "partner_of", "supplier_of"}
# Real exchanges — anything else under listed_on is a defect (index/ticker/common noun).
_REAL_EXCHANGES = {
    "NYSE", "NASDAQ", "NYSE AMERICAN", "NYSEAMERICAN", "AMEX", "LSE", "TSX",
    "TSXV", "HKEX", "SSE", "SZSE", "BSE", "NSE", "ASX", "JPX", "TSE", "FWB",
    "XETRA", "EURONEXT", "SIX", "OTC", "OTCMKTS", "CBOE", "NASDAQ GS", "NMS",
}
_INDEX_TOKENS = {"S&P 500", "S&P500", "DOW", "DOW JONES", "NASDAQ COMPOSITE",
                 "RUSSELL 2000", "FTSE 100", "NIKKEI", "DAX", "CAC 40"}


# ── Golden sample ──────────────────────────────────────────────────────────────


@dataclass
class Article:
    doc_id: str
    title: str | None
    source_type: str | None
    tier: str
    word_count: int
    entities: str  # the {entities} prompt fill
    text: str  # the {text} prompt fill


_SAMPLE_SQL = """
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


def assemble(sample_size: int) -> list[Article]:
    import psycopg

    url = os.environ.get("NLP_DB_URL", "postgresql://postgres:postgres@localhost:5432/nlp_db")
    url = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
    arts: list[Article] = []
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(_SAMPLE_SQL, {"limit": sample_size * 3})
            rows = cur.fetchall()
        for doc_id, tier, title, source_type, wc in rows:
            with conn.cursor() as cur:
                cur.execute(_TEXT_SQL, {"doc_id": doc_id})
                row = cur.fetchone()
            text = (row[0] if row else None) or ""
            if not text.strip():
                continue
            words = text.split()
            if len(words) > _SINGLE_WINDOW_TOKEN_LIMIT:
                text = " ".join(words[:_SINGLE_WINDOW_TOKEN_LIMIT])
            with conn.cursor() as cur:
                cur.execute(_MENTIONS_SQL, {"doc_id": doc_id})
                mentions = [r[0] for r in cur.fetchall() if r[0]]
            # Need ≥2 distinct entities for a relation to even be possible.
            mention_names = list(dict.fromkeys(mentions))
            if len(mention_names) < 2:
                continue
            arts.append(Article(
                doc_id=str(doc_id), title=title, source_type=source_type, tier=str(tier),
                word_count=int(wc or len(words)),
                entities=", ".join(mention_names), text=text,
            ))
            if len(arts) >= sample_size:
                break
    return arts


# ── Prompt rendering (both versions) ───────────────────────────────────────────


def _render_working_tree(entities: str, text: str) -> tuple[str, str]:
    """Render the WORKING-TREE prompt (=@1.6). Returns (rendered, identifier)."""
    from prompts.extraction.deep import DEEP_EXTRACTION

    return DEEP_EXTRACTION.render(entities=entities, text=text), DEEP_EXTRACTION.identifier()


def _load_head_template(repo_root: Path) -> tuple[str, str]:
    """Load the @1.5 (git HEAD) prompt body + identifier via a throwaway module exec."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:libs/prompts/src/prompts/extraction/deep.py"], cwd=repo_root, text=True,
    )
    # Execute the HEAD source in an isolated namespace so DEEP_EXTRACTION (HEAD)
    # coexists with the working-tree import. The module only imports from prompts._base.
    ns: dict[str, Any] = {}
    exec(compile(src, "<deep_head>", "exec"), ns)  # noqa: S102 — trusted repo source
    tmpl = ns["DEEP_EXTRACTION"]
    return tmpl.template, tmpl.identifier()  # template body for manual .format below


def _render_head(head_body: str, entities: str, text: str) -> str:
    return head_body.format(entities=entities, text=text)


# ── DeepInfra call ──────────────────────────────────────────────────────────────


def _chat(client: httpx.Client, key: str, model: str, system: str, user: str,
          *, reasoning_effort: str, max_tokens: int = _MAX_TOKENS, force_json: bool = True) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if force_json:
        body["response_format"] = {"type": "json_object"}
    # Bounded retry on 429/5xx (mirrors the production adapter so a busy-hour burst
    # never substitutes an empty result — same hardening as the deployed fix).
    last = ""
    for attempt in range(1, 6):
        resp = client.post(f"{_DEEPINFRA_BASE_URL}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"}, json=body)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"].get("content") or ""
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


# ── Deterministic, model-independent defect counters ───────────────────────────


def code_defects(parsed: dict[str, Any] | None) -> dict[str, int]:
    """Objective structural defects in a relation set (no judge needed)."""
    out = {"relations": 0, "self_loop": 0, "oov_predicate": 0,
           "listed_on_bad_object": 0, "symmetric": 0}
    if not parsed:
        return out
    for rel in parsed.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        out["relations"] += 1
        subj = str(rel.get("subject_ref", "")).strip()
        obj = str(rel.get("object_ref", "")).strip()
        pred = str(rel.get("predicate", "")).strip()
        if subj and obj and subj.lower() == obj.lower():
            out["self_loop"] += 1
        if pred and pred not in _VALID_PREDICATES:
            out["oov_predicate"] += 1
        if pred in _SYMMETRIC_PREDICATES:
            out["symmetric"] += 1
        if pred == "listed_on":
            o_up = obj.upper()
            if o_up in _INDEX_TOKENS or o_up not in _REAL_EXCHANGES:
                # not a recognised exchange (index, ticker, or common noun)
                out["listed_on_bad_object"] += 1
    return out


# ── Independent judge ──────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """\
You are a meticulous financial-NLP reviewer grading the RELATIONS array of an
automated extraction system. You are NOT the system being graded. For EACH relation
decide whether the article text ASSERTS that relationship (contains a relation-bearing
verb/phrase linking the two entities) — merely co-mentioning both entities in a
sentence (a market recap, a 'peers such as X, Y, Z' list, a résumé enumeration) does
NOT count as support. A self-loop (subject == object), an out-of-controlled-vocabulary
predicate, or listed_on pointing at an index/ticker (not a stock exchange) is unsupported.

You will receive: ARTICLE TEXT, the ENTITY ALLOW-LIST, and the RELATIONS JSON.

Return ONLY this JSON object, no prose:
{
  "n_relations": <int — relations you were given>,
  "n_supported": <int — relations the text actually ASSERTS>,
  "n_symmetric": <int — competes_with/partner_of/supplier_of relations given>,
  "n_symmetric_supported": <int — of those, how many the text actually ASSERTS>,
  "n_comention_hallucinations": <int — relations that are mere co-mention, no asserted link>,
  "recall_grade": <1-5, 5=captured the relationships a careful analyst would; a thin/low-signal article correctly returning [] is a 5>,
  "justification": "<two sentences citing specifics>"
}"""


def _judge_user(art: Article, relations: list[Any]) -> str:
    text = art.text
    words = text.split()
    if len(words) > 6000:
        text = " ".join(words[:6000]) + " […truncated…]"
    return (f"ARTICLE TEXT:\n{text}\n\nENTITY ALLOW-LIST:\n{art.entities}\n\n"
            f"RELATIONS JSON:\n{json.dumps(relations, ensure_ascii=False)}\n")


@dataclass
class JudgeResult:
    n_relations: int = 0
    n_supported: int = 0
    n_symmetric: int = 0
    n_symmetric_supported: int = 0
    n_comention_hallucinations: int = 0
    recall_grade: int | None = None
    justification: str = ""
    error: str | None = None


def judge(client: httpx.Client, key: str, art: Article, parsed: dict[str, Any] | None) -> JudgeResult:
    relations = (parsed or {}).get("relations") or []
    if not relations:
        # No relations to support; recall is judged separately (empty may be correct).
        try:
            raw = _chat(client, key, _JUDGE_MODEL, _JUDGE_SYSTEM, _judge_user(art, []),
                        reasoning_effort="none", max_tokens=512)
            v = _parse(raw) or {}
            return JudgeResult(recall_grade=_clamp(v.get("recall_grade")), justification=str(v.get("justification", ""))[:400])
        except Exception as e:
            return JudgeResult(error=f"{type(e).__name__}: {e}")
    try:
        raw = _chat(client, key, _JUDGE_MODEL, _JUDGE_SYSTEM, _judge_user(art, relations),
                    reasoning_effort="none", max_tokens=768)
        v = _parse(raw)
        if v is None:
            return JudgeResult(error="judge produced unparseable JSON")
        return JudgeResult(
            n_relations=_int(v.get("n_relations")) or len(relations),
            n_supported=_int(v.get("n_supported")) or 0,
            n_symmetric=_int(v.get("n_symmetric")) or 0,
            n_symmetric_supported=_int(v.get("n_symmetric_supported")) or 0,
            n_comention_hallucinations=_int(v.get("n_comention_hallucinations")) or 0,
            recall_grade=_clamp(v.get("recall_grade")),
            justification=str(v.get("justification", ""))[:400],
        )
    except Exception as e:
        return JudgeResult(error=f"{type(e).__name__}: {e}")


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clamp(v: Any) -> int | None:
    iv = _int(v)
    return None if iv is None else max(1, min(5, iv))


# ── Main ────────────────────────────────────────────────────────────────────────


@dataclass
class ArmResult:
    relations: list[dict[str, int]] = field(default_factory=list)  # per-article code defects
    judge: list[JudgeResult] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)


def _collect_confidences(parsed: dict[str, Any] | None) -> list[float]:
    out: list[float] = []
    for rel in (parsed or {}).get("relations") or []:
        if isinstance(rel, dict):
            c = rel.get("confidence")
            if isinstance(c, int | float):
                out.append(float(c))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-size", type=int, default=40)
    ap.add_argument("--out", default="results/extraction_prompt_v16_ab")
    ap.add_argument("--limit", type=int, default=None, help="cap articles actually called (cheap reruns)")
    args = ap.parse_args()

    key = os.environ.get("DEEPINFRA_API_KEY")
    if not key:
        sys.exit("DEEPINFRA_API_KEY required.")

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "libs" / "prompts" / "src"))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Assemble (or reload) the frozen sample.
    gp = out / "sample.json"
    if gp.exists():
        arts = [Article(**a) for a in json.loads(gp.read_text())]
        print(f"[reuse] {len(arts)} articles from {gp}")
    else:
        arts = assemble(args.sample_size)
        gp.write_text(json.dumps([a.__dict__ for a in arts], indent=2, ensure_ascii=False))
        print(f"[assemble] froze {len(arts)} articles → {gp}")
    if args.limit:
        arts = arts[: args.limit]

    head_body, head_id = _load_head_template(repo_root)
    _, wt_id = _render_working_tree("x", "y")
    print(f"[prompts] BEFORE={head_id}  AFTER={wt_id}")
    if head_id == wt_id:
        sys.exit("BEFORE and AFTER prompt identifiers are identical — nothing to A/B.")

    before = ArmResult()
    after = ArmResult()
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(connect=10, read=180, write=30, pool=10)) as client:
        for i, art in enumerate(arts, 1):
            # BEFORE = @1.5 prompt + reasoning_effort=none (its production config).
            b_raw = _chat(client, key, _EXTRACTOR_MODEL, _render_head(head_body, art.entities, art.text),
                          art.text, reasoning_effort="none")
            b_parsed = _parse(b_raw)
            # AFTER = @1.6 prompt + reasoning_effort=low (the paired change that ships).
            a_sys, _ = _render_working_tree(art.entities, art.text)
            a_raw = _chat(client, key, _EXTRACTOR_MODEL, a_sys, art.text, reasoning_effort="low")
            a_parsed = _parse(a_raw)

            b_def, a_def = code_defects(b_parsed), code_defects(a_parsed)
            b_j = judge(client, key, art, b_parsed)
            a_j = judge(client, key, art, a_parsed)
            before.relations.append(b_def)
            before.judge.append(b_j)
            after.relations.append(a_def)
            after.judge.append(a_j)
            before.confidences += _collect_confidences(b_parsed)
            after.confidences += _collect_confidences(a_parsed)

            rows.append({
                "doc_id": art.doc_id, "title": art.title, "tier": art.tier,
                "before": {"defects": b_def, "judge": b_j.__dict__},
                "after": {"defects": a_def, "judge": a_j.__dict__},
            })
            print(f"[{i}/{len(arts)}] {art.doc_id[:8]} "
                  f"BEFORE rel={b_def['relations']} sup={b_j.n_supported} loop={b_def['self_loop']} "
                  f"| AFTER rel={a_def['relations']} sup={a_j.n_supported} loop={a_def['self_loop']}")

    (out / "rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    report = build_report(arts, before, after, head_id, wt_id)
    (out / "report.md").write_text(report)
    print("\n" + report)
    print(f"\nWrote {out / 'rows.json'}, {out / 'report.md'}")


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


def _stdev(xs: list[float]) -> float | None:
    import statistics
    return round(statistics.pstdev(xs), 4) if len(xs) > 1 else None


def build_report(arts: list[Article], before: ArmResult, after: ArmResult, before_id: str, after_id: str) -> str:
    n = len(arts)

    def arm_stats(arm: ArmResult) -> dict[str, Any]:
        total_rel = sum(d["relations"] for d in arm.relations)
        self_loop = sum(d["self_loop"] for d in arm.relations)
        oov = sum(d["oov_predicate"] for d in arm.relations)
        listed_bad = sum(d["listed_on_bad_object"] for d in arm.relations)
        sym = sum(d["symmetric"] for d in arm.relations)
        arts_with_rel = sum(1 for d in arm.relations if d["relations"] > 0)
        j_ok = [j for j in arm.judge if j.error is None]
        j_sup = sum(j.n_supported for j in j_ok)
        j_rel = sum(j.n_relations for j in j_ok)
        j_sym = sum(j.n_symmetric for j in j_ok)
        j_sym_sup = sum(j.n_symmetric_supported for j in j_ok)
        j_com = sum(j.n_comention_hallucinations for j in j_ok)
        recalls = [j.recall_grade for j in j_ok if j.recall_grade is not None]
        return {
            "total_rel": total_rel, "self_loop": self_loop, "oov": oov,
            "listed_bad": listed_bad, "sym": sym, "arts_with_rel": arts_with_rel,
            "recall_proxy": _safe_div(arts_with_rel, n),
            "judge_precision": _safe_div(j_sup, j_rel),
            "judge_sym_precision": _safe_div(j_sym_sup, j_sym),
            "comention_halluc": j_com,
            "mean_recall_grade": _safe_div(sum(recalls), len(recalls)) if recalls else None,
            "conf_stdev": _stdev(arm.confidences), "conf_n": len(arm.confidences),
            "conf_distinct": len({round(c, 3) for c in arm.confidences}),
        }

    b, a = arm_stats(before), arm_stats(after)
    L: list[str] = []
    L.append("# Prompt A/B — deep_extraction @1.5 (BEFORE) vs @1.6 (AFTER)\n")
    L.append(f"- BEFORE: `{before_id}` + reasoning_effort=none")
    L.append(f"- AFTER:  `{after_id}` + reasoning_effort=low")
    L.append(f"- Extractor: `{_EXTRACTOR_MODEL}` | Independent judge: `{_JUDGE_MODEL}` (different family)")
    L.append(f"- Sample: {n} held-out full_pipeline news articles (≥2 entities), silver body text\n")
    L.append("## Recall\n")
    L.append("| metric | BEFORE | AFTER |")
    L.append("|---|---|---|")
    L.append(f"| articles producing ≥1 relation (proxy) | {b['recall_proxy']} ({b['arts_with_rel']}/{n}) | {a['recall_proxy']} ({a['arts_with_rel']}/{n}) |")
    L.append(f"| total relations emitted | {b['total_rel']} | {a['total_rel']} |")
    L.append(f"| mean judge recall grade (1-5) | {b['mean_recall_grade']} | {a['mean_recall_grade']} |")
    L.append("\n## Precision (independent judge — relation supported by its evidence?)\n")
    L.append("| metric | BEFORE | AFTER |")
    L.append("|---|---|---|")
    L.append(f"| overall precision (supported / emitted) | {b['judge_precision']} | {a['judge_precision']} |")
    L.append(f"| **symmetric-predicate precision** | {b['judge_sym_precision']} | {a['judge_sym_precision']} |")
    L.append(f"| co-mention hallucinations (count) | {b['comention_halluc']} | {a['comention_halluc']} |")
    L.append("\n## Deterministic structural defects (code-side, judge-independent)\n")
    L.append("| defect | BEFORE | AFTER |")
    L.append("|---|---|---|")
    L.append(f"| self-loops | {b['self_loop']} | {a['self_loop']} |")
    L.append(f"| out-of-vocab predicates | {b['oov']} | {a['oov']} |")
    L.append(f"| listed_on → non-exchange | {b['listed_bad']} | {a['listed_bad']} |")
    L.append(f"| symmetric relations emitted | {b['sym']} | {a['sym']} |")
    L.append("\n## extraction_confidence discriminative variance\n")
    L.append("| metric | BEFORE | AFTER |")
    L.append("|---|---|---|")
    L.append(f"| confidence stdev | {b['conf_stdev']} | {a['conf_stdev']} |")
    L.append(f"| distinct confidence values / total | {b['conf_distinct']}/{b['conf_n']} | {a['conf_distinct']}/{a['conf_n']} |")
    return "\n".join(L)


if __name__ == "__main__":
    main()
