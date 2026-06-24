"""Trustworthy RE-MEASUREMENT of stored knowledge-graph relation quality.

Why this script exists
----------------------
A prior audit (``validate_stored_relation_quality.py`` → 27.6% SUPPORTED) is an
UNRELIABLE pessimistic floor for three reasons, each fixed here:

  (1) ALL-EVIDENCE judging. The prior run judged each relation against only ONE
      (longest) ``relation_evidence`` snippet. Here we pass EVERY distinct snippet
      and mark SUPPORTED if ANY snippet asserts the triple.
  (2) STRONGER, INDEPENDENT judge. The prior run used a budget judge
      (deepseek-ai/DeepSeek-V4-Flash) that over-flags. Here we use
      Qwen/Qwen3-235B-A22B-Instruct-2507 (reasoning model, ``reasoning_effort=low``)
      — strong, cheap, and NOT the gpt-oss-120b extractor (no self-preference).
  (3) DIRECTION CONVENTIONS. The prior judge was never told the canonical
      subject→object meaning of each predicate, so it penalised legitimate
      convention choices. Here every predicate's convention (read verbatim from
      ``libs/prompts/.../extraction/deep.py``) is injected into the judge prompt.

We re-judge the SAME 382 relation_ids from ``/tmp/wv_verdicts.json`` so the result
is directly comparable to the Flash/single-snippet baseline (isolating methodology).

READ-ONLY on the DB: evidence is fetched once via a single batched ``docker exec
psql`` SELECT (see ``fetch_evidence``); this script then only calls DeepInfra.

Usage
-----
    source .venv312/bin/activate
    KEY=$(docker exec worldview-nlp-pipeline-article-consumer-0-1 \
            printenv NLP_PIPELINE_EXTRACTION_API_KEY)
    python scripts/eval/remeasure_stored_relation_quality.py \
        --key "$KEY" \
        --prior /tmp/wv_verdicts.json \
        --evidence-tsv /tmp/wv_all_evidence.tsv \
        --out /tmp/wv_remeasure_verdicts.json
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import json
import math
import sys
import threading
import time

import httpx

JUDGE_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"

# ---------------------------------------------------------------------------
# Direction conventions — read VERBATIM from
#   libs/prompts/src/prompts/extraction/deep.py  (DEEP_EXTRACTION predicate list
#   + "DIRECTION RULE FOR PERSON-COMPANY RELATIONS")
# and services/knowledge-graph/src/knowledge_graph/domain/enums.py (RelationType).
# These are the conventions the EXTRACTOR was instructed to follow, so the judge
# must apply the SAME convention or it will mis-flag legitimate direction choices.
# ---------------------------------------------------------------------------
CONVENTIONS: dict[str, str] = {
    "acquired_by": "subject = the ACQUIRED company; object = the ACQUIRER. "
    "Membership in an acquiring consortium counts (consortium incl. X acquiring Y => Y acquired_by X).",
    "analyst_rating": "an analyst/firm issued a rating on a company. "
    "Convention: subject = the RATED COMPANY, object = the analyst/rating FIRM (e.g. Zacks). "
    "If no rating-firm is the object but a rating exists on the subject company, treat as SUPPORTED.",
    "appointed_as": "subject = the COMPANY, object = the PERSON appointed to a formal role (new hire / appointment).",
    "board_member_of": "subject = the PERSON, object = the COMPANY whose board they sit on.",
    "competes_with": "symmetric rivalry between two companies (direction is not meaningful; either order is fine).",
    "corporate_action": "subject = the COMPANY announcing a dividend / buyback / spin-off / split; "
    "object = the action or affected entity.",
    "credit_rating": "subject = the RATED COMPANY, object = the rating AGENCY issuing a credit rating.",
    "divested_from": "subject = the DIVESTING company; object = the DIVESTED entity (asset / unit / company sold).",
    "downgraded_by": "subject = the COMPANY downgraded; object = the analyst FIRM or rating AGENCY doing the downgrade.",
    "earnings_guidance": "subject = the COMPANY issuing forward earnings guidance; object = the guidance/metric.",
    "earnings_released": "subject = the COMPANY reporting quarterly/annual earnings; object = the earnings/period.",
    "employs": "subject = the COMPANY, object = the PERSON (ongoing employment). NEVER person as subject.",
    "filed_lawsuit_against": "subject = the PLAINTIFF, object = the DEFENDANT.",
    "has_executive": "subject = the COMPANY, object = the named EXECUTIVE PERSON "
    "(CEO/CFO/CTO/President/COO/MD/Chairman). The person is ALWAYS the object.",
    "headquartered_in": "subject = the COMPANY, object = the PLACE (city or country) of its primary HQ.",
    "investment_in": "subject = the INVESTOR (fund/company), object = the INVESTEE.",
    "is_in_industry": "subject = the COMPANY, object = the GICS INDUSTRY it belongs to.",
    "is_in_sector": "subject = the COMPANY, object = the broad GICS SECTOR it belongs to.",
    "issues_debt": "subject = the COMPANY issuing bonds / taking a loan; object = the debt instrument/lender.",
    "listed_on": "subject = the COMPANY/security, object = the EXCHANGE its shares trade on.",
    "market_share_claim": "subject = the COMPANY, object = the market/segment in which a share % is claimed.",
    "operates_in_country": "subject = the COMPANY, object = the COUNTRY it has significant business in.",
    "owns_stake_in": "subject = the OWNER (company/person), object = the INVESTEE it owns equity in.",
    "partner_of": "formal partnership / JV / alliance between two parties (direction not meaningful; either order is fine).",
    "price_target": "subject = the COMPANY whose stock has a price target; object = the analyst/firm or the target.",
    "produces": "subject = the COMPANY, object = the PRODUCT or service it makes.",
    "regulates": "subject = the REGULATOR (government body), object = the company/sector regulated.",
    "reported_revenue_of": "subject = the COMPANY, object = the SEGMENT / GEOGRAPHY whose revenue was reported.",
    "revenue_from_country": "subject = the COMPANY, object = the COUNTRY it derives material revenue from.",
    "sentiment_signal": "a general sentiment expression about the subject entity not captured by other predicates.",
    "subsidiary_of": "subject = the SUBSIDIARY, object = the PARENT company.",
    "supplier_of": "subject = the SUPPLIER, object = the BUYER it supplies goods/services to.",
}

SYSTEM_PROMPT = (
    "You are a careful, fair knowledge-graph relation auditor. You are given a candidate "
    "triple (SUBJECT, PREDICATE, OBJECT), the CANONICAL CONVENTION for that predicate "
    "(the exact subject->object meaning the extractor was instructed to use), and ONE OR "
    "MORE evidence snippets pulled from news/filings.\n\n"
    "A relation is SUPPORTED if ANY single snippet asserts the triple under the stated "
    "CONVENTION with a relation-bearing verb or phrase. You do NOT need all snippets to "
    "agree; one sufficient snippet is enough. Apply the CONVENTION exactly as given — do "
    "not invent a different subject/object orientation.\n\n"
    "Be fair, not pedantic:\n"
    "- Membership in a named consortium/group/syndicate that performs the action COUNTS "
    "(e.g. 'a consortium including Fairfax is acquiring Kennedy-Wilson' SUPPORTS "
    "Kennedy-Wilson acquired_by Fairfax).\n"
    "- Apposition / titles count (e.g. 'Tim Cook, CEO of Apple' SUPPORTS Apple has_executive Tim Cook).\n"
    "- For symmetric predicates (competes_with, partner_of) either subject/object order is acceptable.\n"
    "- A relation stated with hedging ('agreed to', 'plans to', 'is set to') still counts as SUPPORTED.\n\n"
    "Choose exactly ONE verdict:\n"
    '  "SUPPORTED"       = some snippet asserts SUBJECT-PREDICATE-OBJECT under the convention.\n'
    '  "CO_MENTION"      = both entities appear but NO relation of this kind is asserted '
    "between them (merely listed/adjacent).\n"
    '  "WRONG_DIRECTION" = the relation exists in evidence but SUBJECT and OBJECT are '
    "swapped relative to the stated convention.\n"
    '  "WRONG_PREDICATE" = a real relation exists between the two entities but a DIFFERENT '
    "predicate fits the evidence, not this one (judge ONLY against the stated convention).\n"
    '  "UNSUPPORTED"     = no support at all (wrong entity, hallucinated, evidence unrelated).\n\n"'
    "Output STRICT JSON only, no prose:\n"
    '{"verdict": "...", "confidence": 0.0-1.0, "reason": "<=18 words"}'
)


def build_user_prompt(subj: str, pred: str, obj: str, snippets: list[str]) -> str:
    convention = CONVENTIONS.get(pred, "(no convention recorded — judge by plain meaning of the predicate)")
    ev_block = "\n".join(f"[{i + 1}] {s}" for i, s in enumerate(snippets))
    return (
        f"SUBJECT: {subj}\n"
        f"PREDICATE: {pred}\n"
        f"OBJECT: {obj}\n"
        f"CONVENTION for '{pred}': {convention}\n\n"
        f"EVIDENCE SNIPPETS ({len(snippets)}):\n{ev_block}\n\n"
        f"Does ANY snippet assert SUBJECT -{pred}-> OBJECT under the stated convention? "
        "Return the strict JSON verdict."
    )


def judge_one(client: httpx.Client, key: str, row: dict) -> dict:
    payload = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 400,
        "reasoning_effort": "low",  # REQUIRED — Qwen3 reasoning model returns empty content otherwise
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    row["subject_name"], row["predicate"], row["object_name"], row["snippets"]
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    backoff = 2.0
    for attempt in range(7):
        try:
            r = client.post(DEEPINFRA_URL, json=payload, headers=headers, timeout=120.0)
            if r.status_code == 429:
                time.sleep(backoff)
                backoff = min(backoff * 2, 40)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise ValueError("empty content")
            parsed = json.loads(content)
            return {
                "verdict": str(parsed.get("verdict", "PARSE_ERROR")).upper(),
                "confidence": parsed.get("confidence"),
                "reason": parsed.get("reason", ""),
            }
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            if attempt == 6:
                return {"verdict": "JUDGE_ERROR", "confidence": None, "reason": str(exc)[:120]}
            time.sleep(backoff)
            backoff = min(backoff * 2, 40)
    return {"verdict": "JUDGE_ERROR", "confidence": None, "reason": "exhausted retries"}


def load_prior(path: str) -> list[dict]:
    """The 382 relations to re-judge (relation_id + subject/pred/object + era)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_evidence(tsv_path: str) -> dict[str, list[str]]:
    """relation_id -> list of DISTINCT evidence snippets (already deduped by the SQL)."""
    by_rel: dict[str, list[str]] = collections.defaultdict(list)
    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for rec in reader:
            if len(rec) < 2:
                continue
            rid, text = rec[0], rec[1]
            text = text.strip()
            if text and text not in by_rel[rid]:
                by_rel[rid].append(text)
    return by_rel


