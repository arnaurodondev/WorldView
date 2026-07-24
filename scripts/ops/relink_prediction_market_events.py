"""Relink NULL ``prediction_markets.event_id`` rows to their Polymarket event group.

Follow-up (audit ``2026-07-16-open-followups.md``): the market->event linkage is
normally stamped by S3's :class:`PredictionEventConsumer.link_markets`, which sets
``prediction_markets.event_id`` for every child market whose ``market_id``
(Polymarket ``conditionId``) appears in a ``market.prediction.event.v1`` event's
``member_condition_ids``. That path is **forward-only**: it only fires when the
Polymarket ``/events`` group is (re-)fetched by S4. Markets whose owning event has
already ended and is never re-polled keep ``event_id = NULL`` forever.

WHY a DB-side backfill (and its hard limit)
-------------------------------------------
The group->member mapping (``member_condition_ids``) travels **only** on the Kafka
event; it is *not* persisted anywhere in ``market_data_db`` (``prediction_events``
stores just the group metadata: ``event_id``, ``name``, ``category``, dates,
``market_count`` — no member list, and there is no junction table). Consequently
the *only* deterministic, in-DB keys that can relink a market to an existing
``prediction_events`` row are:

  1. ``prediction_markets.market_slug`` == ``prediction_events.event_id`` — for
     Polymarket groups whose ``event_id`` was derived from the group **slug**
     (S4 sets ``event_id = raw["id"] or raw["slug"]``).
  2. ``prediction_markets.market_id``   == ``prediction_events.event_id`` — a
     defensive id-coincidence match.

Any market whose slug is NULL *and* whose slug/id matches no ``prediction_events``
row is **genuinely unlinkable from DB state alone** — its event group was never
fetched into ``prediction_events``, so there is nothing to link *to*. Those rows
can only be healed by re-fetching the Polymarket ``/events`` group upstream (S4),
which re-emits ``member_condition_ids`` and lets the live consumer self-heal them.
This script therefore links what is provably linkable and reports the rest with a
reason — it never guesses.

Idempotent & resumable
----------------------
* Only rows with ``event_id IS NULL`` are read; the UPDATE is guarded by
  ``event_id IS NULL`` (mirrors ``link_markets``' ``IS DISTINCT FROM`` idempotency),
  so a re-run — or a race with the live consumer — never double-writes or clobbers.
* Keyset pagination on the ``id`` primary key in committed batches: a crash /
  pod-roll leaves earlier batches committed, and a re-run simply continues over the
  remaining NULL rows. No external cursor store is needed because the ``event_id IS
  NULL`` predicate *is* the resume position.

Usage::

    python -m scripts.ops.relink_prediction_market_events

Environment variables::

    MARKET_DATA_DSN         asyncpg DSN (default postgres@localhost:5432/market_data_db)
    RELINK_BATCH_SIZE       rows per keyset page (default 500)
    RELINK_DRY_RUN          when true, only report — no writes (default false)
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import asyncpg  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/market_data_db"

# Resolution outcome labels — the value returned alongside the resolved event_id.
# Kept as module constants so tests and the summary printer share one vocabulary.
LINKED_BY_SLUG = "linked_by_slug"
LINKED_BY_MARKET_ID = "linked_by_market_id"
UNLINKABLE_NO_SLUG = "unlinkable_no_matching_event_slug_null"
UNLINKABLE_SLUG_PRESENT = "unlinkable_no_matching_event_slug_present"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in {"true", "yes", "1", "on"} if raw else default


def resolve_event_id(
    market_slug: str | None,
    market_id: str,
    known_event_ids: frozenset[str],
) -> tuple[str | None, str]:
    """Resolve a market's owning ``event_id`` from persisted keys.

    Deterministic, no guessing — mirrors ``link_markets`` membership semantics
    against the *only* keys ``market_data_db`` persists. Priority: slug (the
    semantic group key) then market_id (id-coincidence). Returns
    ``(event_id | None, reason)`` where ``reason`` is one of the module labels.
    """
    slug = (market_slug or "").strip()
    if slug and slug in known_event_ids:
        return slug, LINKED_BY_SLUG
    if market_id and market_id in known_event_ids:
        return market_id, LINKED_BY_MARKET_ID
    # Nothing matched — distinguish the two unlinkable causes for the report.
    return None, (UNLINKABLE_SLUG_PRESENT if slug else UNLINKABLE_NO_SLUG)


async def _load_event_ids(conn: asyncpg.Connection) -> frozenset[str]:
    """Return the set of all ``prediction_events.event_id`` (the linkable targets)."""
    rows = await conn.fetch("SELECT event_id FROM prediction_events")
    return frozenset(str(r["event_id"]) for r in rows if r["event_id"])


async def relink(
    conn: asyncpg.Connection,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int]:
    """Relink all NULL-``event_id`` prediction markets; return a reason tally.

    The tally maps every resolution label (plus ``"total"``) to a count. Only
    ``event_id IS NULL`` rows are visited, and the UPDATE is guarded by the same
    predicate, so the pass is idempotent and safe to interleave with live writes.
    """
    known_event_ids = await _load_event_ids(conn)

    tally: dict[str, int] = {
        "total": 0,
        LINKED_BY_SLUG: 0,
        LINKED_BY_MARKET_ID: 0,
        UNLINKABLE_NO_SLUG: 0,
        UNLINKABLE_SLUG_PRESENT: 0,
    }
    # Keyset cursor on the id PK. UUID text ordering is stable and total, so
    # ``id > cursor`` walks every NULL row exactly once even across restarts.
    cursor = ""
    while True:
        rows = await conn.fetch(
            "SELECT id, market_id, market_slug FROM prediction_markets "
            "WHERE event_id IS NULL AND id::text > $1 "
            "ORDER BY id::text LIMIT $2",
            cursor,
            batch_size,
        )
        if not rows:
            break

        updates: list[tuple[str, str]] = []  # (event_id, market row id)
        for r in rows:
            tally["total"] += 1
            resolved, reason = resolve_event_id(r["market_slug"], str(r["market_id"]), known_event_ids)
            tally[reason] += 1
            if resolved is not None:
                updates.append((resolved, str(r["id"])))

        if updates and not dry_run:
            await conn.executemany(
                "UPDATE prediction_markets SET event_id = $1, updated_at = now() "
                "WHERE id = $2::uuid AND event_id IS NULL",
                updates,
            )

        cursor = str(rows[-1]["id"])

    return tally


def _format_summary(tally: Mapping[str, int], *, dry_run: bool) -> str:
    linked = tally[LINKED_BY_SLUG] + tally[LINKED_BY_MARKET_ID]
    unlinkable = tally[UNLINKABLE_NO_SLUG] + tally[UNLINKABLE_SLUG_PRESENT]
    verb = "would link" if dry_run else "linked"
    lines = [
        f"[INFO] {tally['total']} prediction markets with NULL event_id",
        f"[DONE] {verb} {linked} "
        f"({tally[LINKED_BY_SLUG]} by slug, {tally[LINKED_BY_MARKET_ID]} by market_id); "
        f"{unlinkable} unlinkable",
        f"  {UNLINKABLE_NO_SLUG:<42} {tally[UNLINKABLE_NO_SLUG]}",
        f"  {UNLINKABLE_SLUG_PRESENT:<42} {tally[UNLINKABLE_SLUG_PRESENT]}",
    ]
    return "\n".join(lines)


async def main() -> None:
    dsn = os.environ.get("MARKET_DATA_DSN", _DEFAULT_DSN)
    batch_size = _env_int("RELINK_BATCH_SIZE", 500)
    dry_run = _env_bool("RELINK_DRY_RUN", False)

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        tally = await relink(conn, batch_size=batch_size, dry_run=dry_run)
        print(_format_summary(tally, dry_run=dry_run))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
