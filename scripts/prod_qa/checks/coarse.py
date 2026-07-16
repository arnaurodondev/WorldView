"""Coarse / general platform health — the 'is everything up?' layer.

Covers the invariants that must hold for ANY healthy deploy regardless of
per-service data: pods Ready, no crashloops, expected workloads present,
migrations at head (with stale-image vs pending-migrate disambiguation), every
DLQ empty (Kafka topics AND Postgres tables), consumer groups alive, outbox
dispatchers draining, schema-registry compat, TLS/edge, MinIO buckets.
"""

from __future__ import annotations

import json

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx


def run(ctx: Ctx) -> None:
    R = ctx.report
    _pods_and_workloads(R)
    _migrations(R)
    _dlq_topics(R)
    _dlq_db_tables(R)
    _consumer_groups(R)
    _outbox_dispatchers(R)
    _schema_registry(R)
    _edge_and_tls(R)
    _minio(R)


def _pods_and_workloads(R: H.Report) -> None:
    for ns in (H.INFRA_NS, H.NS, H.MON_NS):
        jobs = H.job_pod_names(ns)
        not_ready, crash = [], []
        for name, ready, status, restarts in H.pods(ns):
            if name in jobs:  # transient Job/CronJob pod — normal lifecycle
                continue
            if status != "Running":
                not_ready.append(f"{name}={status}")
            elif "/" in ready and ready.split("/")[0] != ready.split("/")[1]:
                not_ready.append(f"{name}={ready}")
            n = H.as_int(restarts.split("(")[0])
            if n > T.POD_RESTART_WARN:
                crash.append(f"{name}={restarts}")
        R.check("infra", f"pods Ready ({ns})", not not_ready, ", ".join(not_ready) or "all Running/Ready")
        if crash:
            R.warn("infra", f"crashloops ({ns})", ", ".join(crash))

    # Expected long-running worldview workloads all present.
    _, out = H.kubectl(f"-n {H.NS} get deploy --no-headers -o custom-columns=NAME:.metadata.name")
    present = {ln.strip() for ln in out.splitlines() if ln.strip()}
    missing = [w for w in T.EXPECTED_WORLDVIEW_WORKLOADS if w not in present]
    R.check(
        "infra",
        "expected worldview workloads present",
        not missing,
        f"missing: {missing}" if missing else f"{len(T.EXPECTED_WORLDVIEW_WORKLOADS)} core deployments",
    )


def _migrations(R: H.Report) -> None:
    for db, expected in sorted(T.EXPECTED_ALEMBIC_HEADS.items()):
        current = H.psql_scalar(db, "SELECT version_num FROM alembic_version")
        if not current:
            R.warn("infra", f"migrations {db}", "no alembic_version row (skipped)")
            continue
        if current == expected:
            R.ok("infra", f"migrations {db}", f"@ {current} (head)")
            continue
        dep = T.DB_TO_DEPLOYMENT.get(db)
        image_head = _image_alembic_head(dep) if dep else ""
        if image_head and image_head != expected:
            detail = f"STALE IMAGE: pod bundles {image_head}, release head {expected} (db@{current})"
        elif image_head and current != image_head:
            detail = f"migrate Job PENDING: db@{current} but image bundles {image_head}"
        else:
            detail = f"db@{current}, release head {expected} (migrate pending or migrator image stale)"
        R.fail("infra", f"migrations {db}", detail)


def _image_alembic_head(dep: str) -> str:
    pod = H.running_pod(f"app.kubernetes.io/name={dep}")
    if not pod:
        return ""
    _, out = H.kubectl(f"-n {H.NS} exec {pod} -- sh -c 'cd /app 2>/dev/null && alembic heads 2>/dev/null'")
    for ln in out.splitlines():
        if "(head)" in ln and ln.strip().split():
            return ln.strip().split()[0]
    return ""


def _dlq_topics(R: H.Report) -> None:
    offs = H.kafka_topic_offsets(T.DLQ_TOPICS)
    hot = {t: n for t, n in offs.items() if n > 0}
    R.check(
        "infra",
        "Kafka DLQ topics empty",
        not hot,
        ", ".join(f"{t}={n}" for t, n in hot.items()) or f"all {len(T.DLQ_TOPICS)} DLQs = 0",
    )


def _dlq_db_tables(R: H.Report) -> None:
    dbs = ["nlp_db", "content_store_db", "content_ingestion_db", "alert_db", "intelligence_db"]
    total, recent, worst = 0, 0, ""
    for db in dbs:
        res = H.psql_many(
            db,
            {
                "unresolved": "SELECT count(*) FROM dead_letter_queue WHERE resolved_at IS NULL",
                "recent": "SELECT count(*) FROM dead_letter_queue WHERE resolved_at IS NULL AND created_at > now() - interval '1 hour'",
            },
            timeout=40,
        )
        un = H.as_int(res["unresolved"], 0)
        rn = H.as_int(res["recent"], 0)
        total += un
        recent += rn
        if un and un > H.as_int(worst.split("=")[-1].split()[0]) if worst else un:
            worst = f"{db}={un}(+{rn}/h)"
    status = (
        H.FAIL
        if (total >= T.DLQ_DB_BACKLOG_FAIL or recent >= T.DLQ_DB_RATE_FAIL)
        else H.WARN
        if total >= T.DLQ_DB_BACKLOG_WARN
        else H.PASS
    )
    R.add(
        "infra",
        "Postgres DLQ tables bounded",
        status,
        f"{total} unresolved (+{recent}/h); worst {worst}" if total else "all DB DLQ tables drained",
    )


