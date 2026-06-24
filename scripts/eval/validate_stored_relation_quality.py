"""Validate the SEMANTIC quality of stored knowledge-graph relations.

Goal
----
A benchmark A/B claimed the current extraction model (openai/gpt-oss-120b@medium)
produces near-perfect relations (judge precision 5.0/5, 0 fabrication). This script
checks whether the relations ACTUALLY STORED in the production graph are that good,
by re-judging a stratified sample of real `relations` + `relation_evidence` rows with
an INDEPENDENT budget judge (deepseek-ai/DeepSeek-V4-Flash on DeepInfra).

The graph is a MIX of two extraction-model eras. The extraction model was switched to
openai/gpt-oss-120b around 2026-06-16 (PLAN-0111); before that it was
Qwen/Qwen3-235B-A22B-Instruct-2507. We segment by `relations.created_at`:
  * RECENT cohort  = created_at >= 2026-06-16  (gpt-oss era == current implementation)
  * OLDER  cohort  = created_at <  2026-06-16  (Qwen era)
The headline answer is the RECENT cohort.

Pipeline
--------
1. (PHASE=sample) Run a stratified SQL sample via `docker exec ... psql`, writing a TSV
   to a file inside the postgres container, then `docker cp`-style cat it to the host.
2. (PHASE=judge)  Read the TSV, call DeepInfra per row (temperature 0, retry/backoff on
   429), classify SUPPORTED / CO_MENTION / WRONG_DIRECTION / WRONG_PREDICATE / UNSUPPORTED.
3. Aggregate: SUPPORTED rate overall, by era, by predicate; flag worst predicates; dump
   raw verdicts to JSON for the report.

READ-ONLY on the database (SELECT only). Writes only to local files under /tmp and the
path given by --out.

Usage
-----
    source .venv312/bin/activate
    KEY=$(docker exec worldview-nlp-pipeline-article-consumer-0-1 \
            printenv NLP_PIPELINE_EXTRACTION_API_KEY)
    python scripts/eval/validate_stored_relation_quality.py \
        --key "$KEY" --tsv /tmp/relsample.tsv --out /tmp/verdicts.json
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

JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"

SYSTEM_PROMPT = (
    "You are a strict knowledge-graph relation auditor. You are given a candidate "
    "triple (SUBJECT, PREDICATE, OBJECT) and the EVIDENCE sentence(s) that supposedly "
    "support it. Decide whether the evidence text DIRECTLY ASSERTS that exact relation "
    "with a relation-bearing verb or phrase (not merely mentions both entities).\n\n"
    "Classify into exactly one verdict:\n"
    '  "SUPPORTED"        = the evidence directly asserts SUBJECT-PREDICATE-OBJECT.\n'
    '  "CO_MENTION"       = both entities appear but NO relation of this kind is '
    "asserted between them (they are merely listed/adjacent/mentioned in the same text).\n"
    '  "WRONG_DIRECTION"  = the relation exists in the evidence but SUBJECT and OBJECT '
    "are swapped (e.g. evidence says A acquired B but triple says B acquired_by-> wrong way).\n"
    '  "WRONG_PREDICATE"  = some real relation exists between the two entities, but a '
    "DIFFERENT predicate fits the evidence, not the stated one.\n"
    '  "UNSUPPORTED"      = the evidence does not support the triple at all (wrong '
    "entity, hallucinated, or evidence is unrelated).\n\n"
    "Be skeptical. A bare co-occurrence is NOT support. Output STRICT JSON only, no prose:\n"
    '{"verdict": "...", "confidence": 0.0-1.0, "reason": "<=20 words"}'
)

PREDICATE_HINTS = {
    "competes_with": "SUBJECT is a competitor/rival of OBJECT.",
    "partner_of": "SUBJECT has a partnership/alliance/collaboration with OBJECT.",
    "supplier_of": "SUBJECT supplies goods/components/services TO OBJECT (SUBJECT is the supplier).",
    "operates_in_country": "SUBJECT (a company) operates/has operations in OBJECT (a country).",
    "has_executive": "OBJECT is an executive/officer of SUBJECT (the company).",
    "listed_on": "SUBJECT (a company/security) is listed/trades on OBJECT (a stock exchange).",
    "subsidiary_of": "SUBJECT is a subsidiary/unit owned by OBJECT (the parent).",
    "acquired_by": "SUBJECT was acquired/bought by OBJECT (OBJECT is the acquirer).",
    "produces": "SUBJECT makes/manufactures/produces OBJECT (a product/good).",
    "headquartered_in": "SUBJECT is headquartered in OBJECT (a place).",
    "investment_in": "SUBJECT invests/holds an investment in OBJECT.",
    "owns_stake_in": "SUBJECT owns an equity stake in OBJECT.",
    "is_in_sector": "SUBJECT belongs to OBJECT (a market sector).",
    "is_in_industry": "SUBJECT belongs to OBJECT (an industry).",
    "board_member_of": "SUBJECT is a board member of OBJECT.",
    "regulates": "SUBJECT (a regulator) regulates OBJECT.",
}


def build_user_prompt(subj: str, pred: str, obj: str, evidence: str) -> str:
    hint = PREDICATE_HINTS.get(pred, "")
    hint_line = f"PREDICATE MEANING: {hint}\n" if hint else ""
    return (
        f"SUBJECT: {subj}\n"
        f"PREDICATE: {pred}\n"
        f"OBJECT: {obj}\n"
        f"{hint_line}"
        f"EVIDENCE: {evidence}\n\n"
        "Does the EVIDENCE directly assert SUBJECT -{predicate}-> OBJECT? "
        "Return the strict JSON verdict.".replace("{predicate}", pred)
    )


def judge_one(client: httpx.Client, key: str, row: dict[str, str]) -> dict:
    payload = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    row["subject_name"], row["predicate"], row["object_name"], row["evidence_text"]
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    backoff = 2.0
    for attempt in range(6):
        try:
            r = client.post(DEEPINFRA_URL, json=payload, headers=headers, timeout=60.0)
            if r.status_code == 429:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return {
                "verdict": str(parsed.get("verdict", "PARSE_ERROR")).upper(),
                "confidence": parsed.get("confidence"),
                "reason": parsed.get("reason", ""),
            }
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            if attempt == 5:
                return {"verdict": "JUDGE_ERROR", "confidence": None, "reason": str(exc)[:120]}
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    return {"verdict": "JUDGE_ERROR", "confidence": None, "reason": "exhausted retries"}


def load_rows(tsv_path: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for rec in reader:
            if len(rec) < 6:
                continue
            rel_id, era, subj, pred, obj, evidence = rec[0], rec[1], rec[2], rec[3], rec[4], rec[5]
            rows.append(
                {
                    "relation_id": rel_id,
                    "era": era,
                    "subject_name": subj,
                    "predicate": pred,
                    "object_name": obj,
                    "evidence_text": evidence,
                }
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--tsv", required=True, help="TSV of relation_id\\tera\\tsubj\\tpred\\tobj\\tevidence")
    ap.add_argument("--out", required=True, help="output JSON path for verdicts")
    ap.add_argument("--workers", type=int, default=8, help="concurrent judge calls")
    args = ap.parse_args()

    rows = load_rows(args.tsv)
    print(f"loaded {len(rows)} sample rows", file=sys.stderr)

    # Each worker thread gets its own httpx.Client (Client is not safe to share across
    # threads). DeepSeek-V4-Flash is ~15 s/call serially → parallelise to stay tractable;
    # the per-call 429 backoff (judge_one) absorbs DeepInfra throttling under concurrency.
    thread_local = threading.local()
    done = [0]
    lock = threading.Lock()

    def worker(idx_row: tuple[int, dict[str, str]]) -> tuple[int, dict]:
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
        return idx_row[0], {**row, **verdict}

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

    print("\n================ AGGREGATE ================")
    s, n, p = rate(results)
    print(f"OVERALL SUPPORTED: {s}/{n} = {p:.1%}")
    print("OVERALL verdicts:", breakdown(results))

    for era in ("RECENT", "OLDER"):
        sub = [r for r in results if r["era"] == era]
        s, n, p = rate(sub)
        print(f"\n[{era}] SUPPORTED: {s}/{n} = {p:.1%}  | verdicts: {breakdown(sub)}")

    print("\n---- BY PREDICATE (recent | older | combined) ----")
    preds = sorted({r["predicate"] for r in results})
    for pred in preds:
        line = [f"{pred:24s}"]
        for era in ("RECENT", "OLDER", None):
            sub = [r for r in results if r["predicate"] == pred and (era is None or r["era"] == era)]
            s, n, p = rate(sub)
            tag = era or "ALL"
            line.append(f"{tag}={s}/{n}({p:.0%})" if n else f"{tag}=-")
        print("  ".join(line))

    print("\n---- DEFECT EXAMPLES (non-SUPPORTED) ----")
    for r in results:
        if r["verdict"] not in ("SUPPORTED", "JUDGE_ERROR", "PARSE_ERROR"):
            print(
                f"[{r['era']}][{r['verdict']}] {r['subject_name']} -{r['predicate']}-> "
                f"{r['object_name']}\n   ev: {r['evidence_text'][:200]}\n   why: {r['reason']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
