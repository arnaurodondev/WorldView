"""Backfill ROOT portfolios for users that pre-date PLAN-0046 Wave 3.

PLAN-0046 Wave 3 / T-46-3-02.

Migration 0011 adds the ``kind`` discriminator and the ROOT concept, but
does NOT create root portfolios for existing users — that requires inserting
new rows, which is application-level work. Running this script once after
deploying migration 0011 ensures every existing user immediately has the
"All Accounts" view available.

Idempotency:
    Safe to re-run any number of times. The partial unique index
    ``uq_portfolios_owner_root`` guarantees at most one ROOT per user. Each
    iteration calls ``EnsureRootPortfolioUseCase``, which checks for an
    existing root and is a no-op when present.

Usage:
    # Dry run — list users that would get a new root, mutate nothing.
    python -m portfolio.scripts.backfill_root_portfolios --dry-run

    # Live run — provision missing roots and commit per-user.
    python -m portfolio.scripts.backfill_root_portfolios

Environment:
    Loads ``Settings`` (database URL, etc.) the same way the API server does.

Why per-user commits (not one big transaction):
    A failure mid-loop should not roll back the users who were successfully
    backfilled. Per-user commits give us "at-least-once-per-user" semantics:
    the next run will skip everyone that succeeded last time.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any

import structlog
from portfolio.application.use_cases.ensure_root_portfolio import EnsureRootPortfolioUseCase
from portfolio.config import Settings
from portfolio.infrastructure.db.session import _build_factories
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


@dataclass
class BackfillReport:
    """Summary of what the backfill loop did (or would do under --dry-run)."""

    users_total: int
    users_already_had_root: int
    users_root_created: int
    users_failed: int


async def _run(settings: Settings, *, dry_run: bool) -> BackfillReport:
    """Iterate every user, ensuring a ROOT portfolio for each."""
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    users_total = 0
    already_had = 0
    created = 0
    failed = 0

    # ── Step 1: snapshot the user list in a read-only transaction ────────
    # Why we read the user list outside the per-user UoW: we do not want a
    # long-running transaction holding row locks on the users table while we
    # iterate. A snapshot read is fine here — even if a new user is created
    # concurrently, the next backfill run will pick them up (the auto-provision
    # path on first login also handles this).
    async with write_factory() as snapshot_session:
        result = await snapshot_session.execute(
            text("SELECT id, tenant_id FROM users WHERE status = 'active'"),
        )
        rows: list[Any] = list(result.fetchall())

    users_total = len(rows)
    logger.info("backfill_users_loaded", count=users_total)

    if users_total == 0:
        return BackfillReport(0, 0, 0, 0)

    # ── Step 2: for each user, ensure a ROOT portfolio in its own UoW ─────
    uc = EnsureRootPortfolioUseCase()
    for user_id, tenant_id in rows:
        try:
            # Each iteration gets its own UoW so commits/rollbacks are isolated.
            uow = SqlAlchemyUnitOfWork(write_factory)
            async with uow:
                outcome = await uc.execute(user_id, tenant_id, uow)
                if outcome.created:
                    created += 1
                    if dry_run:
                        # Roll back the speculative insert under --dry-run so
                        # the script can be safely tested in production.
                        await uow.rollback()
                        logger.info(
                            "dry_run_would_create_root",
                            user_id=str(user_id),
                            tenant_id=str(tenant_id),
                        )
                    else:
                        await uow.commit()
                        logger.info(
                            "root_created",
                            user_id=str(user_id),
                            tenant_id=str(tenant_id),
                            portfolio_id=str(outcome.portfolio_id),
                        )
                else:
                    already_had += 1
        except Exception as exc:
            # Log + continue: one failed user must not block backfilling the rest.
            failed += 1
            logger.error(
                "root_backfill_failed",
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                error=str(exc),
                exc_info=True,
            )

    return BackfillReport(
        users_total=users_total,
        users_already_had_root=already_had,
        users_root_created=created,
        users_failed=failed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill ROOT portfolios for existing users.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change but do not commit.",
    )
    args = parser.parse_args(argv)

    configure_logging("portfolio-backfill-root")
    settings = Settings()  # type: ignore[call-arg]
    report = asyncio.run(_run(settings, dry_run=args.dry_run))

    logger.info(
        "backfill_root_portfolios_complete",
        dry_run=args.dry_run,
        users_total=report.users_total,
        users_already_had_root=report.users_already_had_root,
        users_root_created=report.users_root_created,
        users_failed=report.users_failed,
    )
    # Non-zero exit when any user failed so CI / operators notice.
    return 0 if report.users_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
