#!/usr/bin/env python3
"""Merge same-ticker duplicate canonical_entities into one survivor (BP-459 Phase 3).

ROOT CAUSE (see docs/BUG_PATTERNS.md BP-459): two minting pipelines —
  (A) the market-data instrument-seeding path (knowledge-graph
      ``InstrumentEntityConsumer``), which anchors ``entity_id == instrument_id``
      (M-017) and writes ``exchange``; and
  (B) the news/provisional promotion path (``persist_enrichment``), which minted
      a fresh ticker-bearing canonical with NULL exchange —
each created a canonical_entities row for the SAME ticker without consulting the
other.  None of the dedup guards keyed on the ticker, so e.g. "Shell Plc"
(ticker=SHEL, exchange=NULL, 82 mentions) and "Shell PLC ADR" (ticker=SHEL,
exchange=US, the tradable instrument, 0 mentions) coexist.  Live count
2026-06-12: 451 tickers with duplicate canonicals / 593 excess rows.

This script consolidates each same-ticker cluster of ``financial_instrument``
canonicals into ONE survivor and re-points every reference.

SURVIVOR RULE (deterministic, documented):
  1. Prefer the canonical whose ``entity_id`` exists in
     ``market_data_db.instruments`` (the M-017-anchored tradable instrument) —
     this is the row the instrument page and portfolio resolve to, so news must
     flow INTO it.
  2. If none (or more than one) is instrument-anchored, prefer the row WITH a
     non-NULL ``exchange``.
  3. Tie-break: oldest ``created_at`` (most-referenced, most-stable id).

RE-POINTING (idempotent, transactional per cluster):
  intelligence_db:  relations(subject/object), relation_evidence_raw(subject/object),
                    claims.subject_entity_id, events.subject_entity_id,
                    event_entities, entity_event_exposures, entity_narrative_versions,
                    path_insights.anchor_entity_id, path_insight_jobs,
                    llm_usage_log, ticker_aliases, entity_aliases (move + dedup),
                    entity_embedding_state (survivor keeps its own rows).
  nlp_db:           entity_mentions.resolved_entity_id.
After re-pointing, the loser canonical rows are DELETED (their entity_aliases /
embedding_state cascade or are merged first).

The script is SAFE TO RE-RUN: after a successful pass a ticker has exactly one
financial_instrument canonical, so the cluster query returns nothing for it.

Usage:
    python scripts/data/merge_ticker_duplicates.py            # platform-wide, all dup tickers
    python scripts/data/merge_ticker_duplicates.py --ticker SHEL
    python scripts/data/merge_ticker_duplicates.py --dry-run  # report only, no writes
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import psycopg

# Default DSNs target the local docker-compose Postgres (single instance, two
# logical DBs).  Override via env for other environments.
_INTEL_DSN = os.environ.get(
    "INTELLIGENCE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)
_NLP_DSN = os.environ.get(
    "NLP_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/nlp_db",
)
_MARKET_DSN = os.environ.get(
    "MARKET_DATA_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/market_data_db",
)

# intelligence_db tables to re-point that have NO unique constraint on the
# re-pointed column(s): a plain UPDATE is always safe.  Collision-prone tables
# (relations, event_entities, entity_event_exposures, ticker_aliases,
# entity_aliases) are handled with bespoke delete-then-repoint logic below.
_INTEL_REPOINTS: tuple[tuple[str, str], ...] = (
    ("relation_evidence_raw", "subject_entity_id"),
    ("relation_evidence_raw", "object_entity_id"),
    ("claims", "subject_entity_id"),
    ("events", "subject_entity_id"),
    ("path_insights", "anchor_entity_id"),
    ("llm_usage_log", "entity_id"),
)


@dataclass
class Cluster:
    ticker: str
    members: list[dict[str, object]]  # entity_id, canonical_name, exchange, created_at


def _fetch_clusters(intel: psycopg.Connection, ticker: str | None) -> list[Cluster]:
    """Return same-ticker financial_instrument clusters with count > 1."""
    # Fixed SQL template with a single ``{clause}`` slot replaced by one of two
    # constant strings — the ticker value is always a bound parameter, never
    # spliced into the text, so there is no injection surface.
    base = """