def _consumer_groups(R: H.Report) -> None:
    groups = H.kafka_groups()
    if not groups:
        R.warn("infra", "kafka consumer groups", "could not list groups")
        return
    real = [g for g in groups if not g.startswith("probe")]
    missing = [g for g in T.EXPECTED_CONSUMER_GROUPS if g not in real]
    R.check(
        "infra",
        "expected consumer groups present",
        not missing,
        f"missing: {missing}" if missing else f"{len(T.EXPECTED_CONSUMER_GROUPS)} core groups present",
    )

    # Describe only the core expected groups present (each describe is a
    # tunnelled kubectl exec — bounding the set keeps the run tractable).
    dead, worst = [], ("", 0)
    for g in [g for g in T.EXPECTED_CONSUMER_GROUPS if g in real]:
        rows, lag, members = H.kafka_group_describe(g)
        if rows > 0 and members == 0:
            dead.append(g)
        if lag > worst[1]:
            worst = (g, lag)
    R.check(
        "infra",
        "consumer groups have live members",
        not dead,
        f"{len(dead)} dead (0 members): {dead[:5]}" if dead else f"all {len(real)} groups have members",
    )
    grp, lag = worst
    status = H.FAIL if lag > T.KAFKA_LAG_FAIL else H.WARN if lag > T.KAFKA_LAG_WARN else H.PASS
    R.add("infra", "consumer lag bounded", status, f"max {grp}={lag}")


def _outbox_dispatchers(R: H.Report) -> None:
    stuck, worst = 0, ""
    for db in (
        "portfolio_db",
        "intelligence_db",
        "nlp_db",
        "market_data_db",
        "content_store_db",
        "alert_db",
        "content_ingestion_db",
        "ingestion_db",
    ):
        n = H.as_int(
            H.psql_scalar(
                db,
                "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL AND created_at < now() - interval '10 minutes'",
            ),
            -1,
        )
        if n > 0:
            stuck += n
            worst = f"{db}={n}"
    status = H.FAIL if stuck > T.OUTBOX_STUCK_FAIL else H.WARN if stuck else H.PASS
    R.add(
        "infra",
        "outbox dispatchers draining",
        status,
        f"{stuck} undispatched >10m ({worst})" if stuck else "all outboxes drained",
    )


def _schema_registry(R: H.Report) -> None:
    code, out = H.sh("curl -s --max-time 10 http://schema-registry.infra.svc:8081/config")
    if code != 0 or "compatibilityLevel" not in (out or ""):
        # Not reachable from the harness host (curl runs locally) — non-fatal.
        R.warn("infra", "schema-registry compat", f"could not read /config ({str(out)[:60]})")
        return
    try:
        level = json.loads(out).get("compatibilityLevel", "?")
    except ValueError:
        level = "?"
    R.check("infra", "schema-registry compat FULL", level in T.SCHEMA_REGISTRY_SAFE_COMPAT, f"global={level}")


def _edge_and_tls(R: H.Report) -> None:
    host = H.PUBLIC_HOST
    _, redir = H.sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://{host}/healthz")
    R.check("edge", "HTTP :80 → 301 redirect", redir.strip() == "301", f"got {redir.strip()}")
    _, hc = H.sh(
        f"curl -s -o /dev/null -w '%{{http_code}}:%{{ssl_verify_result}}' --max-time 12 https://{host}/healthz"
    )
    parts = hc.strip().split(":")
    ok = parts[0] == "200" and (len(parts) < 2 or parts[1] == "0")
    R.check("edge", "HTTPS /healthz 200 + valid TLS", ok, hc.strip())
    _, un = H.sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{host}/v1/market/top-movers")
    R.check("edge", "unauth /v1 data → 401/403", un.strip() in ("401", "403"), f"got {un.strip()}")
    for path in ("/metrics", "/openapi.json"):
        _, ic = H.sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{host}{path}")
        R.check("edge", f"internal route blocked {path}", ic.strip() in ("401", "403", "404"), f"got {ic.strip()}")
    _, cert = H.kubectl(f"-n {H.NS} get certificate api-tls -o jsonpath='{{.status.conditions[0].status}}'")
    R.check("edge", "TLS cert (api-tls) issued", cert.strip() == "True", f"ready={cert.strip()}")


def _minio(R: H.Report) -> None:
    mp = H.running_pod("app=minio", H.INFRA_NS) or ""
    if not mp:
        _, out = H.kubectl(f"-n {H.INFRA_NS} get pods --no-headers")
        for ln in out.splitlines():
            if ln.startswith("minio-") and "Running" in ln:
                mp = ln.split()[0]
                break
    if not mp:
        R.warn("infra", "MinIO buckets", "minio pod not found")
        return
    _, out = H.kubectl(
        f"-n {H.INFRA_NS} exec {mp} -- sh -c "
        f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; mc ls l/ 2>/dev/null\''
    )
    present = {ln.split()[-1].rstrip("/") for ln in out.splitlines() if ln.strip()}
    expected = ["market-data", "content-data", "intelligence-data", "rag-data", "worldview-bronze", "worldview-silver"]
    missing = [b for b in expected if b not in present]
    R.check(
        "infra",
        "MinIO core buckets present",
        not missing,
        f"missing: {missing}" if missing else f"{len(present)} buckets",
    )
