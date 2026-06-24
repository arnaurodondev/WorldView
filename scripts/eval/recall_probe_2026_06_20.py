"""Targeted recall probe (2026-06-20 investigation, throwaway).

Reuses the frozen golden_set.json from results/model_switch_ab and re-extracts a
HANDFUL of the worst-recall articles under two interventions, to test recall
root-cause hypotheses WITHOUT touching the DB or production config:

  H-A (reasoning_effort): re-run @medium vs @high on the same articles.
  H-B (allow-list repair): re-run the Thai My-ENet article (Mavenir off-list)
       with "Mavenir" added to the entity allow-list, to see if the missed
       ENet-Mavenir partnership relation then appears.

Output: prints n_relations / relation list per arm. No files written, no commits.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))
sys.path.insert(0, str(REPO / "libs" / "prompts" / "src"))

import extraction_quality_eval as H  # noqa: E402, N812 — `H` (harness) alias used pervasively for brevity.

GOLDEN = json.loads((REPO / "results" / "model_switch_ab" / "golden_set.json").read_text())
BY_PREFIX = {g["doc_id"][:10]: g for g in GOLDEN}

API_KEY = os.environ["KEY"]
BASE = "https://api.deepinfra.com/v1/openai"


def _art(prefix: str, entities_override: str | None = None) -> H.GoldenArticle:
    g = BY_PREFIX[prefix]
    return H.GoldenArticle(
        doc_id=g["doc_id"],
        title=g["title"],
        source_name=g["source_name"],
        published_at=g["published_at"],
        routing_tier=g["routing_tier"],
        span_bucket=g["span_bucket"],
        word_count=g["word_count"],
        entity_count=g["entity_count"],
        entities=entities_override if entities_override is not None else g["entities"],
        text=g["text"],
    )


def _run(client: httpx.Client, art: H.GoldenArticle, arm: str) -> None:
    res = H.run_model_on_article(client, API_KEY, BASE, arm, art)
    rels = (res.parsed or {}).get("relations", []) if res.parsed else []
    print(f"  [{arm:28s}] status={res.status} n_rel={len(rels)} n_claim={res.n_claims} n_ev={res.n_events}")
    for r in rels:
        print(f"      {r.get('subject_ref')} --{r.get('predicate')}--> {r.get('object_ref')}")


def main() -> None:
    # Worst relation-miss articles (see investigation report).
    probes = ["019ede68-8", "019ede68-9", "019ede3b-3", "019ede63-6"]
    with httpx.Client(timeout=httpx.Timeout(180.0)) as client:
        for pfx in probes:
            art = _art(pfx)
            print(f"\n=== {pfx} | {art.title[:55]} | allow-list: {art.entities[:80]}")
            _run(client, art, "openai/gpt-oss-120b@medium")
            _run(client, art, "openai/gpt-oss-120b@high")

        # H-B: Thai article with Mavenir repaired into the allow-list.
        print("\n=== H-B allow-list repair: 019ede68-8 (Thai) + Mavenir ===")
        repaired = _art("019ede68-8", entities_override="ENet, My ENet, Mavenir")
        _run(client, repaired, "openai/gpt-oss-120b@medium")


if __name__ == "__main__":
    main()
