"""Guard helpers shared by Alembic migrations.

PLAN-0093 Wave Phase 5 remediation (QA-4, A.4.1).

This is an intentional copy of
``services/intelligence-migrations/alembic/_guards.py``.  Each service has
its own alembic env with a distinct ``sys.path``, so a single shared module
cannot be imported across both.  Keep both files identical.

See the intelligence-migrations copy for the full rationale.
"""

from __future__ import annotations

import os


def assert_truncate_allowed(table: str) -> None:
    """Refuse to TRUNCATE in production unless explicitly overridden.

    Parameters
    ----------
    table:
        Human-readable name of the table (or table group) about to be
        truncated.  Only used to make the RuntimeError message useful.

    Raises
    ------
    RuntimeError
        If ``APP_ENV`` is ``production`` and ``ALLOW_DESTRUCTIVE_MIGRATION``
        is not set to the literal string ``"1"``.
    """
    if os.environ.get("APP_ENV", "").lower() == "production" and os.environ.get("ALLOW_DESTRUCTIVE_MIGRATION") != "1":
        raise RuntimeError(
            f"Refusing to TRUNCATE {table!r} in APP_ENV=production. "
            "Set ALLOW_DESTRUCTIVE_MIGRATION=1 to override (requires SRE sign-off)."
        )
