#!/usr/bin/env python3
"""Backfill CLI: populate fundamental_metrics from existing fundamentals rows.

Provides chunked, deterministic, resumable processing with machine-readable
summary output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from argparse import ArgumentParser

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Ensure the service package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.infrastructure.db.backfill_fundamental_metrics import BackfillOptions, run_backfill

logger = structlog.get_logger(__name__)


async def backfill(db_url: str, options: BackfillOptions, json_summary: bool = True) -> None:
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    summary = await run_backfill(session_factory, options)
    await engine.dispose()

    if json_summary:
        sys.stdout.write(f"{json.dumps(summary.to_dict(), sort_keys=True)}\\n")
    else:
        logger.info("fundamental_metrics_backfill.summary", **summary.to_dict())


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Backfill fundamental_metrics projection")
    parser.add_argument("--section", type=str, default=None, help="Single section to backfill (optional)")
    parser.add_argument("--start-id", type=str, default=None, help="Resume cursor: process rows with id > start-id")
    parser.add_argument("--batch-size", type=int, default=500, help="Chunk size for read/upsert")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Continue processing after row-level failures",
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        default=False,
        help="Print machine-readable JSON summary to stdout",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    db_url = os.environ.get("MARKET_DATA_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("fundamental_metrics_backfill_missing_db_url")
        sys.exit(1)

    # Ensure async driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    options = BackfillOptions(
        batch_size=args.batch_size,
        section=args.section,
        start_id=args.start_id,
        continue_on_error=args.continue_on_error,
    )
    asyncio.run(backfill(db_url, options, json_summary=args.json_summary))


if __name__ == "__main__":
    main()