SELECT ce.ticker, ce.entity_id, ce.canonical_name, ce.exchange, ce.created_at
FROM canonical_entities ce
WHERE ce.ticker IS NOT NULL
  AND ce.entity_type = 'financial_instrument'
  {clause}
  AND ce.ticker IN (
        SELECT ticker FROM canonical_entities
        WHERE ticker IS NOT NULL AND entity_type = 'financial_instrument'
        GROUP BY ticker HAVING count(*) > 1
  )
ORDER BY ce.ticker, ce.created_at
"""
    sql = base.replace("{clause}", "AND ce.ticker = %(ticker)s" if ticker else "")
    rows = intel.execute(sql, {"ticker": ticker} if ticker else {}).fetchall()
    by_ticker: dict[str, list[dict[str, object]]] = {}
    for tkr, eid, name, exch, created in rows:
        by_ticker.setdefault(tkr, []).append(
            {"entity_id": eid, "canonical_name": name, "exchange": exch, "created_at": created},
        )
    return [Cluster(ticker=t, members=m) for t, m in by_ticker.items() if len(m) > 1]


def _instrument_anchored_ids(market: psycopg.Connection, entity_ids: list[str]) -> set[str]:
    """Return the subset of entity_ids that are real instruments in market_data_db."""
    if not entity_ids:
        return set()
    rows = market.execute(
        "SELECT id FROM instruments WHERE id = ANY(%(ids)s)",
        {"ids": entity_ids},
    ).fetchall()
    return {str(r[0]) for r in rows}


def _choose_survivor(cluster: Cluster, anchored: set[str]) -> dict[str, object]:
    """Apply the documented survivor rule."""
    members = cluster.members
    anchored_members = [m for m in members if str(m["entity_id"]) in anchored]
    if len(anchored_members) == 1:
        return anchored_members[0]
    pool = anchored_members or members
    with_exchange = [m for m in pool if m["exchange"]]
    if len(with_exchange) == 1:
        return with_exchange[0]
    pool = with_exchange or pool
    # Tie-break: oldest created_at.
    return min(pool, key=lambda m: m["created_at"])  # type: ignore[arg-type,return-value]


def _merge_cluster(
    intel: psycopg.Connection,
    nlp: psycopg.Connection,
    cluster: Cluster,
    survivor_id: str,
    loser_ids: list[str],
    *,
    dry_run: bool,
) -> dict[str, int]:
    """Re-point all references from loser_ids → survivor_id and delete losers.

    Runs as ONE transaction on each connection.  Returns per-surface row counts.
    """
    counts: dict[str, int] = {}

    p = {"survivor": survivor_id, "losers": loser_ids}

    # ── relations: first drop loser rows whose effective triple would become a
    #     SELF-LOOP (subject==object after re-point, e.g. a loser→survivor or
    #     loser→loser edge).  These violate chk_relations_no_self_loop (BP-385)
    #     and carry no information once the endpoints are the same entity.
    intel.execute(
        """
DELETE FROM relations r
WHERE (r.subject_entity_id = ANY(%(losers)s) OR r.object_entity_id = ANY(%(losers)s))
  AND (CASE WHEN r.subject_entity_id = ANY(%(losers)s) THEN %(survivor)s::uuid
            ELSE r.subject_entity_id END)
    = (CASE WHEN r.object_entity_id = ANY(%(losers)s) THEN %(survivor)s::uuid
            ELSE r.object_entity_id END)
""",
        p,
    )

    # ── relations (uidx_relations_triple: subject_entity_id, canonical_type,
    #     object_entity_id) — BOTH endpoints may be re-pointed.  We map any
    #     endpoint that is a loser to the survivor (the "effective" triple),
    #     then DELETE every row whose effective triple is not the FIRST
    #     occurrence — this collapses duplicates that would otherwise violate
    #     uidx_relations_triple after re-pointing.  Survivor-only rows keep
    #     their natural triple and rank first, so they are never deleted.  The
    #     remaining loser rows are then re-pointed.
    intel.execute(
        """