def wilson_ci(sup: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = sup / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# Full predicate frequencies in the `relations` table (SELECT canonical_type,count(*) ...),
# captured 2026-06-20. Used for the VOLUME-WEIGHTED support rate.
PREDICATE_FREQ: dict[str, int] = {
    "operates_in_country": 1923,
    "listed_on": 1497,
    "competes_with": 1263,
    "partner_of": 1137,
    "analyst_rating": 949,
    "has_executive": 801,
    "headquartered_in": 780,
    "is_in_sector": 683,
    "regulates": 586,
    "produces": 496,
    "investment_in": 454,
    "price_target": 436,
    "supplier_of": 263,
    "employs": 215,
    "acquired_by": 215,
    "sentiment_signal": 171,
    "reported_revenue_of": 168,
    "owns_stake_in": 158,
    "board_member_of": 157,
    "subsidiary_of": 141,
    "appointed_as": 132,
    "corporate_action": 129,
    "filed_lawsuit_against": 126,
    "revenue_from_country": 124,
    "is_in_industry": 121,
    "divested_from": 108,
    "downgraded_by": 70,
    "earnings_released": 58,
    "issues_debt": 42,
    "market_share_claim": 23,
    "earnings_guidance": 12,
    "credit_rating": 11,
}
TOTAL_RELATIONS = sum(PREDICATE_FREQ.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--prior", required=True, help="prior verdicts JSON (the 382 relation_ids to re-judge)")
    ap.add_argument("--evidence-tsv", required=True, help="relation_id\\tevidence_text (all distinct snippets)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6, help="concurrent judge calls (keep modest)")
    args = ap.parse_args()

    prior = load_prior(args.prior)
    evidence = load_evidence(args.evidence_tsv)

    rows: list[dict] = []
    for p in prior:
        rid = p["relation_id"]
        snippets = evidence.get(rid) or [p.get("evidence_text", "")]
        rows.append(
            {
                "relation_id": rid,
                "era": p["era"],
                "subject_name": p["subject_name"],
                "predicate": p["predicate"],
                "object_name": p["object_name"],
                "snippets": snippets,
                "n_snippets": len(snippets),
                "prior_verdict": p["verdict"],
            }
        )
    print(f"loaded {len(rows)} relations; total snippets={sum(r['n_snippets'] for r in rows)}", file=sys.stderr)

    thread_local = threading.local()
    done = [0]
    lock = threading.Lock()

    def worker(idx_row: tuple[int, dict]) -> tuple[int, dict]:
        _, row = idx_row
        client = getattr(thread_local, "client", None)
        if client is None:
            client = httpx.Client()
            thread_local.client = client
        verdict = judge_one(client, args.key, row)
        with lock:
            done[0] += 1
            if done[0] % 20 == 0:
                print(f"  judged {done[0]}/{len(rows)}", file=sys.stderr)
        out = {**row, **verdict}
        out.pop("snippets", None)  # keep verdict file small; snippets re-derivable from TSV
        out["snippets"] = row["snippets"]
        return idx_row[0], out

    results_by_idx: dict[int, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for idx, res in pool.map(worker, list(enumerate(rows))):
            results_by_idx[idx] = res
    results = [results_by_idx[i] for i in range(len(rows))]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # ── Aggregate ────────────────────────────────────────────────────────────
    def rate(items: list[dict]) -> tuple[int, int, float]:
        valid = [r for r in items if r["verdict"] not in ("JUDGE_ERROR", "PARSE_ERROR")]
        sup = sum(1 for r in valid if r["verdict"] == "SUPPORTED")
        n = len(valid)
        return sup, n, (sup / n if n else 0.0)

    def breakdown(items: list[dict]) -> dict[str, int]:
        return dict(collections.Counter(r["verdict"] for r in items))

    print("\n================ RE-MEASURE AGGREGATE ================")
    s, n, p = rate(results)
    lo, hi = wilson_ci(s, n)
    print(f"OVERALL SUPPORTED (raw sample): {s}/{n} = {p:.1%}  (95% CI {lo:.1%}-{hi:.1%})")
    print("OVERALL verdicts:", breakdown(results))

    for era in ("RECENT", "OLDER"):
        sub = [r for r in results if r["era"] == era]
        s, n, p = rate(sub)
        lo, hi = wilson_ci(s, n)
        print(f"[{era}] SUPPORTED: {s}/{n} = {p:.1%} (CI {lo:.1%}-{hi:.1%}) | {breakdown(sub)}")

    # Per-predicate support (used for predicate-balanced AND volume-weighted rates)
    per_pred: dict[str, tuple[int, int, float]] = {}
    print("\n---- BY PREDICATE (combined) ----")
    for pred in sorted({r["predicate"] for r in results}):
        sub = [r for r in results if r["predicate"] == pred]
        s, n, pp = rate(sub)
        per_pred[pred] = (s, n, pp)
        print(f"  {pred:24s} {s}/{n} ({pp:.0%})")

    # Predicate-balanced: simple mean of per-predicate rates (matches prior audit framing)
    measured = [v[2] for v in per_pred.values() if v[1] > 0]
    bal = sum(measured) / len(measured) if measured else 0.0
    print(f"\nPREDICATE-BALANCED support (mean of per-predicate rates): {bal:.1%}")

    # Volume-weighted: weight each predicate's measured rate by its real frequency
    num = den = 0.0
    eff_sup = eff_n = 0.0
    for pred, (_s, npred, pp) in per_pred.items():
        if npred == 0 or pred not in PREDICATE_FREQ:
            continue
        w = PREDICATE_FREQ[pred]
        num += w * pp
        den += w
        # effective counts for a CI on the volume-weighted estimate
        eff_sup += w * pp
        eff_n += w
    vw = num / den if den else 0.0
    # CI: treat the volume-weighted rate as a proportion over an effective sample equal to
    # the raw judged n (conservative — we judged ~12/predicate, not thousands).
    _, n_total, _ = rate(results)
    lo_vw, hi_vw = wilson_ci(round(vw * n_total), n_total)
    print(
        f"VOLUME-WEIGHTED support (weighted by relations-table frequency): {vw:.1%} "
        f"(approx 95% CI {lo_vw:.1%}-{hi_vw:.1%}, n_eff={n_total})"
    )

    # Prior verdict cross-tab (where Flash and Qwen disagree)
    print("\n---- PRIOR (Flash, 1-snippet) vs NOW (Qwen, all-snippet) ----")
    flipped_to_sup = [r for r in results if r["prior_verdict"] != "SUPPORTED" and r["verdict"] == "SUPPORTED"]
    flipped_from_sup = [r for r in results if r["prior_verdict"] == "SUPPORTED" and r["verdict"] != "SUPPORTED"]
    print(f"flipped NON-SUPPORTED -> SUPPORTED: {len(flipped_to_sup)}")
    print(f"flipped SUPPORTED -> non-supported: {len(flipped_from_sup)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
