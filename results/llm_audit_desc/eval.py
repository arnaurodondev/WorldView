#!/usr/bin/env python3
"""Entity-description quality A/B: Qwen3-235B (prod) vs gpt-oss-20b/120b.

Focus = HALLUCINATION on obscure entities (the prod model invents biographies for
unknown persons/orgs, which poisons the KG). Judge = DeepSeek-V4-Flash scores each
description for (a) hallucination risk and (b) overall quality on a 1-5 scale.
READ-ONLY. Calls DeepInfra directly.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

KEY = os.environ["DEEPINFRA_API_KEY"]
URL = "https://api.deepinfra.com/v1/openai/chat/completions"

SYSTEM = """\
You are a financial knowledge-base writer for a professional market intelligence platform.
## Task
Write a concise, factual 2-3 sentence description of a financial or economic entity.
## Anti-hallucination rules
- State only well-established, publicly verifiable facts
- Never invent figures, founding dates, executive names, or addresses you are not certain about
- For obscure or ambiguous entities, describe the general category rather than guessing specifics
- For people, describe only their known public role; never speculate on personal history
Plain text only, exactly 2-3 sentences."""

# Mix of well-known + obscure/likely-unknown entities (obscure ones expose fabrication)
SAMPLE = [
    ("Qatar Investment Authority", "organization"),
    ("Megaspeed International", "organization"),  # obscure / likely unknown
    ("Jordan Klein", "person"),                   # obscure person
    ("Rafael Mattje", "person"),                  # obscure person
    ("Derek Yan", "person"),                      # obscure person (prod said 'footballer')
    ("Braidwell LP", "organization"),             # obscure fund
    ("Andrew Spicehandler", "person"),            # obscure person
    ("Gurgaon", "place"),
    ("American Industry", "unknown"),             # vague concept
    ("Culper Research", "organization"),          # niche short-seller
    ("EAA Partners", "organization"),             # obscure
    ("Lewis Howes", "person"),                    # non-finance person
]

ARMS = [
    ("Qwen/Qwen3-235B-A22B-Instruct-2507", None, "235b-prod"),
    ("openai/gpt-oss-20b", "low", "20b@low"),
    ("openai/gpt-oss-120b", "medium", "120b@medium"),
]
JUDGE = "deepseek-ai/DeepSeek-V4-Flash"


def call(model, system, user, reasoning, max_tokens=400):
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.0, "max_tokens": max_tokens}
    if reasoning is not None:
        body["reasoning_effort"] = reasoning
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
        return (resp["choices"][0]["message"].get("content") or "").strip(), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}", time.time() - t0


JUDGE_SYS = (
    "You are a strict fact-checking judge for a financial knowledge graph. Given an entity name, "
    "its type, and a generated description, score it. A FABRICATED fact (invented biography, made-up "
    "role, wrong identity) is the worst failure — it poisons the graph. For obscure/unknown entities, "
    "the CORRECT behaviour is to state the general category or admit limited public info, NOT to invent. "
    'Respond ONLY JSON: {"hallucination": <0=none,1=minor,2=severe>, "quality": <1-5>, "note": "<=12 words"}'
)


def judge(name, etype, desc):
    user = f"Entity: {name}\nType: {etype}\nDescription: {desc}"
    out, _ = call(JUDGE, JUDGE_SYS, user, None, 200)
    s, e = out.find("{"), out.rfind("}")
    try:
        return json.loads(out[s:e + 1])
    except Exception:  # noqa: BLE001
        return {"hallucination": None, "quality": None, "note": out[:60]}


def main():
    results = {}
    for model, reff, label in ARMS:
        descs = {}
        lats = []
        for name, etype in SAMPLE:
            user = f"{name} (entity_type: {etype})"
            d, dt = call(model, SYSTEM, user, reff)
            lats.append(dt)
            descs[name] = (etype, d)
        hall, qual, rows = [], [], []
        for name, (etype, d) in descs.items():
            if d.startswith("__ERR__"):
                rows.append({"name": name, "err": d[:80]})
                continue
            j = judge(name, etype, d)
            if j.get("hallucination") is not None:
                hall.append(j["hallucination"])
            if j.get("quality") is not None:
                qual.append(j["quality"])
            rows.append({"name": name, "desc": d[:160], "judge": j})
        results[label] = {
            "model": model, "reasoning": reff, "n": len(SAMPLE),
            "mean_hallucination": round(sum(hall) / len(hall), 2) if hall else None,
            "severe_hallucinations": sum(1 for h in hall if h == 2),
            "mean_quality": round(sum(qual) / len(qual), 2) if qual else None,
            "lat_p50": round(sorted(lats)[len(lats) // 2], 2),
            "rows": rows,
        }
        print(f"[desc] {label}: hallu={results[label]['mean_hallucination']} "
              f"severe={results[label]['severe_hallucinations']} qual={results[label]['mean_quality']} "
              f"p50={results[label]['lat_p50']}s")
    with open(os.path.join(os.path.dirname(__file__), "desc_results.json"), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
