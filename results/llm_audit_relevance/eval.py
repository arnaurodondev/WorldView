#!/usr/bin/env python3
"""Standalone targeted A/B for structured NLP capabilities (relevance, resolution).

READ-ONLY w.r.t. the platform. Calls DeepInfra directly. Judge = DeepSeek-V4-Flash
for relevance calibration; for resolution we use the weak DB label as ground truth
(binary entity/noise) so no judge needed there.

Usage:
  DEEPINFRA_API_KEY=... python eval.py relevance
  DEEPINFRA_API_KEY=... python eval.py resolution
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

KEY = os.environ["DEEPINFRA_API_KEY"]
URL = "https://api.deepinfra.com/v1/openai/chat/completions"


def call(model: str, system: str, user: str, reasoning: str | None, max_tokens: int = 256) -> tuple[str, float]:
    body: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if reasoning is not None:
        body["reasoning_effort"] = reasoning
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data=data, headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
        dt = time.time() - t0
        content = resp["choices"][0]["message"].get("content") or ""
        return content.strip(), dt
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}", time.time() - t0


def parse_json(txt: str) -> dict | None:
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json").strip()
    s, e = txt.find("{"), txt.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(txt[s : e + 1])
    except Exception:  # noqa: BLE001
        return None


RELEVANCE_SYSTEM = (
    "You are a financial news relevance assessor. Rate the market impact of this news article from 0.0 to 1.0.\n"
    "0.0 = completely irrelevant (celebrity news, sports, weather)\n0.3 = mildly relevant (broad economy, far sector)\n"
    "0.6 = moderately relevant (sector news, indirect exposure)\n0.9 = highly relevant (direct earnings, M&A, regulatory action)\n"
    "1.0 = critical (halted trading, major earnings miss, bankruptcy)\n"
    "If the title is absent, vague, or ambiguous, return score 0.3 as a conservative default.\n"
    'Also classify the market sentiment: "positive","negative","neutral","mixed".\n'
    'Respond with ONLY valid JSON: {"score": <float 0.0-1.0>, "reason": "<max 10 words>", "sentiment": "positive"|"negative"|"neutral"|"mixed"}'
)

# (title, baseline_qwen3.5-9b_score, baseline_sentiment) — from live nlp_db
RELEVANCE_SAMPLE = [
    ("TSMC's Price Hike Is Bad For Nvidia Margins — And Potentially Great For Nvidia Stock", 0.9, "mixed"),
    ("FLEX LNG Ltd. Q1 2026 Earnings Call Summary", 0.9, "neutral"),
    ("Palantir CEO Warns AI Could Supercharge Wealth Inequality", 0.6, "negative"),
    ("Why Uranium Energy Stock Is Plummeting Again Today", 0.9, "negative"),
    ("Airline profits forecast to halve in 2026 as Middle East conflict, fuel costs weigh", 0.6, "negative"),
    ("Jim Cramer on Adobe: “I Don’t Want You in It”", 0.6, "negative"),
    ("12 Months From Now, Will You Wish You'd Bought This Industrial Stock?", 0.3, "neutral"),
    ("Alphabet (GOOGL): A Must-Buy Stock with the Strongest 1Q2026 Earnings Beats", 0.9, "positive"),
    ("The difference between on-prem AI vs. data centers", 0.3, "neutral"),
    ("Intel Gains as Google Reportedly Eyes Major AI Chip Order", 0.9, "positive"),
    ("$ADMA Fraud Notice: ADMA Biologics Accused of Securities Fraud over Channel Stuffing", 0.9, "negative"),
    ("Visa plugs its payment network into ChatGPT, letting AI agents shop and pay for users", 0.6, "positive"),
    ("New Ownership of PostalAnnex in San Jose Brings Fresh Energy to the Business", 0.3, "neutral"),
    ("Apple Inc. (AAPL) Is A Top Stock In Ken Griffin’s Portfolio", 0.6, "positive"),
    ("Western Digital Stock Skyrockets 185% YTD: Is More Growth on the Horizon?", 0.6, "positive"),
    ("U.S. Bancorp Names Brian Mauney Head of Investor Relations", 0.6, "neutral"),
    ("Nvidia Says Anthropic, OpenAI Among Users of New Vera Chip", 0.6, "neutral"),
    ("Has Temu-Owner PDD's Story Changed After Double Miss?", 0.9, "negative"),
    ("1 Value Stock to Keep an Eye On and 2 We Brush Off", 0.3, "neutral"),
    ("United Airlines Targets Distressed Rival Assets To Refine Premium Network Growth", 0.6, "positive"),
]

RES_SYSTEM = (
    "You are classifying a candidate entity mention from a financial-news pipeline. "
    "Decide whether the SURFACE refers to a real, named entity worth tracking in a "
    "market-intelligence knowledge graph. Companies, subsidiaries, funds, ETFs, indices, "
    "regulators, central banks, named persons, named financial products are ENTITY. "
    "Pronouns, generic roles (analysts, investors, shares), jargon (constant currency), "
    "media outlets used as attribution, bare numbers/dates/tickers, common-noun event words, "
    "and misparsed fragments are NOISE.\n"
    'Respond with ONLY JSON: {"is_entity": <true|false>, "confidence": <0.0-1.0>, "reason": "<short>"}'
)

# (surface, mention_class, weak_label_is_entity) — from live nlp_db resolution_outcome
RES_SAMPLE = [
    ("Globale Aktier", "financial_instrument", False),
    ("Badami", "location", False),
    ("business inventories", "macroeconomic_indicator", False),
    ("steel", "commodity", False),
    ("brokerage firms", "financial_institution", False),
    ("OUT shares", "financial_instrument", False),
    ("shares", "financial_instrument", False),
    ("Flower Mound, Texas", "location", False),
    ("sentiment", "macroeconomic_indicator", False),
    ("settlor", "person", False),
    ("Stock", "financial_instrument", False),
    ("Park Meadows", "location", False),
    ("NASDAQ", "organization", True),
    ("BYD", "organization", True),
    ("Booking Holdings", "organization", True),
    ("Freedom Holding", "organization", True),
    ("Synopsys", "organization", True),
    ("Culper Research", "organization", True),
    ("Samsung", "organization", True),
    ("OpenAI", "organization", True),
    ("Matador Resources", "organization", True),
    ("Intel", "organization", True),
    ("SMCI", "organization", True),
    ("Paycom", "organization", True),
    ("AXON", "organization", True),
    ("Deb Cupp", "person", True),
    ("Wall Street", "financial_institution", True),
    ("Kay Jewelers", "organization", True),
]

# Reasoning models need reasoning_effort set; Qwen3.5-9B uses enable_thinking via chat_template
# but reasoning_effort=none also disables CoT. None => provider default (baseline parity).
ARMS_RELEVANCE = [
    ("Qwen/Qwen3.5-9B", "none", "baseline"),
    ("openai/gpt-oss-20b", "low", "20b@low"),
    ("openai/gpt-oss-120b", "low", "120b@low"),
]
ARMS_RES = [
    ("Qwen/Qwen3.5-9B", "none", "baseline"),
    ("openai/gpt-oss-20b", "low", "20b@low"),
    ("openai/gpt-oss-120b", "low", "120b@low"),
]


def run_relevance() -> None:
    out: dict = {}
    for model, reff, label in ARMS_RELEVANCE:
        rows, lats, score_err, sent_match, empties = [], [], [], 0, 0
        for title, base_score, base_sent in RELEVANCE_SAMPLE:
            user = f"Title: {title}\nSource: news"
            content, dt = call(model, RELEVANCE_SYSTEM, user, reff, 256)
            lats.append(dt)
            obj = parse_json(content)
            if not obj or "score" not in obj:
                empties += 1
                rows.append({"title": title, "raw": content[:120]})
                continue
            try:
                sc = float(obj["score"])
            except Exception:  # noqa: BLE001
                empties += 1
                continue
            score_err.append(abs(sc - base_score))
            if str(obj.get("sentiment", "")).lower() == base_sent:
                sent_match += 1
            rows.append({"title": title, "score": sc, "base": base_score, "sentiment": obj.get("sentiment"), "base_sent": base_sent})
        n = len(RELEVANCE_SAMPLE)
        out[label] = {
            "model": model,
            "reasoning": reff,
            "n": n,
            "empties": empties,
            "mae_vs_baseline_score": round(sum(score_err) / len(score_err), 3) if score_err else None,
            "sentiment_agree_pct": round(100 * sent_match / n, 1),
            "lat_p50": round(sorted(lats)[len(lats) // 2], 2),
            "lat_mean": round(sum(lats) / len(lats), 2),
            "rows": rows,
        }
        print(f"[relevance] {label}: empties={empties} mae={out[label]['mae_vs_baseline_score']} "
              f"sent_agree={out[label]['sentiment_agree_pct']}% p50={out[label]['lat_p50']}s")
    with open(os.path.join(os.path.dirname(__file__), "relevance_results.json"), "w") as f:
        json.dump(out, f, indent=2)


def run_resolution() -> None:
    out: dict = {}
    for model, reff, label in ARMS_RES:
        tp = fp = tn = fn = empties = 0
        lats, rows = [], []
        for surface, mclass, gold in RES_SAMPLE:
            user = f"SURFACE: {json.dumps(surface)}\nCONTEXT: (class={mclass})"
            content, dt = call(model, RES_SYSTEM, user, reff, 200)
            lats.append(dt)
            obj = parse_json(content)
            if not obj or "is_entity" not in obj:
                empties += 1
                continue
            pred = bool(obj["is_entity"])
            if pred and gold:
                tp += 1
            elif pred and not gold:
                fp += 1
            elif not pred and not gold:
                tn += 1
            else:
                fn += 1
            rows.append({"surface": surface, "gold": gold, "pred": pred})
        n = len(RES_SAMPLE)
        correct = tp + tn
        out[label] = {
            "model": model, "reasoning": reff, "n": n, "empties": empties,
            "accuracy_vs_weaklabel": round(100 * correct / (n - empties), 1) if (n - empties) else None,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "lat_p50": round(sorted(lats)[len(lats) // 2], 2),
            "lat_mean": round(sum(lats) / len(lats), 2),
            "rows": rows,
        }
        print(f"[resolution] {label}: acc={out[label]['accuracy_vs_weaklabel']}% "
              f"tp={tp} fp={fp} tn={tn} fn={fn} empties={empties} p50={out[label]['lat_p50']}s")
    with open(os.path.join(os.path.dirname(__file__), "resolution_results.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "relevance"
    if mode == "relevance":
        run_relevance()
    elif mode == "resolution":
        run_resolution()
