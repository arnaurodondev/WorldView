#!/usr/bin/env python3
"""Description eval — Part 2 (gemini quality) + Part 3 (news-grounding A/B).

Reuses the EXACT production system prompt + _build_prompt + DeepSeek-V4-Flash judge
from results/kg_desc_eval/eval.py. Adds:
  - gemini arm: google/gemini-3.1-flash-lite, no-context (same prod prompt) — Part 2.
  - news-grounded arms: the same prompt with a NEWS CONTEXT block injected before the
    instruction (235b+news, gemini+news) — Part 3 A/B vs the no-context baselines.

READ-ONLY. DeepInfra API only. No production change.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import defaultdict

KEY = os.environ["DEEPINFRA_API_KEY"]
URL = "https://api.deepinfra.com/v1/openai/chat/completions"
HERE = os.path.dirname(__file__)

# Import the verbatim prod prompt + helpers from the prior harness.
import sys
sys.path.insert(0, os.path.join(HERE, "..", "kg_desc_eval"))
from eval import SYSTEM_PROMPT, build_prompt, JUDGE_SYS, JUDGE  # noqa: E402

# Arms: (model, reasoning_effort, label, use_news). max_tokens 256 = prod.
ARMS = [
    ("Qwen/Qwen3-235B-A22B-Instruct-2507", None, "235b", False),       # baseline (re-run subset)
    ("google/gemini-3.1-flash-lite", None, "gemini", False),           # Part 2
    ("Qwen/Qwen3-235B-A22B-Instruct-2507", None, "235b+news", True),   # Part 3
    ("google/gemini-3.1-flash-lite", None, "gemini+news", True),       # Part 3
]
RUNS_OBSCURE = 2
RUNS_WELLKNOWN = 1


def call(model, system, user, reasoning, max_tokens=256, temperature=0.3):
    body = {"model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": max_tokens}
    if reasoning is not None:
        body["reasoning_effort"] = reasoning
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.load(r)
        msg = resp["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
        return content, time.time() - t0, resp.get("usage", {})
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}", time.time() - t0, {}


def build_grounded_prompt(name, etype, hints, snippets):
    """No-context prod prompt + a NEWS CONTEXT block (Part 3 plumbing prototype)."""
    base = build_prompt(name, etype, hints)
    if not snippets:
        # Grounded-but-no-news: tell the model there is no corroborating news.
        ctx = ("\n\nNEWS CONTEXT: No corroborating news mentions were found for this entity. "
               "Describe only the general category; do NOT invent specifics.")
    else:
        joined = "\n".join(f"- {s}" for s in snippets)
        ctx = ("\n\nNEWS CONTEXT (verbatim snippets from articles where this entity was mentioned; "
               "ground your description in these facts and do not contradict or go beyond them):\n" + joined)
    return base + ctx


def judge(name, etype, hints, desc):
    hints_str = "; ".join(f"{k}={v}" for k, v in hints.items() if v) or "(none)"
    user = (f"INPUT CONTEXT given to the writer:\n  name: {name}\n  entity_type: {etype}\n"
            f"  hints: {hints_str}\n\nGENERATED description:\n{desc}")
    out, _, _ = call(JUDGE, JUDGE_SYS, user, None, max_tokens=300, temperature=0.0)
    s, e = out.find("{"), out.rfind("}")
    try:
        return json.loads(out[s:e + 1])
    except Exception:  # noqa: BLE001
        return {"fabricated_claims": None, "hallucination": None, "grounding": None,
                "accuracy": None, "completeness": None, "note": out[:60]}


def main():
    sample = json.load(open(os.path.join(HERE, "sample_raw.json")))
    news = json.load(open(os.path.join(HERE, "news_context.json")))
    per_arm = {label: defaultdict(list) for _, _, label, _ in ARMS}
    rows = []
    total_calls = 0

    for ent in sample:
        name, etype, stratum = ent["canonical_name"], ent["entity_type"], ent["stratum"]
        hints = {k: ent.get(k) for k in ("ticker", "exchange", "isin") if ent.get(k)}
        snippets = news.get(name, [])
        n_runs = RUNS_OBSCURE if stratum == "obscure" else RUNS_WELLKNOWN

        for model, reff, label, use_news in ARMS:
            # Skip news arms on well-known (no-context already perfect; saves budget).
            if use_news and stratum == "well_known":
                continue
            user = build_grounded_prompt(name, etype, hints, snippets) if use_news else build_prompt(name, etype, hints)
            for run_i in range(n_runs):
                d, dt, usage = call(model, SYSTEM_PROMPT, user, reff)
                total_calls += 1
                if d.startswith("__ERR__"):
                    rows.append({"name": name, "type": etype, "stratum": stratum,
                                 "arm": label, "run": run_i, "err": d[:120]})
                    print(f"[{label:12}] ERR {name[:24]}: {d[:80]}")
                    continue
                j = judge(name, etype, hints, d)
                total_calls += 1
                rec = {"name": name, "type": etype, "stratum": stratum, "arm": label, "run": run_i,
                       "has_news": bool(snippets), "latency_s": round(dt, 2),
                       "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
                       "desc": d, "judge": j}
                rows.append(rec)
                for m in ("fabricated_claims", "hallucination", "grounding", "accuracy", "completeness"):
                    v = j.get(m)
                    if v is not None:
                        per_arm[label][(stratum, m)].append(v)
                        per_arm[label][("ALL", m)].append(v)
                        if etype == "person" and stratum == "obscure":
                            per_arm[label][("obscure_person", m)].append(v)
                per_arm[label][("ALL", "lat")].append(dt)
                if usage.get("prompt_tokens"):
                    per_arm[label][("ALL", "tin")].append(usage["prompt_tokens"])
                    per_arm[label][("ALL", "tout")].append(usage.get("completion_tokens", 0))
                print(f"[{label:12}] {stratum:10} {etype[:4]} {name[:24]:24} news={int(bool(snippets))} "
                      f"fab={j.get('fabricated_claims')} hal={j.get('hallucination')} grnd={j.get('grounding')} t={dt:.1f}s")

    def agg(label, stratum, m):
        vals = per_arm[label].get((stratum, m), [])
        return round(sum(vals) / len(vals), 2) if vals else None

    summary = {}
    for _, _, label, _ in ARMS:
        summary[label] = {}
        for stratum in ("ALL", "well_known", "obscure", "obscure_person"):
            hv = per_arm[label].get((stratum, "hallucination"), [])
            summary[label][stratum] = {
                "n": len(hv),
                "fab": agg(label, stratum, "fabricated_claims"),
                "hallu": agg(label, stratum, "hallucination"),
                "severe": sum(1 for h in hv if h == 2),
                "grounding": agg(label, stratum, "grounding"),
                "accuracy": agg(label, stratum, "accuracy"),
                "completeness": agg(label, stratum, "completeness"),
            }
        tin = per_arm[label].get(("ALL", "tin"), [])
        tout = per_arm[label].get(("ALL", "tout"), [])
        summary[label]["mean_tokens_in"] = round(sum(tin) / len(tin), 1) if tin else None
        summary[label]["mean_tokens_out"] = round(sum(tout) / len(tout), 1) if tout else None

    out = {"summary": summary, "rows": rows, "total_api_calls": total_calls}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=2)
    print("\n===== SUMMARY =====")
    print(json.dumps(summary, indent=2))
    print(f"\ntotal api calls (gen+judge): {total_calls}")


if __name__ == "__main__":
    main()
