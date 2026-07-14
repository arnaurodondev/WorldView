"""Read-only lifetime extraction for the decay fitter — PLAN-0123 Wave 2, T-A-2-04.

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL (same
convention as every other intelligence_db repository in this service, e.g.
``relation_type_registry.py``, ``relation_evidence.py``).

100% read traffic (R27): callers MUST pass a session bound to the
read-replica connection factory (this service's ``get_readonly_session`` /
``ReadOnlyDbSessionDep`` convention — see ``api/dependencies.py``). No write
statement appears anywhere in this module.

Sources (PRD §6.6, P-5 circularity guard, plan Wave 1 codebase-state table):
- ``extract_mention_series`` reads **pre-gating** ``relation_evidence_raw``
  (never confidence-gated ``relation_evidence``) — fitting on gated data
  would bias toward the *current* alpha (circularity).
- ``extract_supersession_lifetimes`` reads **``relations``** directly
  (``first_evidence_at``, ``latest_contra_at``, ``valid_to``) — NOT
  ``relations_history``, which has no ``decay_alpha`` column and is not
  needed here (everything required is already denormalized on ``relations``).

Both functions enforce the ``TEMPORAL_CLAIM``-only scope guard (P-3): a
``RELATION_STATE`` type is never extracted for fitting — it raises rather
than silently returning an empty/wrong result.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.analytics.decay_fitting.supersession_estimator import build_lifetime
from knowledge_graph.domain.decay_fit import Lifetime, MentionSeries

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RelationStateNotFittableError(ValueError):
    """Raised when the fitter is pointed at a RELATION_STATE type (P-3 scope guard)."""

    def __init__(self, canonical_type: str, semantic_mode: str) -> None:
        super().__init__(
            f"canonical_type={canonical_type!r} has semantic_mode={semantic_mode!r}; "
            "the decay fitter is scoped to TEMPORAL_CLAIM only (PRD-0120 P-3)",
        )


async def _assert_temporal_claim(session: AsyncSession, canonical_type: str) -> None:
    """Scope guard (P-3): raise if *canonical_type* is not TEMPORAL_CLAIM."""
    result = await session.execute(
        text("""
SELECT semantic_mode
FROM relation_type_registry
WHERE canonical_type = :canonical_type
"""),
        {"canonical_type": canonical_type},
    )
    row = result.fetchone()
    if row is None:
        raise ValueError(f"canonical_type={canonical_type!r} not found in relation_type_registry")
    semantic_mode = str(row[0])
    if semantic_mode != "TEMPORAL_CLAIM":
        raise RelationStateNotFittableError(canonical_type, semantic_mode)


async def extract_mention_series(
    canonical_type: str,
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[MentionSeries]:
    """Group pre-gating evidence into one :class:`MentionSeries` per relation instance.

    Each relation instance's founding mention (its earliest ``evidence_date``)
    defines age-0; every later mention's age is measured relative to it.
    ``observation_window_days`` is the age of the founding mention as of
    *now* — every relation instance's exposure is right-censored at "now"
    regardless of whether it was mentioned again (inherent to the NHPP
    formulation, no separate censoring flag needed — see
    ``nhpp_estimator.py``).

    Args:
    ----
        canonical_type: Must be a ``TEMPORAL_CLAIM`` type (P-3 scope guard).
        session: A session bound to the **read replica** (R27) — callers
            must not pass a write-path session.
        now: Injectable for tests; defaults to ``common.time.utc_now()``.

    Returns:
    -------
        One :class:`MentionSeries` per distinct relation instance
        (subject/object pair) of *canonical_type*.

    """
    await _assert_temporal_claim(session, canonical_type)

    if now is None:
        from common.time import utc_now  # type: ignore[import-untyped]

        now = utc_now()

    # relation_evidence_raw has NO relation_id column (it is pre-relation
    # staging, keyed only by subject/object/canonical_type) — join to
    # ``relations`` on that natural key (uidx_relations_triple) to attach
    # the real relation_id. This also naturally excludes evidence for edges
    # that never materialized (e.g. still-deferred provisional relations),
    # which is the correct scope for fitting.
    result = await session.execute(
        text("""
SELECT rer.subject_entity_id, rer.object_entity_id, r.relation_id, rer.evidence_date
FROM relation_evidence_raw rer
JOIN relations r
  ON r.subject_entity_id = rer.subject_entity_id
 AND r.object_entity_id  = rer.object_entity_id
 AND r.canonical_type    = rer.canonical_type
WHERE rer.canonical_type = :canonical_type
ORDER BY rer.subject_entity_id, rer.object_entity_id, rer.evidence_date
"""),
        {"canonical_type": canonical_type},
    )
    rows = result.fetchall()

    groups: dict[tuple[str, str], list[datetime]] = {}
    relation_ids: dict[tuple[str, str], UUID] = {}
    for subject_id, object_id, relation_id, evidence_date in rows:
        key = (str(subject_id), str(object_id))
        groups.setdefault(key, []).append(evidence_date)
        relation_ids[key] = relation_id if isinstance(relation_id, UUID) else UUID(str(relation_id))

    series: list[MentionSeries] = []
    for key, dates in groups.items():
        dates_sorted = sorted(dates)
        founding = dates_sorted[0]
        window_days = (now - founding).total_seconds() / 86400.0
        mention_ages = tuple((d - founding).total_seconds() / 86400.0 for d in dates_sorted[1:])
        series.append(
            MentionSeries(
                canonical_type=canonical_type,
                relation_id=relation_ids[key],
                mention_ages_days=mention_ages,
                observation_window_days=max(window_days, 0.0),
            ),
        )
    return series


async def extract_supersession_lifetimes(
    canonical_type: str,
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[Lifetime]:
    """Build one :class:`Lifetime` per relation of *canonical_type* from ``relations``.

    Reads ``first_evidence_at``, ``latest_contra_at``, ``valid_to`` directly
    off ``relations`` — NOT ``relations_history`` (no ``decay_alpha`` column
    there, and everything needed is already on ``relations``).

    Args:
    ----
        canonical_type: Must be a ``TEMPORAL_CLAIM`` type (P-3 scope guard).
        session: A session bound to the **read replica** (R27).
        now: Injectable for tests; defaults to ``common.time.utc_now()``.

    Returns:
    -------
        One :class:`Lifetime` per relation row of *canonical_type*, built via
        the competing-risks rule (``build_lifetime``, SS-3).

    """
    await _assert_temporal_claim(session, canonical_type)

    if now is None:
        from common.time import utc_now  # type: ignore[import-untyped]

        now = utc_now()

    result = await session.execute(
        text("""
SELECT first_evidence_at, latest_contra_at, valid_to
FROM relations
WHERE canonical_type = :canonical_type
"""),
        {"canonical_type": canonical_type},
    )
    rows = result.fetchall()

    lifetimes: list[Lifetime] = []
    for first_evidence_at, latest_contra_at, valid_to in rows:
        observation_age_days = (now - first_evidence_at).total_seconds() / 86400.0
        contra_duration = (
            (latest_contra_at - first_evidence_at).total_seconds() / 86400.0 if latest_contra_at is not None else None
        )
        valid_to_duration = (valid_to - first_evidence_at).total_seconds() / 86400.0 if valid_to is not None else None
        lifetimes.append(
            build_lifetime(
                observation_age_days=observation_age_days,
                contra_duration_days=contra_duration,
                valid_to_duration_days=valid_to_duration,
            ),
        )
    return lifetimes
