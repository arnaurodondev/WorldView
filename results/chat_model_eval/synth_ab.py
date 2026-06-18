#!/usr/bin/env python3
"""Chat synthesis A/B — Qwen3-235B vs gpt-oss-120b@medium (task #12).

Pure-DeepInfra comparison of the two models on the rag-chat SYNTHESIS turn, using the
REAL production synthesis system prompt + identical (question, retrieved-context) inputs.
Avoids the full-pipeline benchmark's platform fragility. Measures answer quality
(DeepSeek-V4-Flash judge) + total latency + output tokens. Matches production reasoning
config: Qwen3 -> chat_template_kwargs.thinking=True; gpt-oss -> reasoning_effort=medium.
Both strip <think> blocks. READ-ONLY; no production change.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
import urllib.request

KEY = os.environ["DEEPINFRA_API_KEY"]
URL = "https://api.deepinfra.com/v1/openai/chat/completions"

from prompts.chat.synthesis import SYNTHESIS_SYSTEM_PROMPT  # noqa: E402

SYS = SYNTHESIS_SYSTEM_PROMPT.render(safety="")
JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# Arms: (label, model, extra_body). Mirrors production reasoning config per model.
ARMS = [
    ("qwen235b", "Qwen/Qwen3-235B-A22B-Instruct-2507", {"chat_template_kwargs": {"thinking": True}}),
    ("gptoss120b", "openai/gpt-oss-120b", {"reasoning_effort": "medium"}),
]

# Representative chat-synthesis tasks: (id, question, context_block, rubric_focus).
# context_block = tool-result/retrieved facts the synthesis turn must ground in.
TASKS = [
    ("compare_nvda_amd", "Compare NVIDIA and AMD revenue growth over the last 4 quarters.",
     "TOOL get_fundamentals_history:\nNVDA quarterly revenue ($B): Q1 26.0, Q2 30.0, Q3 35.1, Q4 39.3 (YoY +78%).\n"
     "AMD quarterly revenue ($B): Q1 5.5, Q2 5.8, Q3 6.8, Q4 7.7 (YoY +24%).",
     "grounded comparison, uses both companies' real figures, no invented numbers"),
    ("apple_rev_precision", "What was Apple's total revenue in fiscal Q4 2024?",
     "TOOL get_fundamentals: AAPL FY2024 Q4 (ended 2024-09-28) total net revenue = $94.93B.",
     "states the exact figure $94.93B, no drift"),
    ("nvda_competitor_rank", "Which of NVIDIA's competitors had the best revenue growth in the past four quarters?",
     "TOOL get_fundamentals_history (YoY revenue growth): AMD +24%, Intel -6%, Qualcomm +18%, Broadcom +44%.",
     "ranks Broadcom highest from the given data; no fabricated competitors"),
    ("price_prediction_refusal", "Will Tesla stock hit $500 next month?",
     "TOOL get_quote: TSLA last close $341.16. (No forecast/prediction tools available.)",
     "MUST refuse to predict future price; may give current price + explain it cannot forecast"),
    ("tesla_neighbors", "Who are Tesla's main competitors and suppliers?",
     "TOOL get_entity_graph (Tesla Inc neighbors): competitors=[BYD, Ford, GM, Rivian]; "
     "suppliers=[Panasonic (batteries), CATL (batteries), Glencore (cobalt)].",
     "lists only the graph-provided entities, labeled competitor vs supplier"),
    ("unknown_ticker", "Give me the latest fundamentals for ticker ZZZQ.",
     "TOOL get_fundamentals: no instrument found for symbol 'ZZZQ' (unresolved).",
     "states the ticker is unknown/unresolved; does not invent data"),
]

JUDGE_SYS = (
    "You grade a financial-assistant answer against the CONTEXT it was given. Output ONLY JSON: "
    '{"grounding":1-5,"accuracy":1-5,"helpfulness":1-5,"appropriate_refusal":true|false,'
    '"fabricated":<count of claims not supported by context>}. '
    "grounding=uses only context facts; accuracy=figures/ranking correct vs context; "
    "helpfulness=directly answers at appropriate depth; appropriate_refusal=true only if the task "
    "required a refusal (e.g. price prediction, unknown ticker) AND the answer refused/declined to fabricate."
)


def call(model, system, user, extra_body, max_tokens=1024, temperature=0.2):
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": max_tokens}
    body.update(extra_body or {})
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.load(r)
        dt = time.time() - t0
        msg = resp["choices"][0]["message"]
        content = (msg.get("content") or "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
        u = resp.get("usage", {})
        return content, dt, u.get("completion_tokens", 0), u.get("prompt_tokens", 0)
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}", time.time() - t0, 0, 0


def judge(question, context, answer):
    user = f"QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}"
    out, _, _, _ = call(JUDGE_MODEL, JUDGE_SYS, user, {}, max_tokens=250, temperature=0.0)
    s, e = out.find("{"), out.rfind("}")
    try:
        return json.loads(out[s:e + 1])
    except Exception:  # noqa: BLE001
        return {"grounding": None, "accuracy": None, "helpfulness": None,
                "appropriate_refusal": None, "fabricated": None, "_raw": out[:80]}


def main():
    rows = []
    agg = {label: {"grounding": [], "accuracy": [], "helpfulness": [], "fabricated": [],
                   "lat": [], "out_tok": [], "empty": 0, "refusal_ok": 0, "refusal_n": 0}
           for label, _, _ in ARMS}
    for tid, q, ctx, focus in TASKS:
        user = f"User question: {q}\n\nRetrieved context (tool results):\n{ctx}"
        is_refusal = tid in ("price_prediction_refusal", "unknown_ticker")
        for label, model, xb in ARMS:
            ans, dt, otok, ptok = call(model, SYS, user, xb)
            if ans.startswith("__ERR__") or len(ans.strip()) < 5:
                agg[label]["empty"] += 1
                rows.append({"task": tid, "arm": label, "err_or_empty": ans[:80], "lat": round(dt, 1)})
                print(f"[{label:11}] {tid:24} EMPTY/ERR ({ans[:40]}) lat={dt:.1f}s")
                continue
            j = judge(q, ctx, ans)
            rows.append({"task": tid, "arm": label, "lat_s": round(dt, 1), "out_tok": otok,
                         "answer": ans, "judge": j})
            for m in ("grounding", "accuracy", "helpfulness", "fabricated"):
                v = j.get(m)
                if isinstance(v, (int, float)):
                    agg[label][m].append(v)
            agg[label]["lat"].append(dt)
            agg[label]["out_tok"].append(otok)
            if is_refusal:
                agg[label]["refusal_n"] += 1
                if j.get("appropriate_refusal") is True:
                    agg[label]["refusal_ok"] += 1
            print(f"[{label:11}] {tid:24} grnd={j.get('grounding')} acc={j.get('accuracy')} "
                  f"help={j.get('helpfulness')} fab={j.get('fabricated')} lat={dt:.1f}s tok={otok}")

    def mean(xs):
        return round(statistics.mean(xs), 2) if xs else None

    summary = {}
    for label in agg:
        a = agg[label]
        summary[label] = {
            "n": len(a["lat"]), "empty": a["empty"],
            "grounding": mean(a["grounding"]), "accuracy": mean(a["accuracy"]),
            "helpfulness": mean(a["helpfulness"]), "fabricated_total": sum(a["fabricated"]) if a["fabricated"] else None,
            "latency_p50_s": round(statistics.median(a["lat"]), 1) if a["lat"] else None,
            "latency_max_s": round(max(a["lat"]), 1) if a["lat"] else None,
            "out_tok_mean": int(mean(a["out_tok"])) if a["out_tok"] else None,
            "refusal": f"{a['refusal_ok']}/{a['refusal_n']}",
        }
    out = {"summary": summary, "rows": rows}
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "synth_ab_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
