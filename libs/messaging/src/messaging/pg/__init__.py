"""PostgreSQL coordination primitives — advisory locks."""

from messaging.pg.advisory_lock import advisory_lock_id, pg_advisory_lock

__all__ = ["advisory_lock_id", "pg_advisory_lock"]
