"""Prototype + MEASURE a cheap write-time CO-MENTION ENTAILMENT CHECK for relations.

Context
-------
The trustworthy re-measurement
(``docs/audits/2026-06-20-stored-relation-quality-remeasurement.md``) found the
dominant relation defect is the extractor promoting a CO-MENTION (two entities
appearing in the same text) into an asserted relation. This is *semantic* and the
deterministic gate (``relation_validation.py``) cannot catch it — every co-mention
relation is structurally valid.

This script prototypes a CHEAP LLM entailment check that, given
``(subject, predicate, object, evidence_text)``, returns a binary
ASSERTED / NOT_ASSERTED verdict (does the evidence assert the relation with a
relation-bearing verb/phrase, vs mere adjacency?), then MEASURES how well it would
work against a strong-judge ground truth BEFORE any inline wiring.

Two phases
----------
1. ``--phase label`` : run the STRONG judge (Qwen3-235B + conventions, the audit's
   ground truth) over the stratified sample TSV -> writes a labelled JSON. This
   reconstructs the audit's ``/tmp/wv_remeasure_verdicts.json`` labelled set
   (SUPPORTED / CO_MENTION / WRONG_DIRECTION / WRONG_PREDICATE / UNSUPPORTED).
2. ``--phase eval``  : run the CHEAP entailment check (``--cheap-model``) over the
   same relations and compare its binary ASSERTED/NOT verdict to the ground-truth
   label. Reports precision/recall at catching co-mention/unsupported defects and —
   critically — the FALSE-POSITIVE rate (correctly-SUPPORTED relations the cheap
   check would wrongly kill).

Ground-truth mapping
--------------------
  should_pass := label == SUPPORTED
  should_fail := label in {CO_MENTION, UNSUPPORTED}
WRONG_DIRECTION / WRONG_PREDICATE are EXCLUDED from the precision/recall headline
(the entailment check is designed to catch co-mention/unsupported, not direction/
predicate errors) but are reported separately for completeness.

READ-ONLY on the DB (the TSV is produced by an external SELECT). Only calls DeepInfra.

Usage
-----
    source .venv312/bin/activate
    KEY=$(docker exec worldview-nlp-pipeline-article-consumer-0-1 \
            printenv NLP_PIPELINE_EXTRACTION_API_KEY)
    python scripts/eval/prototype_entailment_check.py --phase label \
        --key "$KEY" --tsv /tmp/wv_sample.tsv --labels /tmp/wv_labels.json
    python scripts/eval/prototype_entailment_check.py --phase eval \
        --key "$KEY" --tsv /tmp/wv_sample.tsv --labels /tmp/wv_labels.json \
        --cheap-model openai/gpt-oss-20b --out /tmp/wv_eval_gptoss20b.json
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import json
import sys
import threading
import time

import httpx

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
STRONG_JUDGE = "Qwen/Qwen3-235B-A22B-Instruct-2507"

# Per-1M-token DeepInfra list prices (USD), captured 2026-06-21. Used for cost estimate.
MODEL_PRICE_PER_M = {
    "openai/gpt-oss-20b": {"in": 0.04, "out": 0.16},
    "openai/gpt-oss-120b": {"in": 0.09, "out": 0.45},
    "Qwen/Qwen3-235B-A22B-Instruct-2507": {"in": 0.13, "out": 0.60},
}

# Direction conventions — VERBATIM from remeasure_stored_relation_quality.py so the
# strong-judge ground truth here is identical to the audit's labelled set.
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

# ── Strong-judge prompt (ground truth) — same 5-way scheme as the audit ──────────
STRONG_SYSTEM = (
    "You are a careful, fair knowledge-graph relation auditor. You are given a candidate "
    "triple (SUBJECT, PREDICATE, OBJECT), the CANONICAL CONVENTION for that predicate, and "
    "an evidence snippet from news/filings.\n\n"
    "A relation is SUPPORTED if the snippet asserts the triple under the stated CONVENTION "
    "with a relation-bearing verb or phrase. Apply the CONVENTION exactly.\n\n"
    "Be fair, not pedantic: consortium membership counts; apposition/titles count "
    "('Tim Cook, CEO of Apple' SUPPORTS Apple has_executive Tim Cook); for symmetric "
    "predicates (competes_with, partner_of) either order is fine; hedged verbs "
    "('agreed to','plans to') still count.\n\n"
    "Choose exactly ONE verdict:\n"
    '  "SUPPORTED"       = the snippet asserts SUBJECT-PREDICATE-OBJECT under the convention.\n'
    '  "CO_MENTION"      = both entities appear but NO relation of this kind is asserted.\n'
    '  "WRONG_DIRECTION" = the relation exists but SUBJECT/OBJECT are swapped vs convention.\n'
    '  "WRONG_PREDICATE" = a real relation exists but a DIFFERENT predicate fits, not this one.\n'
    '  "UNSUPPORTED"     = no support at all (wrong entity, hallucinated, evidence unrelated).\n\n'
    "Output STRICT JSON only:\n"
    '{"verdict": "...", "confidence": 0.0-1.0, "reason": "<=18 words"}'
)


def strong_user(subj: str, pred: str, obj: str, ev: str) -> str:
    conv = CONVENTIONS.get(pred, "(no convention recorded — judge by plain meaning)")
    return (
        f"SUBJECT: {subj}\nPREDICATE: {pred}\nOBJECT: {obj}\n"
        f"CONVENTION for '{pred}': {conv}\n\nEVIDENCE: {ev}\n\n"
        f"Does the evidence assert SUBJECT -{pred}-> OBJECT under the convention? "
        "Return the strict JSON verdict."
    )


# ── CHEAP entailment-check prompt — BINARY, tuned to minimise FALSE POSITIVES ────
# The default leans towards ASSERTED (keep the relation) on any doubt, because false
# positives (killing a good relation) are the critical risk.
CHEAP_SYSTEM = (
    "You are a strict entailment checker for a knowledge graph. You receive a candidate "
    "relation triple (SUBJECT, PREDICATE, OBJECT), a one-line MEANING of the predicate, and "
    "an EVIDENCE snippet. Your ONLY job: does the evidence ASSERT this relation with a "
    "relation-bearing verb or phrase that connects THIS subject to THIS object — or do the "
    "two entities merely CO-OCCUR (listed together, adjacent, both mentioned) without the "
    "relation being stated?\n\n"
    "Rules:\n"
    "- ASSERTED requires a verb/phrase that actually expresses the relation between the two "
    "named entities (e.g. 'X acquired Y', 'X, a supplier to Y', 'X competes with Y', "
    "'X, CEO of Y'). Apposition and titles count. Hedged verbs ('agreed to','plans to') count. "
    "For symmetric predicates (competes_with, partner_of) either order is fine.\n"
    "- NOT_ASSERTED means the snippet only co-mentions the entities, or talks about a "
    "DIFFERENT relation, or does not connect them at all.\n"
    "- CRITICAL: when in ANY doubt, answer ASSERTED. Only answer NOT_ASSERTED when you are "
    "confident the relation is NOT stated. Do not penalise direction or a slightly-off "
    "predicate — if SOME relation-bearing language links the two entities, answer ASSERTED.\n\n"
    "Output STRICT JSON only:\n"
    '{"asserted": true|false, "confidence": 0.0-1.0, "reason": "<=14 words"}'
)

# Short predicate meanings for the cheap check (no full direction convention — keep it cheap).
CHEAP_MEANING: dict[str, str] = {k: v.split(".")[0] for k, v in CONVENTIONS.items()}


def cheap_user(subj: str, pred: str, obj: str, ev: str) -> str:
    meaning = CHEAP_MEANING.get(pred, pred.replace("_", " "))
    return (
        f"SUBJECT: {subj}\nPREDICATE: {pred} ({meaning})\nOBJECT: {obj}\n"
        f"EVIDENCE: {ev}\n\n"
        "Does the EVIDENCE assert this relation between SUBJECT and OBJECT, or do they only "
        "co-occur? Return the strict JSON."
    )


def _post(
    client: httpx.Client, key: str, model: str, system: str, user: str, reasoning: str
) -> tuple[dict | None, int, int]:
    """POST one chat completion with 429 backoff. Returns (parsed_json, in_tok, out_tok)."""
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 400,
        "reasoning_effort": reasoning,  # both are reasoning models: empty content without this
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
            body = r.json()
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            in_tok = int(usage.get("prompt_tokens", 0))
            out_tok = int(usage.get("completion_tokens", 0))
            if not content or not content.strip():
                raise ValueError("empty content")
            return json.loads(content), in_tok, out_tok
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError):
            if attempt == 6:
                return None, 0, 0
            time.sleep(backoff)
            backoff = min(backoff * 2, 40)
    return None, 0, 0


def load_rows(tsv_path: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(tsv_path, encoding="utf-8") as f:
        for rec in csv.reader(f, delimiter="\t"):
            if len(rec) < 6:
                continue
            rows.append(
                {
                    "relation_id": rec[0],
                    "era": rec[1],
                    "subject_name": rec[2],
                    "predicate": rec[3],
                    "object_name": rec[4],
                    "evidence_text": rec[5],
                    "subject_type": rec[6] if len(rec) > 6 else "",
                    "object_type": rec[7] if len(rec) > 7 else "",
                }
            )
    return rows


def _run_pool(rows: list[dict], fn, workers: int) -> list[dict]:
    thread_local = threading.local()
    done = [0]
    lock = threading.Lock()

    def worker(idx_row: tuple[int, dict]) -> tuple[int, dict]:
        idx, row = idx_row
        client = getattr(thread_local, "client", None)
        if client is None:
            client = httpx.Client()
            thread_local.client = client
        out = fn(client, row)
        with lock:
            done[0] += 1
            if done[0] % 25 == 0:
                print(f"  {done[0]}/{len(rows)}", file=sys.stderr)
        return idx, out

    by_idx: dict[int, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, res in pool.map(worker, list(enumerate(rows))):
            by_idx[idx] = res
    return [by_idx[i] for i in range(len(rows))]


def phase_label(args: argparse.Namespace) -> int:
    rows = load_rows(args.tsv)
    print(f"labelling {len(rows)} relations with strong judge {STRONG_JUDGE}", file=sys.stderr)

    def fn(client: httpx.Client, row: dict) -> dict:
        parsed, _, _ = _post(
            client,
            args.key,
            STRONG_JUDGE,
            STRONG_SYSTEM,
            strong_user(row["subject_name"], row["predicate"], row["object_name"], row["evidence_text"]),
            reasoning="low",
        )
        verdict = "JUDGE_ERROR" if parsed is None else str(parsed.get("verdict", "PARSE_ERROR")).upper()
        return {
            **row,
            "label": verdict,
            "label_confidence": None if parsed is None else parsed.get("confidence"),
            "label_reason": "" if parsed is None else parsed.get("reason", ""),
        }

    results = _run_pool(rows, fn, args.workers)
    with open(args.labels, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    counts = collections.Counter(r["label"] for r in results)
    print("\nLABEL DISTRIBUTION:", dict(counts))
    valid = [r for r in results if r["label"] not in ("JUDGE_ERROR", "PARSE_ERROR")]
    sup = sum(1 for r in valid if r["label"] == "SUPPORTED")
    print(f"SUPPORTED: {sup}/{len(valid)} = {sup / len(valid):.1%}" if valid else "no valid labels")
    return 0


def phase_eval(args: argparse.Namespace) -> int:
    with open(args.labels, encoding="utf-8") as f:
        labelled = json.load(f)
    model = args.cheap_model
    reasoning = args.reasoning
    print(f"evaluating cheap check {model} (reasoning={reasoning}) over {len(labelled)} relations", file=sys.stderr)

    tok_in = [0]
    tok_out = [0]
    tok_lock = threading.Lock()

    def fn(client: httpx.Client, row: dict) -> dict:
        parsed, it, ot = _post(
            client,
            args.key,
            model,
            CHEAP_SYSTEM,
            cheap_user(row["subject_name"], row["predicate"], row["object_name"], row["evidence_text"]),
            reasoning=reasoning,
        )
        with tok_lock:
            tok_in[0] += it
            tok_out[0] += ot
        if parsed is None:
            check = "ERROR"
        else:
            asserted = parsed.get("asserted")
            check = "ASSERTED" if asserted is True else "NOT_ASSERTED" if asserted is False else "PARSE_ERROR"
        return {
            **row,
            "check": check,
            "check_confidence": None if parsed is None else parsed.get("confidence"),
            "check_reason": "" if parsed is None else parsed.get("reason", ""),
        }

    results = _run_pool(labelled, fn, args.workers)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    report(results, model, tok_in[0], tok_out[0])
    return 0


def report(results: list[dict], model: str, tok_in: int, tok_out: int) -> None:
    # Keep only rows where BOTH the ground-truth label and the cheap check are valid.
    usable = [
        r
        for r in results
        if r["label"] not in ("JUDGE_ERROR", "PARSE_ERROR") and r["check"] in ("ASSERTED", "NOT_ASSERTED")
    ]
    n_err = len(results) - len(usable)

    # Headline scope: SUPPORTED (should_pass) vs CO_MENTION/UNSUPPORTED (should_fail).
    should_pass = [r for r in usable if r["label"] == "SUPPORTED"]
    should_fail = [r for r in usable if r["label"] in ("CO_MENTION", "UNSUPPORTED")]
    other = [r for r in usable if r["label"] in ("WRONG_DIRECTION", "WRONG_PREDICATE")]

    # Defect-catching confusion matrix (positive class = "defect caught" = NOT_ASSERTED).
    tp = sum(1 for r in should_fail if r["check"] == "NOT_ASSERTED")  # caught a real defect
    fn_ = sum(1 for r in should_fail if r["check"] == "ASSERTED")  # missed a defect
    fp = sum(1 for r in should_pass if r["check"] == "NOT_ASSERTED")  # KILLED A GOOD RELATION
    tn = sum(1 for r in should_pass if r["check"] == "ASSERTED")  # correctly kept good relation

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn_) if (tp + fn_) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0  # the critical risk
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    price = MODEL_PRICE_PER_M.get(model, {"in": 0.0, "out": 0.0})
    n_calls = len(usable)
    avg_in = tok_in / n_calls if n_calls else 0.0
    avg_out = tok_out / n_calls if n_calls else 0.0
    cost_per_call = (avg_in * price["in"] + avg_out * price["out"]) / 1_000_000

    print("\n" + "=" * 64)
    print(f"CHEAP ENTAILMENT CHECK — {model}")
    print("=" * 64)
    print(f"usable rows: {len(usable)} (errors excluded: {n_err})")
    print(f"  should_pass (SUPPORTED):             {len(should_pass)}")
    print(f"  should_fail (CO_MENTION+UNSUPPORTED): {len(should_fail)}")
    print(f"  other (WRONG_DIR/WRONG_PRED):        {len(other)} (excluded from headline)")
    print("\n-- Defect-catching (positive = NOT_ASSERTED = 'kill the relation') --")
    print(f"  TP (defect correctly caught):      {tp}")
    print(f"  FN (defect missed, kept):          {fn_}")
    print(f"  FP (GOOD relation wrongly killed): {fp}   <-- critical risk")
    print(f"  TN (good relation kept):           {tn}")
    print(f"\n  PRECISION (caught are real defects): {precision:.1%}")
    print(f"  RECALL    (defects caught):          {recall:.1%}")
    print(f"  F1:                                  {f1:.1%}")
    print(f"  FALSE-POSITIVE RATE (good killed):   {fpr:.1%}   <-- MUST be low")

    if other:
        wd_kill = sum(1 for r in other if r["check"] == "NOT_ASSERTED")
        print(
            f"\n  on WRONG_DIR/WRONG_PRED: {wd_kill}/{len(other)} killed "
            f"(bonus catches — defects, but not the target class)"
        )

    print(f"\n-- Cost (DeepInfra list price in={price['in']}/M out={price['out']}/M) --")
    print(f"  avg tokens/call: in={avg_in:.0f} out={avg_out:.0f}")
    print(f"  cost per relation-check: ${cost_per_call:.6f}/call (${cost_per_call * 1000:.4f} per 1k)")
    for rpa in (1, 2, 5):
        print(f"  est. cost/article @ {rpa} risky-relation checks: ${cost_per_call * rpa:.6f}")

    # Per-predicate FP/recall on the HIGH-RISK target predicates.
    risky = ("competes_with", "regulates", "produces", "partner_of", "supplier_of")
    print("\n-- HIGH-RISK predicates (the inline target set) --")
    print(f"  {'predicate':18s} {'pass':>4} {'fail':>4} {'recall':>7} {'FP':>4} {'FPR':>6}")
    for pred in risky:
        sp = [r for r in should_pass if r["predicate"] == pred]
        sf = [r for r in should_fail if r["predicate"] == pred]
        r_tp = sum(1 for r in sf if r["check"] == "NOT_ASSERTED")
        r_fp = sum(1 for r in sp if r["check"] == "NOT_ASSERTED")
        rec = r_tp / len(sf) if sf else 0.0
        pfpr = r_fp / len(sp) if sp else 0.0
        print(f"  {pred:18s} {len(sp):>4} {len(sf):>4} {rec:>6.0%} {r_fp:>4} {pfpr:>5.0%}")

    # Restrict the whole confusion matrix to ONLY the high-risk predicates (inline scope).
    rp = [r for r in should_pass if r["predicate"] in risky]
    rf = [r for r in should_fail if r["predicate"] in risky]
    rtp = sum(1 for r in rf if r["check"] == "NOT_ASSERTED")
    rfn = sum(1 for r in rf if r["check"] == "ASSERTED")
    rfp = sum(1 for r in rp if r["check"] == "NOT_ASSERTED")
    rtn = sum(1 for r in rp if r["check"] == "ASSERTED")
    rprec = rtp / (rtp + rfp) if (rtp + rfp) else 0.0
    rrec = rtp / (rtp + rfn) if (rtp + rfn) else 0.0
    rfpr = rfp / (rfp + rtn) if (rfp + rtn) else 0.0
    print("\n-- HIGH-RISK predicates ONLY (inline-scope confusion matrix) --")
    print(f"  TP={rtp} FN={rfn} FP={rfp} TN={rtn}")
    print(f"  PRECISION={rprec:.1%}  RECALL={rrec:.1%}  FALSE-POSITIVE-RATE={rfpr:.1%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("label", "eval"), required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--tsv", required=True)
    ap.add_argument("--labels", required=True, help="ground-truth labels JSON (written by label, read by eval)")
    ap.add_argument("--out", help="eval output JSON (required for --phase eval)")
    ap.add_argument("--cheap-model", default=STRONG_JUDGE)
    ap.add_argument("--reasoning", default="low")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.phase == "label":
        return phase_label(args)
    if not args.out:
        ap.error("--out is required for --phase eval")
    return phase_eval(args)


if __name__ == "__main__":
    raise SystemExit(main())
