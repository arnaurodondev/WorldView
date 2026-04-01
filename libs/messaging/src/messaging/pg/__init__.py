"""PostgreSQL coordination primitives — advisory locks.

Requires the ``messaging[pg]`` extra (sqlalchemy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from messaging.pg.advisory_lock import advisory_lock_id as advisory_lock_id
    from messaging.pg.advisory_lock import pg_advisory_lock as pg_advisory_lock


def __getattr__(name: str) -> object:
    if name in ("advisory_lock_id", "pg_advisory_lock"):
        from messaging.pg.advisory_lock import advisory_lock_id, pg_advisory_lock

        return advisory_lock_id if name == "advisory_lock_id" else pg_advisory_lock
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["advisory_lock_id", "pg_advisory_lock"]
