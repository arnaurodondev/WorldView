#!/usr/bin/env python3
"""Manual fundamentals refresh trigger (PLAN-0097 W1 T-W1-04).

WHY THIS SCRIPT EXISTS
======================
The 2026-05-27 chat-eval data-integrity audit
(``docs/audits/2026-05-27-plan-0097-data-integrity-investigation.md`` Part B)
confirmed that **no FundamentalsRefreshWorker exists** in the codebase.
Fundamentals are refreshed only when an external trigger (the scheduler,
the ``/api/v1/ingest/trigger`` route, or this script) explicitly enqueues
a fetch task for the relevant symbols.

The chat-eval refusal pattern observed on 2026-05-27 — "tool returned
data for Q2 FY2027 but no Q1-Q4 FY2026" for AMD — is the visible symptom:
EODHD's most-recent FY2026 quarter for AMD had not been ingested at the
time the eval ran. Without an active polling worker, freshness is
opportunistic.

This script is the short-term mitigation: an ops one-shot that fans out
``DatasetType.FUNDAMENTALS`` ingestion triggers for a configurable list
of tickers via the existing ``POST /api/v1/ingest/trigger`` route on the
market-ingestion service. It is intentionally minimal — a proper
recurring ``FundamentalsRefreshWorker`` is deferred to PLAN-0098 (see
``docs/plans/0097-iter-9-followups-and-quality-plan.md`` W1 T-W1-04
deferral note).

USAGE
=====

  # Refresh the default eval ticker set against a locally-running stack.
  MARKET_INGESTION_URL=http://localhost:8084 \\
      python scripts/refresh_fundamentals.py

  # Refresh a custom ticker list.
  python scripts/refresh_fundamentals.py --tickers AMD,NVDA,AAPL

  # Dry-run (print the requests that would be sent, no network call).
  python scripts/refresh_fundamentals.py --dry-run

ENV VARS
========
  MARKET_INGESTION_URL   Base URL of the market-ingestion service.
                          Default: http://localhost:8084
  REFRESH_PROVIDER       Provider key (eodhd, fmp, …). Default: eodhd.

EXIT CODES
==========
  0  All triggers accepted (HTTP 202).
  1  At least one trigger failed (HTTP != 202 or transport error).
  2  Invalid CLI arguments.

CAVEATS
=======
- This script does NOT block until ingestion completes — it returns as
  soon as the API accepts the trigger. Use the
  ``instruments.last_fundamentals_ingest_at`` column (added in PLAN-0096
  T-W1-02) to verify post-ingest.
- Per-ticker rate limits are enforced server-side; if you hit EODHD's
  daily quota some triggers may be deferred. The script reports each
  ticker's response status individually so you can re-run for the
  failures alone.
- No batching beyond one HTTP request per ticker. EODHD's batch
  fundamentals endpoint exists but is not yet wired through the
  ``/api/v1/ingest/trigger`` route — left to PLAN-0098.
"""

# ruff: noqa: T201 — this is a CLI ops script; print to stdout is intentional.

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import httpx

# Default ticker set: the chat-eval universe + a handful of mega-caps that
# are most likely to surface in user questions. Keep this list short — a
# proper backfill goes through the market-ingestion scheduler, not this
# manual trigger.
_DEFAULT_TICKERS: tuple[str, ...] = (
    "AMD",
    "NVDA",
    "AAPL",
    "MSFT",
    "GOOGL",
    "META",
    "TSLA",
    "AMZN",
)


async def _trigger_one(
    client: httpx.AsyncClient,
    base_url: str,
    provider: str,
    ticker: str,
) -> tuple[str, int, str]:
    """POST one trigger and return (ticker, status_code, summary).

    Returns 0 status_code on transport failure so the caller can treat any
    non-202 (including 0) as a refresh failure for that ticker.
    """
    url = f"{base_url.rstrip('/')}/api/v1/ingest/trigger"
    payload: dict[str, Any] = {
        "provider": provider,
        # DatasetType enum: "fundamentals" — keep in sync with
        # services/market-ingestion/src/market_ingestion/domain/enums.py.
        "dataset_type": "fundamentals",
        "symbols": [ticker],
        # Fundamentals fetches do not use a timeframe / exchange selector;
        # the provider adapter picks the appropriate EODHD endpoint based
        # on the dataset_type.
        "timeframe": None,
        "exchange": None,
    }
    try:
        resp = await client.post(url, json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        return (ticker, 0, f"transport error: {exc}")

    body_excerpt = resp.text[:200].replace("\n", " ")
    return (ticker, resp.status_code, body_excerpt)


async def _run(tickers: list[str], base_url: str, provider: str, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry-run] base_url={base_url} provider={provider}")
        for t in tickers:
            print(f"[dry-run] would POST /api/v1/ingest/trigger for ticker={t}")
        return 0

    failures = 0
    # One-at-a-time fan-out — the market-ingestion route is per-symbol
    # idempotent (TriggerIngestionUseCase coalesces duplicates) so we
    # serialise rather than risk hammering EODHD's rate limit.
    async with httpx.AsyncClient() as client:
        for ticker in tickers:
            t, status, body = await _trigger_one(client, base_url, provider, ticker)
            ok = status == 202
            tag = "OK  " if ok else "FAIL"
            print(f"{tag}  {t:>6}  status={status}  body={body}")
            if not ok:
                failures += 1
    return 1 if failures > 0 else 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker list. Default: AMD,NVDA,AAPL,MSFT,GOOGL,META,TSLA,AMZN",
    )
    p.add_argument(
        "--provider",
        type=str,
        default=os.environ.get("REFRESH_PROVIDER", "eodhd"),
        help="Provider key to pass to the trigger route (default: eodhd).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the requests that would be sent, but do not call the API.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    base_url = os.environ.get("MARKET_INGESTION_URL", "http://localhost:8084")
    tickers: list[str]
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = list(_DEFAULT_TICKERS)
    if not tickers:
        print("error: no tickers provided", file=sys.stderr)
        return 2
    return asyncio.run(_run(tickers, base_url, args.provider, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
