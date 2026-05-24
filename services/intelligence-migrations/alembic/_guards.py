"""Guard helpers shared by Alembic migrations.

PLAN-0093 Wave Phase 5 remediation (QA-4, A.4.1).

WHY THIS FILE EXISTS
--------------------
The platform-wide ``assert_app_env_or_die`` runs at *application* startup —
Alembic migrations run independently (CI jobs, ad-hoc CLI invocations,
restored staging dumps, developer laptops) and therefore bypass that gate.

Several PLAN-0093 migrations (0045, 0047, and nlp-pipeline 0020) issue
``TRUNCATE`` against tables that may contain real data in production.  The
explicit "Pre-Prod Simplifications" preamble in the plan tolerates that for
pre-production environments — but if the migration is ever replayed in
``APP_ENV=production`` (e.g. someone restores a prod snapshot into a CI
shard and re-runs the chain) the truncate would silently delete real data.

The helper below makes that footgun explicit: it raises in production unless
the operator opts in via ``ALLOW_DESTRUCTIVE_MIGRATION=1``.

NOTE ON IMPORT PATH
-------------------
This module is shipped under the ``alembic/`` directory so it sits next to
``versions/``.  Alembic does not treat ``versions/`` as a package, so the
migrations import this helper via the ``_guards`` sibling module.  An
identical copy lives in ``services/nlp-pipeline/alembic/_guards.py`` because
that service has its own alembic env with a distinct ``sys.path``.
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
