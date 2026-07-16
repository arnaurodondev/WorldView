"""Granular functional checks for knowledge-graph (S7 / intelligence_db).

Covers: entity resolution + grounded facts (no fabrication signature), relation
density + type diversity, description/embedding coverage floors, AGE shadow-sync
liveness (vertex count + a real path query), evidence-promoter drain, temporal
events, and the PLAN-0056 prediction-market entity-linking path (which — as of
2026-07-15 — is a known prod gap: the prediction-enriched/move consumers are not
deployed, so prediction temporal events + exposure polarity are empty).
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx
from . import api_json, assert_api_ok

SVC = "knowledge-graph"


def run(ctx: Ctx) -> None:
    _db(ctx)
    _age(ctx)
    _api(ctx)


def _db(ctx: Ctx) -> None:
    R = ctx.report
    q = H.psql_many(
        "intelligence_db",
        {
            "entities": "SELECT count(*) FROM canonical_entities",
            "fin": "SELECT count(*) FROM canonical_entities WHERE entity_type='financial_instrument'",
            "desc": "SELECT count(*) FILTER (WHERE description IS NOT NULL AND length(description)>0) FROM canonical_entities",
            "rel_active": "SELECT count(*) FROM relations WHERE valid_to IS NULL",
            "rel_types": "SELECT count(DISTINCT canonical_type) FROM relations",
            "emb_num": "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) FROM entity_embedding_state",
            "emb_den": "SELECT count(*) FROM entity_embedding_state",
            "temporal": "SELECT count(*) FROM temporal_events",
            "pred_events": "SELECT count(*) FROM temporal_events WHERE event_type='prediction'",
            "exposures": "SELECT count(*) FROM entity_event_exposures",
            "exp_polarity": "SELECT count(*) FILTER (WHERE polarity IS NOT NULL) FROM entity_event_exposures",
            "evid_total": "SELECT count(*) FROM relation_evidence_raw",
            "evid_promoted": "SELECT count(*) FILTER (WHERE promoted_at IS NOT NULL) FROM relation_evidence_raw",
            "path_insights": "SELECT count(*) FROM path_insights",
            "graph_edges": "SELECT count(*) FROM public.graph_edges",
        },
    )
    R.floor(SVC, "canonical_entities", H.as_int(q["entities"]), T.KG_ENTITIES_FLOOR)
    R.floor(SVC, "financial_instrument entities", H.as_int(q["fin"]), T.KG_FIN_INSTRUMENTS_FLOOR)
    R.floor(SVC, "description coverage %", H.pct(q["desc"], q["entities"]), T.KG_DESC_COVERAGE_WARN, unit="%")
    R.floor(SVC, "embedding coverage %", H.pct(q["emb_num"], q["emb_den"]), T.KG_EMBED_COVERAGE_WARN, unit="%")
    R.floor(SVC, "active relations", H.as_int(q["rel_active"]), T.KG_RELATIONS_FLOOR)
    R.floor(SVC, "distinct relation types", H.as_int(q["rel_types"]), T.KG_RELATION_TYPES_FLOOR)
    R.floor(SVC, "temporal_events", H.as_int(q["temporal"]), T.KG_TEMPORAL_EVENTS_FLOOR)
    R.floor(
        SVC,
        "evidence promoter drain %",
        H.pct(q["evid_promoted"], q["evid_total"]),
        T.KG_EVIDENCE_PROMOTED_WARN,
        unit="%",
    )

    # Weird-path / relational-traversal materialisation liveness.
    R.check(
        SVC,
        "path_insights precomputed",
        H.as_int(q["path_insights"], 0) > 0,
        f"{q['path_insights']} rows (weird-connections feed)",
        soft=True,
    )
    R.check(
        SVC,
        "public.graph_edges matview populated",
        H.as_int(q["graph_edges"], 0) > 0,
        f"{q['graph_edges']} edges (relational traversal)",
        soft=True,
    )

    # PLAN-0056 prediction entity-linking (bullish/bearish 'against a company').
    R.check(
        SVC,
        "prediction temporal events written",
        H.as_int(q["pred_events"], 0) > 0,
        f"{q['pred_events']} prediction events (KG prediction-enriched consumer)",
        soft=True,
    )
    R.check(
        SVC,
        "exposure polarity populated",
        H.as_int(q["exp_polarity"], 0) > 0,
        f"{q['exp_polarity']}/{q['exposures']} exposures carry polarity",
        soft=True,
    )


def _age_count(match: str, ret_col: str) -> int:
    """Count rows of an AGE Cypher MATCH on worldview_graph.

    NOTE the `\\$\\$` escaping: this command reaches `/bin/sh -c` via the harness,
    and a bare `$$` would be expanded to the shell PID. Backslash-dollar inside
    the double-quoted psql arg survives as a literal `$$` for AGE's dollar-quote.
    The `SET search_path` prefix prints a `SET` tag, so we take the last all-digit
    line, not the first meaningful one.
    """
    sql = (
        f"LOAD 'age'; SET search_path=ag_catalog,public; "
        f"SELECT count(*) FROM cypher('worldview_graph', \\$\\$ {match} RETURN {ret_col} \\$\\$) as ({ret_col} agtype)"
    )
    _, out = H.kubectl(
        f'-n {H.INFRA_NS} exec {H.POSTGRES_POD} -c {H.POSTGRES_CONTAINER} -- psql -U postgres -d intelligence_db -tAc "{sql}"'
    )
    digits = [ln.strip() for ln in out.splitlines() if ln.strip().isdigit()]
    return H.as_int(digits[-1]) if digits else -1


def _age(ctx: Ctx) -> None:
    R = ctx.report
    # AGE shadow-sync liveness: vertex count via ag_catalog Cypher.
    R.floor(SVC, "AGE graph vertices (shadow sync)", _age_count("MATCH (n)", "n"), T.KG_AGE_VERTEX_FLOOR)
    # A real 1-hop path query returns edges — proves the graph is traversable.
    edges = _age_count("MATCH ()-[r]->()", "r")
    R.check(SVC, "AGE graph has edges", edges > 0, f"{edges} edges", soft=True)


def _api(ctx: Ctx) -> None:
    R = ctx.report
    ok, body = assert_api_ok(ctx, SVC, "graph/stats", "kg_stats")
    if ok and isinstance(body, dict):
        R.check(
            SVC,
            "graph/stats entity+relation counts sane",
            H.as_int(str(body.get("entity_count")), 0) >= T.KG_ENTITIES_FLOOR
            and H.as_int(str(body.get("relation_count")), 0) >= T.KG_RELATIONS_FLOOR,
            f"entities={body.get('entity_count')} relations={body.get('relation_count')}",
        )

    # Grounded golden entity: Apple resolves with correct, non-fabricated facts.
    ok, body = assert_api_ok(ctx, SVC, "entity lookup (AAPL)", "kg_lookup")
    ok2, ent = assert_api_ok(ctx, SVC, "entity detail (AAPL)", "kg_entity")
    if ok2 and isinstance(ent, dict):
        name_ok = T.KG_GOLDEN_NAME_SUBSTR.lower() in str(ent.get("canonical_name", "")).lower()
        type_ok = ent.get("entity_type") == "financial_instrument"
        ticker_ok = ent.get("ticker") == T.KG_GOLDEN_TICKER
        isin_ok = ent.get("isin") == T.KG_GOLDEN_ISIN  # grounded fact, not fabricated
        R.check(
            SVC,
            "AAPL entity grounded facts (name/type/ticker/isin)",
            name_ok and type_ok and ticker_ok and isin_ok,
            f"name={ent.get('canonical_name')} type={ent.get('entity_type')} ticker={ent.get('ticker')} isin={ent.get('isin')}",
        )

    ok, body = assert_api_ok(ctx, SVC, "entity intelligence narrative (AAPL)", "kg_intel")
    if ok and isinstance(body, dict):
        R.check(
            SVC,
            "intelligence has health_score",
            isinstance(body.get("health_score"), (int, float)),
            f"health_score={body.get('health_score')}",
            soft=True,
        )

    ok, body = assert_api_ok(ctx, SVC, "entity graph (AAPL)", "kg_graph")
    if ok and isinstance(body, dict):
        center = body.get("center") or {}
        R.check(
            SVC,
            "entity graph centred on AAPL",
            str(center.get("ticker")) == T.KG_GOLDEN_TICKER,
            f"center ticker={center.get('ticker')}",
        )

    assert_api_ok(ctx, SVC, "temporal-events feed", "kg_temporal")
    # similar / weird / predictions may legitimately be empty on a young graph → status-only.
    # 422 here is a valid semantic response ("no view-embedding for this entity"),
    # so the route is proven up by either 200 or a 4xx validation body.
    st, _ = api_json(ctx, "kg_similar")
    R.check(SVC, "similar-entities route up", st in (200, 422), f"HTTP {st}", soft=True)
    st, _ = api_json(ctx, "kg_weird")
    R.check(SVC, "weird-connections route up", st == 200, f"HTTP {st}", soft=True)
    st, _ = api_json(ctx, "kg_predictions")
    R.check(SVC, "entity predictions route up", st == 200, f"HTTP {st}", soft=True)

    # Async description-gen trigger: 200/202 enqueued, 429 rate-limited — both healthy.
    row = ctx.api_row("kg_refresh")
    if row:
        s = row.get("status")
        R.check(SVC, "description-gen trigger healthy", s in (200, 202, 429), f"HTTP {s}", soft=(s == 429))
