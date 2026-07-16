#!/usr/bin/env python3
"""Top-level runner for the worldview prod-QA harness.

    export KUBECONFIG=~/.kube/config-worldview     # SSH tunnel / context to prod
    python3 -m scripts.prod_qa.run                 # full suite
    python3 -m scripts.prod_qa.run --only coarse,market_data
    python3 -m scripts.prod_qa.run --skip rag_chat # (chat generation is slow)
    python3 -m scripts.prod_qa.run --json out.json --quiet

Layers
------
    coarse           platform/infra: pods, migrations, DLQ (kafka+db), consumer
                     groups, outbox drain, schema-registry, edge/TLS, MinIO
    market_data      S3: quotes/OHLCV/fundamentals/intraday/prediction streams
    knowledge_graph  S7: entity grounding, relations, AGE sync, prediction linking
    nlp_pipeline     S6: chunks/embeddings/NER/routing/relevance + read APIs
    content          S4+S5: news freshness/volume, dedup, title coverage, DLQ
    rag_chat         S8: grounded golden-answer assertions
    portfolio        S1+S2: schema presence, readiness, ingestion throughput
    alert            S10+S9: alert schema/rule-type, gateway route contract

EXIT CODE: 0 if no FAIL rows (WARNs allowed); 1 otherwise.

The suite is READ-ONLY against prod. The authenticated data-plane checks run a
prober INSIDE the api-gateway pod that mints the gateway's own internal RS256 JWT
(prod Zitadel / dev-login is unavailable headlessly) — see prober.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import harness as H
from . import prober
from .checks import alert as c_alert
from .checks import coarse as c_coarse
from .checks import content as c_content
from .checks import knowledge_graph as c_kg
from .checks import market_data as c_md
from .checks import nlp_pipeline as c_nlp
from .checks import portfolio as c_portfolio
from .checks import rag_chat as c_rag

# Ordered layer registry. `needs_api` layers consume the in-pod prober blob.
LAYERS: list[tuple[str, object, bool]] = [
    ("coarse", c_coarse, False),
    ("market_data", c_md, True),
    ("knowledge_graph", c_kg, True),
    ("nlp_pipeline", c_nlp, True),
    ("content", c_content, False),
    ("rag_chat", c_rag, True),
    ("portfolio", c_portfolio, False),
    ("alert", c_alert, True),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="worldview prod-QA harness")
    ap.add_argument("--only", help="comma list of layers to run (default: all)")
    ap.add_argument("--skip", help="comma list of layers to skip")
    ap.add_argument("--json", help="write full report JSON to this path")
    ap.add_argument("--quiet", action="store_true", help="suppress per-row output")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else set()
    selected = [(n, m, a) for (n, m, a) in LAYERS if (only is None or n in only) and n not in skip]

    report = H.Report(quiet=args.quiet)
    ctx = H.Ctx(report=report)

    print(f"worldview prod-QA — {H.PUBLIC_HOST} ({H.NODE_IP})  {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}")
    _, kctx = H.kubectl("config current-context")
    print(f"kube-context: {kctx.strip()}")

    # Run the in-pod prober once if any selected layer needs authed API data.
    if any(a for (_, _, a) in selected):
        print("\n=== in-pod API prober (mint internal JWT, drive backends) ===")
        ctx.api, ctx.aapl_entity_id = prober.run_prober(report)

    for name, mod, _ in selected:
        print(f"\n=== {name} ===")
        try:
            mod.run(ctx)  # type: ignore[attr-defined]
        except Exception as e:  # a layer crash must not abort the whole run
            report.fail(name, "layer execution", f"{type(e).__name__}: {e}")

    c = report.counts()
    print("\n" + "=" * 64)
    print(
        f"SUMMARY: {H._C[H.PASS]}{c[H.PASS]} PASS{H._C['END']}  "
        f"{H._C[H.WARN]}{c[H.WARN]} WARN{H._C['END']}  {H._C[H.FAIL]}{c[H.FAIL]} FAIL{H._C['END']}"
        f"   ({sum(c.values())} checks)"
    )
    if c[H.FAIL]:
        print("\nFAILs:")
        for svc, nm, st, det in report.rows:
            if st == H.FAIL:
                print(f"  - [{svc}] {nm} — {det}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"summary": c, "rows": report.rows}, f, indent=2)
        print(f"\nwrote {args.json}")
    return 1 if c[H.FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
