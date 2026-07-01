#!/usr/bin/env python3
"""Shadow-diff: general-news firehose coverage vs the per-ticker EODHD sources.

WHY THIS SCRIPT EXISTS (EODHD news firehose redesign, SHADOW STAGE 2026-07-01)
-----------------------------------------------------------------------------
The general ``/api/news`` feed (source_type ``eodhd``, no ``s`` filter) is,
empirically, a symbol-tagged SUPERSET of the ~625 per-ticker feeds (source_type
``eodhd_ticker_news``). To prove that coverage claim BEFORE cutting over — and
especially to catch small-cap coverage gaps — we run the firehose IN PARALLEL
with the per-ticker sources for a few days (SHADOW STAGE) and then compare, over
a window, which url_hashes each side captured.

HOW THE COMPARISON WORKS (and why global dedup makes it meaningful)
-------------------------------------------------------------------
``article_fetch_log.url_hash`` is UNIQUE across the whole table
(``uq_article_fetch_log_url_hash``), so any given article is recorded exactly
once — attributed to whichever source stored it FIRST. During a parallel shadow
run the firehose polls far more often (e.g. every 60s) than the per-ticker
sources (hourly), so:

  * ``general_only``  = fetch_log rows attributed to the ``eodhd`` general feed.
                        These are articles the firehose WON the race for — the
                        firehose's realised coverage.
  * ``ticker_only``   = fetch_log rows attributed to ``eodhd_ticker_news``.
                        These are precisely the articles the firehose MISSED
                        (a per-ticker source got them first). This is the
                        coverage GAP — it MUST trend to ~0 before cutover.
  * ``both``          = structurally 0 in fetch_log: global url_hash dedup means
                        a hash is stored once, so overlap is winner-take-all.
                        (The firehose's own symbol-tag coverage is tracked
                        separately by the ``s4_general_firehose_symbol_tags_total``
                        Prometheus counter emitted in shadow mode.)

The per-symbol breakdown of ``ticker_only`` names EXACTLY which tickers the
firehose is failing to cover — the small-caps to inspect before cutover.

USAGE (run inside the content-ingestion image / venv)::

    cd services/content-ingestion
    python scripts/shadow_diff_general_vs_ticker.py --window-hours 24
    python scripts/shadow_diff_general_vs_ticker.py --window-hours 72 --top 50 --json

Read-only: queries the read replica; never mutates. ENV: standard
content-ingestion settings (DB_URL / DB_URL_READ).

========================= STAGED CUTOVER PLAN =================================
This script gates the cutover. Do NOT disable the per-ticker sources until the
shadow-diff shows parity. The exact sequence:

  STEP 0 (DONE — this change): ship the firehose behind flags, default OFF.
         Nothing changes in prod until the flags are flipped.

  STEP 1 — START SHADOW RUN (parallel, ~3 days):
         Redeploy content-ingestion, then flip (gitops env, NOT code):
           CONTENT_INGESTION_EODHD__GENERAL_NEWS_FIREHOSE_ENABLED=true
           CONTENT_INGESTION_EODHD__GENERAL_NEWS_SHADOW_MODE=true
           CONTENT_INGESTION_EODHD__GENERAL_NEWS_POLL_INTERVAL_SECONDS=60
         Leave ``ticker_news_sync_enabled=true`` and all 625 per-ticker sources
         RUNNING. The firehose now polls the general feed every 60s with
         early-exit (≈1 request/poll ≈ 7.2k credits/day) alongside the existing
         per-ticker sweep. Dedup makes the double-ingest a no-op.
         Verify: ``s4_general_firehose_requests_total{outcome="early_exit"}``
         dominates (each poll is 1 request), and quota (``eodhd:v1:quota:*``)
         does not spike.

  STEP 2 — PROVE PARITY (after ~3 days):
         Run this script over the parallel window:
           python scripts/shadow_diff_general_vs_ticker.py --window-hours 72 --top 50
         PASS criteria: ``ticker_only`` ≈ 0 (or only stale/illiquid symbols with
         a documented, acceptable reason). Investigate every symbol in the
         per-symbol ``ticker_only`` breakdown. Do NOT proceed until the gap is
         explained/closed.

  STEP 3 — CUTOVER (disable the per-ticker firehose):
           CONTENT_INGESTION_TICKER_NEWS_SYNC_ENABLED=false   # stop the sync worker
         Then disable the existing ``eodhd_ticker_news`` Source rows (they stop
         being polled). Keep ``general_news_firehose_enabled=true``. This is the
         625-source → 1-source cut that removes ~625 hourly 5-credit requests.

  STEP 4 — WATCH THE DROP:
         Confirm ``eodhd:v1:quota:v1:quota:<month>`` credit burn falls ~91%
         (≈78.6k → ≈7.2k credits/day) and that news freshness + entity coverage
         hold (nlp-pipeline re-extracts entities from the article body, so
         attribution is unchanged). If coverage regresses, re-enable the sync
         worker (STEP 3 is fully reversible) and re-open the shadow-diff.
==============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json as json_mod
from datetime import timedelta

import structlog
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import _build_factories
from sqlalchemy import text

import common.time

log = structlog.get_logger(__name__)

# Source types compared. ``eodhd`` = general firehose; ``eodhd_ticker_news`` =
# the per-symbol sources the firehose is meant to replace.
_GENERAL = "eodhd"
_TICKER = "eodhd_ticker_news"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare general-firehose vs per-ticker EODHD news coverage over a window.",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=24.0,
        help="Look back this many hours of article_fetch_log rows (default 24).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Show the top-N ticker symbols the firehose MISSED (default 25).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary to stdout.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    since = common.time.utc_now() - timedelta(hours=args.window_hours)

    settings = Settings()  # type: ignore[call-arg]
    write_engine, read_engine, _write_factory, read_factory = _build_factories(settings)

    try:
        async with read_factory() as session:
            # Winner-take-all counts per source type (global url_hash dedup).
            counts_rows = (
                await session.execute(
                    text(
                        """
                        SELECT s.source_type AS source_type, count(*) AS n
                        FROM article_fetch_log fl
                        JOIN sources s ON s.id = fl.source_id
                        WHERE fl.fetched_at >= :since
                          AND s.source_type IN (:general, :ticker)
                        GROUP BY s.source_type
                        """
                    ),
                    {"since": since, "general": _GENERAL, "ticker": _TICKER},
                )
            ).all()
            by_type = {row.source_type: int(row.n) for row in counts_rows}
            general_only = by_type.get(_GENERAL, 0)
            ticker_only = by_type.get(_TICKER, 0)

            # Which tickers did the firehose MISS? (per-symbol ticker_only)
            gap_rows = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(s.config->>'symbol', '(unknown)') AS symbol,
                               count(*) AS n
                        FROM article_fetch_log fl
                        JOIN sources s ON s.id = fl.source_id
                        WHERE fl.fetched_at >= :since
                          AND s.source_type = :ticker
                        GROUP BY s.config->>'symbol'
                        ORDER BY n DESC
                        LIMIT :top
                        """
                    ),
                    {"since": since, "ticker": _TICKER, "top": args.top},
                )
            ).all()
            gap_by_symbol = [{"symbol": r.symbol, "missed": int(r.n)} for r in gap_rows]

        total = general_only + ticker_only
        # Fraction of comparable articles the firehose captured first. 1.0 = the
        # firehose is a perfect (realised) superset over this window → cutover-ready.
        coverage_ratio = (general_only / total) if total else 1.0

        summary = {
            "window_hours": args.window_hours,
            "since": since.isoformat(),
            # articles seen by general-only / ticker-only / both (see module docstring
            # for why "both" is structurally 0 under global url_hash dedup).
            "general_only": general_only,
            "ticker_only": ticker_only,
            "both": 0,
            "general_coverage_ratio": round(coverage_ratio, 4),
            "top_missed_symbols": gap_by_symbol,
        }

        log.info(
            "shadow_diff.result",
            general_only=general_only,
            ticker_only=ticker_only,
            general_coverage_ratio=round(coverage_ratio, 4),
            missed_symbol_count=len(gap_by_symbol),
            cutover_ready=ticker_only == 0,
        )

        if args.json:
            print(json_mod.dumps(summary, indent=2))  # noqa: T201 — operator-facing output
        else:
            print("── EODHD news shadow-diff ─────────────────────────────")  # noqa: T201
            print(f"  window            : last {args.window_hours}h (since {since.isoformat()})")  # noqa: T201
            print(f"  general_only      : {general_only:>8}  (firehose won)")  # noqa: T201
            print(f"  ticker_only       : {ticker_only:>8}  (firehose MISSED — coverage gap)")  # noqa: T201
            print(f"  both              : {0:>8}  (0 by design: global url_hash dedup)")  # noqa: T201
            print(f"  coverage_ratio    : {coverage_ratio:>8.4f}  (1.0 = firehose is a superset)")  # noqa: T201
            if gap_by_symbol:
                print(f"  top {args.top} missed symbols (investigate before cutover):")  # noqa: T201
                for entry in gap_by_symbol:
                    print(f"      {entry['symbol']:<14} {entry['missed']:>6}")  # noqa: T201
            else:
                print("  NO firehose misses this window → cutover-ready (see STEP 2/3).")  # noqa: T201
        return 0
    finally:
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
