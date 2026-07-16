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
    _prediction_linking(ctx)
    _internal_jwt_probe(ctx)
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
            "fund_emb_num": "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) "
            "FROM entity_embedding_state WHERE view_type='fundamentals_ohlcv'",
            "fund_emb_den": "SELECT count(*) FROM entity_embedding_state WHERE view_type='fundamentals_ohlcv'",
            "view_stamped": "SELECT string_agg(view_type||':'||stamped||':'||wtext,',') FROM "
            "(SELECT view_type, count(*) FILTER (WHERE last_refreshed_at IS NOT NULL) stamped, "
            "count(*) FILTER (WHERE source_text IS NOT NULL AND source_text!='') wtext "
            "FROM entity_embedding_state GROUP BY view_type) t",
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

    # D1: fundamentals_ohlcv view was 100% empty (NULL embedding + empty
    # source_text) while last_refreshed_at was current — the KG→market-data
    # internal-JWT was rejected (see _internal_jwt_probe), so no fundamentals text
    # was ever built. Assert this specific view is actually embedded.
    R.floor(
        SVC,
        "fundamentals_ohlcv embedding coverage %",
        H.pct(q["fund_emb_num"], q["fund_emb_den"]),
        T.KG_FUND_OHLCV_EMBED_WARN,
        unit="%",
    )
    _stamped_but_empty(R, q["view_stamped"])
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


def _stamped_but_empty(R: H.Report, encoded: str) -> None:
    """Generic silent-worker anti-pattern across ALL embedding view_types.

    Encoded as `view_type:stamped:with_text,...`. A view_type whose worker
    stamped last_refreshed_at on many rows but left source_text empty on most of
    them is the "reports success, persists nothing" failure (D1's signature). We
    flag any such view_type, not just fundamentals_ohlcv, so a NEW view that
    regresses the same way is caught automatically.
    """
    offenders: list[str] = []
    for part in (encoded or "").split(","):
        bits = part.split(":")
        if len(bits) != 3:
            continue
        vt, stamped_s, wtext_s = bits
        stamped, wtext = H.as_int(stamped_s, 0), H.as_int(wtext_s, 0)
        if stamped < T.KG_STAMPED_MIN_ROWS:
            continue
        empty_frac = 1 - (wtext / stamped)
        if empty_frac > T.KG_STAMPED_EMPTY_FRACTION_FAIL:
            offenders.append(f"{vt}={wtext}/{stamped} have text ({round(empty_frac * 100)}% empty)")
    R.check(
        SVC,
        "no stamped-but-empty embedding view (worker persists text)",
        not offenders,
        "; ".join(offenders) if offenders else "all view_types write source_text where stamped",
    )


def _prediction_linking(ctx: Ctx) -> None:
    """PLAN-0056 prediction entity-linking consumer liveness.

    The bullish/bearish-against-a-company signal depends on two Kafka consumers
    (`kg-prediction-enriched-group`, `kg-prediction-move-group`). If they are
    absent or lagging, prediction temporal events + exposure polarity never
    populate (D6). Assert both groups exist, have members, and are not backed up.
    """
    R = ctx.report
    groups = set(H.kafka_groups())
    for g in T.KG_PREDICTION_GROUPS:
        if g not in groups:
            R.warn(SVC, f"prediction consumer group present ({g})", "group not registered")
            continue
        rows, lag, members = H.kafka_group_describe(g)
        alive = members > 0
        st = (
            H.FAIL
            if lag > T.KG_PREDICTION_LAG_FAIL
            else H.WARN
            if (lag > T.KG_PREDICTION_LAG_WARN or not alive)
            else H.PASS
        )
        R.add(SVC, f"prediction consumer live+bounded ({g})", st, f"members={members} lag={lag} rows={rows}")


def _internal_jwt_probe(ctx: Ctx) -> None:
    """Service→service internal-JWT signing works (D1 empty-key class).

    Reproduces the exact call the FundamentalsRefreshWorker makes: mint an
    X-Internal-JWT inside the KG pod with the worker's own key/dev-secret and hit
    market-data's authed screener. A 200 proves the trust path; a 401 means the
    signing key (KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY) is empty/mis-set and
    market-data is rejecting every call — which silently defers all
    fundamentals_ohlcv embeddings (the D1 root cause).
    """
    R = ctx.report
    pod = H.running_pod("app.kubernetes.io/name=knowledge-graph")
    if not pod:
        R.warn(SVC, "internal-JWT KG→market-data", "no Running knowledge-graph pod")
        return
    script = (
        "import os,json,urllib.request,urllib.error\n"
        "from observability.internal_jwt import mint_internal_jwt\n"
        "pem=os.environ.get('KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY','')\n"
        "base=os.environ.get('KNOWLEDGE_GRAPH_MARKET_DATA_BASE_URL','http://market-data:8003').rstrip('/')\n"
        f"tok=mint_internal_jwt(sub='system:prod-qa-jwt-probe',ttl_seconds=120,private_key_pem=pem,dev_hs256_secret='{T.JWT_PROBE_DEV_SECRET}')\n"
        "req=urllib.request.Request(base+'/api/v1/fundamentals/screen',"
        "data=json.dumps({'filters':[],'limit':1}).encode(),method='POST',"
        "headers={'X-Internal-JWT':tok,'Content-Type':'application/json'})\n"
        "try:\n"
        "    import urllib.request as u\n"
        "    r=u.urlopen(req,timeout=15)\n"
        "    print('PQA_JWT',r.status,bool(pem))\n"
        "except urllib.error.HTTPError as e:\n"
        "    print('PQA_JWT',e.code,bool(pem))\n"
        "except Exception as e:\n"
        "    print('PQA_JWT',-1,bool(pem),type(e).__name__)\n"
    )
    cmd = f"kubectl -n {H.NS} exec -i {pod} -- python3 - <<'PYEOF'\n{script}\nPYEOF"
    _, out = H.sh(cmd, timeout=60)
    line = next((ln for ln in out.splitlines() if ln.startswith("PQA_JWT")), "")
    parts = line.split()
    status = H.as_int(parts[1], -1) if len(parts) >= 2 else -1
    key_present = parts[2] if len(parts) >= 3 else "?"
    if status == 200:
        R.ok(SVC, "internal-JWT KG→market-data signs+verifies", f"200 (key_present={key_present})")
    elif status in (401, 403):
        R.fail(
            SVC,
            "internal-JWT KG→market-data signs+verifies",
            f"HTTP {status} — signing key empty/mis-set, market-data rejects (D1 embed-defer)",
        )
    else:
        R.warn(SVC, "internal-JWT KG→market-data signs+verifies", f"probe inconclusive: {line[:80] or out[-80:]}")


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
