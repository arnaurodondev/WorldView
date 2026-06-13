"""One-time backfill: compute the weirdness metric for existing path_insights.

Context (PLAN-0112 W3, T-3-04):
  Migration 0052 adds the ``dst_entity_id`` + sub-score + ``weirdness`` columns
  to ``path_insights`` but leaves them NULL on existing rows.  The discovery
  worker repopulates them with the full metric (including ``novelty``) on the
  next run because ``replace_for_anchor`` does an atomic delete+insert.  This
  script is the OPTIONAL one-off that recomputes the weirdness columns for rows
  already in the table without waiting for the next discovery cycle.

DEGRADED-NOVELTY CAVEAT (read before running):
  Existing ``path_insights`` rows persist ``path_nodes`` / ``path_edges`` JSON
  but NOT the per-edge ``relation_id`` (``rel_ids``).  Novelty is therefore set
  to 0.0 for backfilled rows (it cannot be derived from stored data).  The
  reliability / unexpectedness / semantic_distance terms ARE recomputed from the
  stored nodes + edges + the live ``node_degree`` / embeddings.  Rows fully
  re-scored by the next discovery cycle will carry the true novelty term.  For a
  clean, novelty-correct backfill prefer simply letting the discovery worker
  re-run (it overwrites these rows anyway).

How to run::

    docker exec worldview-knowledge-graph-1 \\
        python -m scripts.backfill_weirdness

Options (env vars, all optional)::

    BACKFILL_BATCH_SIZE=500       # rows per SELECT/UPDATE batch
    BACKFILL_MAX_ROWS=0           # cap total rows processed (0 = all)
    BACKFILL_DRY_RUN=false        # when true, only print the candidate count

Exit codes::

    0   — successful backfill (or dry-run)
    1   — fatal wiring error (DB unreachable, node_degree empty, etc.)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from knowledge_graph.application.ports.graph_path_engine import RawPath
from knowledge_graph.application.ports.node_degree_repository import GraphStats
from knowledge_graph.application.services.weirdness_scorer import WeirdnessScorer
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_DEFINITION,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
    NodeDegreeRepository,
)
from knowledge_graph.infrastructure.workers.path_insight_worker import _parse_pgvector
from sqlalchemy import text

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.domain.entities.path_insight import PathInsight

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in {"true", "yes", "1", "on"} if raw else default


def _raw_path_from_row(nodes_json: Any, edges_json: Any) -> RawPath | None:
    """Reconstruct a (rel_ids-less) RawPath from stored path_nodes/path_edges."""
    nodes = nodes_json if isinstance(nodes_json, list) else json.loads(str(nodes_json))
    edges = edges_json if isinstance(edges_json, list) else json.loads(str(edges_json))
    if len(nodes) < 2 or not edges:
        return None
    return RawPath(
        node_ids=tuple(str(n["entity_id"]) for n in nodes),
        node_names=tuple(str(n["name"]) for n in nodes),
        node_types=tuple(str(n["entity_type"]) for n in nodes),
        rel_types=tuple(str(e["relation_type"]) for e in edges),
        edge_confs=tuple(float(e["confidence"]) for e in edges),
        rel_ids=(),  # not persisted on existing rows → novelty degrades to 0
    )


async def main() -> int:
    """Recompute weirdness columns for existing path_insights rows."""
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-backfill-weirdness",
        level=settings.log_level,
        json=settings.log_json,
    )

    batch_size = _env_int("BACKFILL_BATCH_SIZE", 500)
    max_rows = _env_int("BACKFILL_MAX_ROWS", 0)
    dry_run = _env_bool("BACKFILL_DRY_RUN", False)

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    try:
        async with write_factory() as session:
            count = await session.execute(text("SELECT count(*) FROM path_insights WHERE weirdness IS NULL"))
            candidates = int(count.scalar_one())
        logger.info("backfill_weirdness_candidates", rows=candidates, dry_run=dry_run)
        if dry_run or candidates == 0:
            return 0

        # Load the global lookups ONCE (degrees, stats).
        async with write_factory() as session:
            degree_repo = NodeDegreeRepository(session)
            degree_map = await degree_repo.get_degree_map()
            stats = await degree_repo.get_graph_stats() or GraphStats(0, 0, 0)
        if not degree_map:
            logger.error(
                "backfill_weirdness_no_degrees",
                reason="node_degree is empty — run the AGE-sync worker once to populate it first.",
            )
            return 1

        processed = 0
        while True:
            if max_rows and processed >= max_rows:
                break
            limit = batch_size if not max_rows else min(batch_size, max_rows - processed)
            updated = await _process_batch(write_factory, degree_map, stats, settings, limit)
            if updated == 0:
                break
            processed += updated
            logger.info("backfill_weirdness_progress", processed=processed)

        logger.info("backfill_weirdness_complete", processed=processed)
        return 0
    finally:
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()


async def _process_batch(
    write_factory: Any,
    degree_map: dict[UUID, tuple[int, int]],
    stats: GraphStats,
    settings: Any,
    limit: int,
) -> int:
    """Fetch + re-score + UPDATE one batch of weirdness-NULL rows."""
    async with write_factory() as session:
        rows = (
            await session.execute(
                text("SELECT insight_id, path_nodes, path_edges FROM path_insights WHERE weirdness IS NULL LIMIT :lim"),
                {"lim": limit},
            )
        ).fetchall()
        if not rows:
            return 0

        # Endpoint ids for the embedding fetch.
        endpoint_ids: set[UUID] = set()
        raw_by_id: dict[UUID, RawPath] = {}
        for row in rows:
            rp = _raw_path_from_row(row[1], row[2])
            if rp is None:
                continue
            insight_id = UUID(str(row[0]))
            raw_by_id[insight_id] = rp
            for nid in (rp.node_ids[0], rp.node_ids[-1]):
                with contextlib.suppress(ValueError, AttributeError):
                    endpoint_ids.add(UUID(nid))

        embeddings = await _fetch_embeddings(session, endpoint_ids)

        scorer = WeirdnessScorer(
            degree_of=lambda eid: degree_map.get(eid, (1, 1))[0],
            meaningful_degree_of=lambda eid: degree_map.get(eid, (1, 1))[1],
            graph_stats=stats,
            embedding_of=lambda eid: embeddings.get(eid),
            first_seen_of=lambda _rid: None,  # rel_ids absent → novelty 0 (documented)
            novelty_window=timedelta(days=settings.novelty_window_days),
            w_unexpectedness=settings.weirdness_w_unexpectedness,
            w_semantic=settings.weirdness_w_semantic,
            w_novelty=settings.weirdness_w_novelty,
            unexpectedness_mode=settings.weirdness_unexpectedness_mode,
        )

        for insight_id, rp in raw_by_id.items():
            scored: PathInsight = scorer.score(rp)
            await session.execute(
                text(
                    "UPDATE path_insights SET "
                    "  dst_entity_id = CAST(:dst AS UUID), "
                    "  reliability = :rel, unexpectedness = :unx, "
                    "  semantic_distance = :sem, novelty = :nov, "
                    "  weirdness = :wrd, composite_score = :wrd, "
                    "  scorer_version = :sv "
                    "WHERE insight_id = CAST(:iid AS UUID)"
                ),
                {
                    "dst": str(scored.dst_entity_id) if scored.dst_entity_id else None,
                    "rel": scored.reliability,
                    "unx": scored.unexpectedness,
                    "sem": scored.semantic_distance,
                    "nov": scored.novelty,
                    "wrd": scored.weirdness,
                    "sv": (scored.scorer_version or "") + "+backfill",
                    "iid": str(insight_id),
                },
            )
        await session.commit()
        return len(raw_by_id)


async def _fetch_embeddings(session: Any, entity_ids: set[UUID]) -> dict[UUID, list[float]]:
    if not entity_ids:
        return {}
    result = await session.execute(
        text(
            "SELECT entity_id, embedding::text FROM entity_embedding_state "
            "WHERE view_type = :vt AND embedding IS NOT NULL "
            "AND entity_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"vt": VIEW_DEFINITION, "ids": [str(e) for e in entity_ids]},
    )
    out: dict[UUID, list[float]] = {}
    for row in result.fetchall():
        vec = _parse_pgvector(row[1])
        if vec:
            out[UUID(str(row[0]))] = vec
    return out


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