WITH eff AS (
    SELECT r.ctid AS cid,
           (r.subject_entity_id = ANY(%(losers)s) OR r.object_entity_id = ANY(%(losers)s)) AS is_loser,
           (CASE WHEN r.subject_entity_id = ANY(%(losers)s) THEN %(survivor)s::uuid
                 ELSE r.subject_entity_id END) AS subj,
           r.canonical_type AS ct,
           (CASE WHEN r.object_entity_id = ANY(%(losers)s) THEN %(survivor)s::uuid
                 ELSE r.object_entity_id END) AS obj
    FROM relations r
    WHERE r.subject_entity_id = ANY(%(losers)s)
       OR r.object_entity_id = ANY(%(losers)s)
       OR r.subject_entity_id = %(survivor)s::uuid
       OR r.object_entity_id = %(survivor)s::uuid
),
ranked AS (
    -- Keep a SURVIVOR-owned row (is_loser=false) as the rn=1 representative
    -- whenever one shares the effective triple, so a loser row is never the
    -- kept duplicate against an existing survivor row (which the loser-only
    -- DELETE could not remove and would then collide with on re-point).
    SELECT cid, is_loser,
           row_number() OVER (PARTITION BY subj, ct, obj ORDER BY is_loser ASC, cid) AS rn
    FROM eff
)
DELETE FROM relations r
USING ranked
WHERE r.ctid = ranked.cid AND ranked.rn > 1 AND ranked.is_loser
""",
        p,
    )
    for col in ("subject_entity_id", "object_entity_id"):
        res = intel.execute(
            f"UPDATE relations SET {col} = %(survivor)s WHERE {col} = ANY(%(losers)s)",  # noqa: S608
            p,
        )
        if res.rowcount:
            counts[f"relations.{col}"] = counts.get(f"relations.{col}", 0) + res.rowcount

    # ── event_entities (event_id, entity_id[, role]) — drop loser rows that
    #     collide with a survivor row for the same event, then re-point.
    intel.execute(
        """
DELETE FROM event_entities le
WHERE le.entity_id = ANY(%(losers)s)
  AND (
        -- collide with a survivor row on the PK (event_id, entity_id) ...
        EXISTS (
            SELECT 1 FROM event_entities se
            WHERE se.entity_id = %(survivor)s
              AND se.event_id = le.event_id
        )
        -- ... or with ANOTHER loser row that ranks ahead for the same event
        -- (so only one row per event_id survives the re-point onto survivor).
        OR EXISTS (
            SELECT 1 FROM event_entities oe
            WHERE oe.entity_id = ANY(%(losers)s)
              AND oe.event_id = le.event_id
              AND oe.ctid < le.ctid
        )
  )
""",
        p,
    )
    res = intel.execute(
        "UPDATE event_entities SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        p,
    )
    if res.rowcount:
        counts["event_entities.entity_id"] = res.rowcount

    # ── entity_event_exposures (event_id, entity_id, exposure_type) ──────────
    intel.execute(
        """
DELETE FROM entity_event_exposures le
WHERE le.entity_id = ANY(%(losers)s)
  AND (
        EXISTS (
            SELECT 1 FROM entity_event_exposures se
            WHERE se.entity_id = %(survivor)s
              AND se.event_id = le.event_id
              AND se.exposure_type = le.exposure_type
        )
        OR EXISTS (
            SELECT 1 FROM entity_event_exposures oe
            WHERE oe.entity_id = ANY(%(losers)s)
              AND oe.event_id = le.event_id
              AND oe.exposure_type = le.exposure_type
              AND oe.ctid < le.ctid
        )
  )
""",
        p,
    )
    res = intel.execute(
        "UPDATE entity_event_exposures SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        p,
    )
    if res.rowcount:
        counts["entity_event_exposures.entity_id"] = res.rowcount

    # ── ticker_aliases (unique on upper(alias) WHERE is_current) — drop loser
    #     current-aliases that collide with a survivor current-alias, re-point rest.
    intel.execute(
        """
