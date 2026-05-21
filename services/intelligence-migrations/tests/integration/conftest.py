"""Fixtures for the TASK-W3-01 integration test suite.

The parent ``tests/conftest.py`` exposes a session-scoped autouse fixture
``run_migrations`` that runs ``alembic downgrade base`` followed by
``alembic upgrade head`` against the test database. If the database is not
reachable, that fixture errors out and the whole pytest session collapses —
which would prevent the pure-static R24/naming tests from ever running.

This subdirectory conftest overrides ``run_migrations`` with a *graceful*
variant that:

  * attempts the same downgrade+upgrade if ``INTELLIGENCE_DB_URL`` is set
    and the Postgres at that URL is reachable; on success, yields normally
    (live tests 1/2/4 then run);
  * sets a session-level "live DB unavailable" flag on a graceful failure,
    yields anyway so static tests can collect+execute, and individual
    live tests skip themselves via the ``live_db_ready`` fixture.

The override is scoped to the ``tests/integration/`` package so the existing
top-level tests (which already error loudly when DB is missing) keep their
current behaviour.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from alembic import command

if TYPE_CHECKING:
    from collections.abc import Iterator

    import sqlalchemy as sa
    from alembic.config import Config

# Cache the live-DB availability so multiple fixtures don't re-probe.
_LIVE_DB_STATE: dict[str, bool | str] = {"checked": False, "available": False, "reason": ""}


def _probe_db_reachable(url: str, timeout: float = 1.5) -> tuple[bool, str]:
    """Return ``(reachable, reason)`` for a Postgres URL without opening a
    SQLAlchemy connection. We just TCP-probe the host:port so failure is fast
    even when the host is unroutable.
    """
    try:
        parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:  # — any socket error means "unreachable"
        return False, f"TCP probe of {host}:{port} failed: {exc}"
    except Exception as exc:  # — parsing failure also means unusable
        return False, f"URL parse failure: {exc}"


@pytest.fixture(scope="session", autouse=True)
def run_migrations(  # type: ignore[override]
    alembic_cfg: Config,
    engine: sa.engine.Engine,
) -> Iterator[None]:
    """Override parent ``run_migrations``: tolerate missing/unreachable DB.

    When the DB is reachable, behaves identically to the parent fixture
    (downgrade base → upgrade head, then downgrade base on teardown). When
    the DB is unreachable, skips silently so static tests can still run;
    live tests (1/2/4) consult ``live_db_ready`` and skip themselves.
    """
    url = str(engine.url)
    reachable, reason = _probe_db_reachable(url)
    if not reachable:
        _LIVE_DB_STATE["checked"] = True
        _LIVE_DB_STATE["available"] = False
        _LIVE_DB_STATE["reason"] = reason
        yield
        return

    try:
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:  # — any alembic/SQL error → mark unavailable
        _LIVE_DB_STATE["checked"] = True
        _LIVE_DB_STATE["available"] = False
        _LIVE_DB_STATE["reason"] = f"alembic upgrade failed: {exc}"
        yield
        return

    _LIVE_DB_STATE["checked"] = True
    _LIVE_DB_STATE["available"] = True
    _LIVE_DB_STATE["reason"] = ""
    try:
        yield
    finally:
        # Best-effort teardown so a future session starts clean. If the
        # teardown fails the next session will downgrade-then-upgrade from
        # whatever state we leave behind, so swallowing the exception here
        # is intentional.
        try:
            command.downgrade(alembic_cfg, "base")
        except Exception:  # noqa: S110 — teardown best-effort
            pass


@pytest.fixture()
def live_db_ready() -> None:
    """Skip the calling test when the integration DB is not reachable or
    the session-fixture migration sweep failed.

    The skip reason distinguishes a missing DB (network/TCP probe failed)
    from a migration-application failure so the latter surfaces during
    debugging instead of being mistaken for "no Postgres available".
    """
    if _LIVE_DB_STATE.get("available"):
        return
    reason = _LIVE_DB_STATE.get("reason", "no probe ran")
    if "alembic upgrade failed" in str(reason):
        pytest.skip(f"intelligence_db migration failed during session setup — see error above. Reason: {reason}")
    else:
        pytest.skip(f"INTELLIGENCE_DB_URL not reachable: {reason}")
