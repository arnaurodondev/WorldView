"""PostgreSQL coordination primitives — advisory locks.

Requires the ``messaging[pg]`` extra (sqlalchemy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

_NAMES = (
    "advisory_lock_id",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_advisory_lock_pinned",
)

if TYPE_CHECKING:
    from messaging.pg.advisory_lock import advisory_lock_id as advisory_lock_id
    from messaging.pg.advisory_lock import pg_advisory_lock as pg_advisory_lock
    from messaging.pg.advisory_lock import pg_advisory_lock_pinned as pg_advisory_lock_pinned
    from messaging.pg.advisory_lock import pg_advisory_xact_lock as pg_advisory_xact_lock


def __getattr__(name: str) -> object:
    if name in _NAMES:
        from messaging.pg import advisory_lock

        return getattr(advisory_lock, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_NAMES)