DELETE FROM ticker_aliases la
WHERE la.entity_id = ANY(%(losers)s)
  AND la.is_current = true
  AND (
        EXISTS (
            SELECT 1 FROM ticker_aliases sa
            WHERE sa.entity_id = %(survivor)s
              AND sa.is_current = true
              AND upper(sa.alias) = upper(la.alias)
        )
        OR EXISTS (
            SELECT 1 FROM ticker_aliases oa
            WHERE oa.entity_id = ANY(%(losers)s)
              AND oa.is_current = true
              AND upper(oa.alias) = upper(la.alias)
              AND oa.ctid < la.ctid
        )
  )
""",
        p,
    )
    res = intel.execute(
        "UPDATE ticker_aliases SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        p,
    )
    if res.rowcount:
        counts["ticker_aliases.entity_id"] = res.rowcount

    # ── entity_narrative_versions (uq_entity_narrative_current: unique entity_id
    #     WHERE is_current) — the SURVIVOR's current narrative is authoritative.
    #     Demote any loser current-narrative to is_current=false (when the
    #     survivor already has one) BEFORE re-pointing so the version history is
    #     preserved without violating the partial-unique index.
    intel.execute(
        """
UPDATE entity_narrative_versions
SET is_current = false
WHERE entity_id = ANY(%(losers)s)
  AND is_current = true
  AND EXISTS (
        SELECT 1 FROM entity_narrative_versions s
        WHERE s.entity_id = %(survivor)s AND s.is_current = true
  )
""",
        p,
    )
    res = intel.execute(
        "UPDATE entity_narrative_versions SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        p,
    )
    if res.rowcount:
        counts["entity_narrative_versions.entity_id"] = res.rowcount

    # ── path_insight_jobs (uq_path_insight_jobs_active: unique entity_id WHERE
    #     status IN ('pending','running')) — these are regenerable scheduling
    #     rows.  Drop loser ACTIVE jobs that collide with a survivor (or another
    #     loser) active job, then re-point the rest.
    intel.execute(
        """
DELETE FROM path_insight_jobs lj
WHERE lj.entity_id = ANY(%(losers)s)
  AND lj.status IN ('pending', 'running')
  AND (
        EXISTS (
            SELECT 1 FROM path_insight_jobs sj
            WHERE sj.entity_id = %(survivor)s
              AND sj.status IN ('pending', 'running')
        )
        OR EXISTS (
            SELECT 1 FROM path_insight_jobs oj
            WHERE oj.entity_id = ANY(%(losers)s)
              AND oj.status IN ('pending', 'running')
              AND oj.ctid < lj.ctid
        )
  )
""",
        p,
    )
    res = intel.execute(
        "UPDATE path_insight_jobs SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        p,
    )
    if res.rowcount:
        counts["path_insight_jobs.entity_id"] = res.rowcount

    # ── plain re-points (no unique constraint on the column) ─────────────────
    for table, col in _INTEL_REPOINTS:
        res = intel.execute(
            f"UPDATE {table} SET {col} = %(survivor)s "  # noqa: S608 — table/col from a fixed allowlist
            f"WHERE {col} = ANY(%(losers)s)",
            p,
        )
        if res.rowcount:
            counts[f"{table}.{col}"] = res.rowcount

    # entity_aliases: move loser aliases to survivor, skipping any that would
    # collide with an alias the survivor already owns (per-entity + cross-entity
    # unique indexes).  Aliases that collide are dropped (the survivor already
    # has an equivalent), the rest are re-pointed.
    intel.execute(
        """
DELETE FROM entity_aliases la
WHERE la.entity_id = ANY(%(losers)s)
  AND la.is_active = true
  AND (
        -- collide with a survivor alias on the per-entity unique key
        -- (entity_id, normalized_alias_text, alias_type) WHERE is_active ...
        EXISTS (
            SELECT 1 FROM entity_aliases sa
            WHERE sa.entity_id = %(survivor)s
              AND sa.is_active = true
              AND sa.normalized_alias_text = la.normalized_alias_text
              AND sa.alias_type = la.alias_type
        )
        -- ... or with ANOTHER loser alias that ranks ahead (so two losers'
        -- identical aliases don't both re-point onto the survivor).
        OR EXISTS (
            SELECT 1 FROM entity_aliases oa
            WHERE oa.entity_id = ANY(%(losers)s)
              AND oa.is_active = true
              AND oa.normalized_alias_text = la.normalized_alias_text
              AND oa.alias_type = la.alias_type
              AND oa.ctid < la.ctid
        )
  )
""",
        {"survivor": survivor_id, "losers": loser_ids},
    )
    res = intel.execute(
        "UPDATE entity_aliases SET entity_id = %(survivor)s WHERE entity_id = ANY(%(losers)s)",
        {"survivor": survivor_id, "losers": loser_ids},
    )
    if res.rowcount:
        counts["entity_aliases.entity_id"] = res.rowcount

    # entity_embedding_state: survivor keeps its own rows; loser rows are
    # removed (they would violate the (entity_id, view_type) PK on re-point and
    # the survivor's embeddings are authoritative).
    intel.execute(
        "DELETE FROM entity_embedding_state WHERE entity_id = ANY(%(losers)s)",
        {"losers": loser_ids},
    )

    # narrative version FK on canonical_entities must be cleared before delete
    # if a loser pointed at its own narrative (avoid FK violation on DELETE).
    intel.execute(
        "UPDATE canonical_entities SET current_narrative_version_id = NULL " "WHERE entity_id = ANY(%(losers)s)",
        {"losers": loser_ids},
    )

    # Finally remove the loser canonical rows.
    res = intel.execute(
        "DELETE FROM canonical_entities WHERE entity_id = ANY(%(losers)s)",
        {"losers": loser_ids},
    )
    counts["canonical_entities.deleted"] = res.rowcount

    # ── nlp_db re-point: entity_mentions.resolved_entity_id ──────────────────
    res = nlp.execute(
        "UPDATE entity_mentions SET resolved_entity_id = %(survivor)s " "WHERE resolved_entity_id = ANY(%(losers)s)",
        {"survivor": survivor_id, "losers": loser_ids},
    )
    if res.rowcount:
        counts["entity_mentions.resolved_entity_id"] = res.rowcount

    if dry_run:
        intel.rollback()
        nlp.rollback()
    else:
        intel.commit()
        nlp.commit()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge same-ticker duplicate canonical_entities (BP-459).")
    ap.add_argument("--ticker", help="Limit to a single ticker (e.g. SHEL).")
    ap.add_argument("--dry-run", action="store_true", help="Report planned merges without writing.")
    args = ap.parse_args()

    with (
        psycopg.connect(_INTEL_DSN) as intel,
        psycopg.connect(_NLP_DSN) as nlp,
        psycopg.connect(_MARKET_DSN) as market,
    ):
        clusters = _fetch_clusters(intel, args.ticker)
        if not clusters:
            print("No same-ticker financial_instrument duplicates found. Nothing to merge.")
            return 0

        print(
            f"Found {len(clusters)} duplicate ticker cluster(s)"
            f"{' (DRY RUN — no writes)' if args.dry_run else ''}.\n"
        )

        total_excess = 0
        for cluster in clusters:
            all_ids = [str(m["entity_id"]) for m in cluster.members]
            anchored = _instrument_anchored_ids(market, all_ids)
            survivor = _choose_survivor(cluster, anchored)
            survivor_id = str(survivor["entity_id"])
            loser_ids = [i for i in all_ids if i != survivor_id]
            total_excess += len(loser_ids)

            print(
                f"[{cluster.ticker}] survivor={survivor_id} "
                f"({survivor['canonical_name']!r}, exchange={survivor['exchange']}, "
                f"instrument_anchored={survivor_id in anchored})"
            )
            for m in cluster.members:
                if str(m["entity_id"]) == survivor_id:
                    continue
                print(f"    merge loser {m['entity_id']} ({m['canonical_name']!r}, exchange={m['exchange']})")

            counts = _merge_cluster(intel, nlp, cluster, survivor_id, loser_ids, dry_run=args.dry_run)
            for surface, n in sorted(counts.items()):
                print(f"        {surface}: {n}")
            print()

        verb = "would be merged" if args.dry_run else "merged"
        print(f"Done. {total_excess} duplicate canonical row(s) {verb} across {len(clusters)} ticker(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
