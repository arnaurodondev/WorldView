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
    _restart_rates(R)
    _migrations(R)
    _dlq_topics(R)
    _dlq_db_tables(R)
    _consumer_groups(R)
    _outbox_dispatchers(R)
    _schema_registry(R)
    _edge_and_tls(R)
    _minio(R)
    _minio_lifecycle(R)
    _pvc_free_space(R)
    _referenced_secrets_exist(R)
    _internal_jwt_signing_keys(R)
    _synthetic_monitor(R)


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
    dead, worst = [], ("", 0, 0)  # (group, lag, members)
    for g in [g for g in T.EXPECTED_CONSUMER_GROUPS if g in real]:
        rows, lag, members = H.kafka_group_describe(g)
        if rows > 0 and members == 0:
            dead.append(g)
        if lag > worst[1]:
            worst = (g, lag, members)
    R.check(
        "infra",
        "consumer groups have live members",
        not dead,
        f"{len(dead)} dead (0 members): {dead[:5]}" if dead else f"all {len(real)} groups have members",
    )
    # Member-aware lag verdict: a group WITH live members and a large lag is a
    # draining backfill (the 195k-doc news backfill drove nlp-pipeline-group to
    # ~187k while consuming healthily) → WARN, not FAIL. FAIL only when the worst
    # group has NO members and real lag (a stopped consumer — a true regression),
    # or when lag is so extreme even a backfill can't explain it.
    grp, lag, members = worst
    if members == 0 and lag > T.KAFKA_LAG_FAIL:
        status = H.FAIL  # wedged/stopped consumer with a real backlog
    elif lag > T.KAFKA_LAG_FAIL_HARD:
        status = H.FAIL  # pathological even for a backfill
    elif lag > T.KAFKA_LAG_WARN:
        status = H.WARN
    else:
        status = H.PASS
    R.add("infra", "consumer lag bounded", status, f"max {grp}={lag} (members={members})")


def _outbox_dispatchers(R: H.Report) -> None:
    """Outbox drain health — aggregate AND per-table (with oldest-undispatched age).

    The aggregate sum can mask a single wedged service (content-ingestion hit
    111k undispatched in this session), and a low count of VERY OLD undispatched
    rows is a wedged dispatcher a >10m count-only check would miss — so each
    outbox table is judged on both its backlog size and its oldest-row age.
    """
    stuck, worst = 0, ""
    per_table_status = H.PASS
    per_table_detail: list[str] = []
    for db in T.OUTBOX_DBS:
        res = H.psql_many(
            db,
            {
                "aged": "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL "
                "AND created_at < now() - interval '10 minutes'",
                "undispatched": "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL",
                "oldest_min": "SELECT coalesce(round(extract(epoch from "
                "now()-min(created_at) FILTER (WHERE dispatched_at IS NULL))/60,1),0) FROM outbox_events",
            },
            timeout=40,
        )
        if res["undispatched"] == "":
            continue  # no outbox_events table in this DB → skip
        aged = H.as_int(res["aged"], 0)
        if aged > 0:
            stuck += aged
            worst = f"{db}={aged}"
        # Per-table: judge backlog size + oldest-undispatched age independently.
        undis = H.as_int(res["undispatched"], 0)
        age = H.as_float(res["oldest_min"], 0.0)
        st = H.PASS
        if undis >= T.OUTBOX_TABLE_BACKLOG_FAIL or age >= T.OUTBOX_AGE_FAIL_MIN:
            st = H.FAIL
        elif undis >= T.OUTBOX_TABLE_BACKLOG_WARN or age >= T.OUTBOX_AGE_WARN_MIN:
            st = H.WARN
        if st != H.PASS:
            per_table_detail.append(f"{db}={undis} rows/{age}m old")
            if st == H.FAIL or per_table_status != H.FAIL:
                per_table_status = st
    status = H.FAIL if stuck > T.OUTBOX_STUCK_FAIL else H.WARN if stuck else H.PASS
    R.add(
        "infra",
        "outbox dispatchers draining (aggregate)",
        status,
        f"{stuck} undispatched >10m ({worst})" if stuck else "all outboxes drained",
    )
    R.add(
        "infra",
        "outbox per-table backlog + age bounded",
        per_table_status,
        "; ".join(per_table_detail) if per_table_detail else f"all {len(T.OUTBOX_DBS)} outbox tables within floors",
    )


def _schema_registry(R: H.Report) -> None:
    """Global compatibility must be FULL_TRANSITIVE (forward+backward, all versions).

    schema-registry has no external Ingress, so a local `curl` cannot reach it —
    the previous host-side curl always WARNed 'unreachable' and never actually
    verified the invariant. We reach the ClusterIP from INSIDE the gateway pod (the
    same trust path producers use) and assert both /config and the subject count.
    """
    gw = H.gateway_pod()
    if not gw:
        R.warn("infra", "schema-registry compat FULL_TRANSITIVE", "no gateway pod to reach ClusterIP")
        return
    py = (
        "import urllib.request,json;"
        "b='http://schema-registry.infra.svc.cluster.local:8081';"
        "c=json.loads(urllib.request.urlopen(b+'/config',timeout=8).read());"
        "s=json.loads(urllib.request.urlopen(b+'/subjects',timeout=8).read());"
        "print('PQA_SR',c.get('compatibilityLevel','?'),len(s))"
    )
    _, out = H.kubectl(f'-n {H.NS} exec {gw} -- python3 -c "{py}"', timeout=40)
    line = next((ln for ln in out.splitlines() if ln.startswith("PQA_SR")), "")
    parts = line.split()
    if len(parts) < 3:
        R.warn("infra", "schema-registry compat FULL_TRANSITIVE", f"unreadable ({(line or out)[:60]})")
        return
    level, n_subjects = parts[1], H.as_int(parts[2], 0)
    R.check(
        "infra",
        "schema-registry compat FULL_TRANSITIVE",
        level in T.SCHEMA_REGISTRY_SAFE_COMPAT and n_subjects > 0,
        f"global={level}, {n_subjects} subjects",
    )


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
    _cert_expiry(R)


def _cert_expiry(R: H.Report) -> None:
    """TLS cert renewal runway. issued=True only proves cert-manager succeeded
    ONCE — a stuck renewal loop shows up solely as an approaching notAfter. Assert
    days-until-expiry so a lapsing cert is caught with time to intervene."""
    import datetime

    _, na = H.kubectl(f"-n {H.NS} get certificate api-tls -o jsonpath='{{.status.notAfter}}'")
    na = na.strip()
    if not na:
        R.warn("edge", "TLS cert (api-tls) expiry runway", "no notAfter on certificate (skipped)")
        return
    try:
        exp = datetime.datetime.fromisoformat(na.replace("Z", "+00:00"))
        days = round((exp - datetime.datetime.now(datetime.UTC)).total_seconds() / 86400, 1)
    except ValueError:
        R.warn("edge", "TLS cert (api-tls) expiry runway", f"unparseable notAfter: {na}")
        return
    st = H.FAIL if days < T.CERT_EXPIRY_FAIL_DAYS else H.WARN if days < T.CERT_EXPIRY_WARN_DAYS else H.PASS
    R.add("edge", "TLS cert (api-tls) expiry runway", st, f"{days}d until {na} (warn <{T.CERT_EXPIRY_WARN_DAYS}d)")


def _minio_pod() -> str:
    return H.running_pod("app=minio", H.INFRA_NS) or H.pod_by_prefix(H.INFRA_NS, "minio-")


def _minio(R: H.Report) -> None:
    mp = _minio_pod()
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


def _minio_lifecycle(R: H.Report) -> None:
    """Re-fetchable buckets MUST carry a lifecycle expiry rule (inode durability).

    bronze (raw firehose) + silver (canonical bodies) are derivable; without an
    expiry rule they grow unbounded and re-exhaust the inodes/bytes the P0 fix just
    reclaimed. `mc ilm ls` exits non-zero / prints 'does not exist' when a bucket
    has NO rule (silver was in exactly this state — the byte-check could never see
    it). Missing rule → WARN (a durability gap, not an active outage).
    """
    mp = _minio_pod()
    if not mp:
        R.warn("infra", "MinIO lifecycle rules", "minio pod not found")
        return
    buckets = " ".join(T.MINIO_LIFECYCLE_BUCKETS)
    _, out = H.kubectl(
        f"-n {H.INFRA_NS} exec {mp} -- sh -c "
        f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; '
        f'for b in {buckets}; do echo "PQA_ILM $b"; mc ilm ls l/$b 2>&1; done\'',
        timeout=40,
    )
    # A bucket section that shows an 'Enabled' rule row has expiry configured; one
    # whose section is empty or errors ('does not exist') has none.
    sections: dict[str, list[str]] = {}
    cur = ""
    for ln in out.splitlines():
        if ln.startswith("PQA_ILM "):
            cur = ln.split(None, 1)[1].strip()
            sections[cur] = []
        elif cur:
            sections[cur].append(ln)
    without = []
    for b in T.MINIO_LIFECYCLE_BUCKETS:
        body = "\n".join(sections.get(b, []))
        has_rule = "Enabled" in body or "Expiration" in body
        if not has_rule:
            without.append(b)
    R.check(
        "infra",
        "MinIO lifecycle expiry on re-fetchable buckets",
        not without,
        f"NO expiry rule (unbounded growth): {without}" if without else f"expiry set on {T.MINIO_LIFECYCLE_BUCKETS}",
        soft=True,
    )


def _internal_jwt_signing_keys(R: H.Report) -> None:
    """Every internal-JWT SIGNER pod must hold a non-empty signing key.

    An empty `*_INTERNAL_JWT_PRIVATE_KEY` makes every downstream call 401 silently
    (the D1 class). The KG→market-data mint probe proves ONE pair end-to-end; this
    generalises across ALL signers: scan each worldview pod's env for a
    `*_INTERNAL_JWT_PRIVATE_KEY` var and assert it is a real PEM (len ≥ floor), not
    empty / a placeholder. Auto-covers a new signer the day it ships.
    """
    empty: list[str] = []
    signers = 0
    # One Running pod per expected workload; check its signing-key env vars.
    for dep in T.EXPECTED_WORLDVIEW_WORKLOADS:
        pod = H.running_pod(f"app.kubernetes.io/name={dep}")
        if not pod:
            continue
        _, ev = H.kubectl(
            f"-n {H.NS} exec {pod} -- sh -c "
            f'\'for v in $(env | grep -oE "[A-Z_]*INTERNAL_JWT_PRIVATE_KEY" | sort -u); do '
            f'printf "%s %s\\n" "$v" "$(printenv "$v" | wc -c)"; done\'',
            timeout=30,
        )
        for row in ev.splitlines():
            f = row.split()
            if len(f) == 2 and f[0].endswith("INTERNAL_JWT_PRIVATE_KEY"):
                signers += 1
                if H.as_int(f[1], 0) < T.JWT_SIGNING_KEY_MIN_LEN:
                    empty.append(f"{dep}:{f[0]}={f[1]}B")
    R.check(
        "infra",
        "internal-JWT signing keys non-empty (all signers)",
        not empty and signers > 0,
        f"EMPTY/placeholder signing key(s): {empty}" if empty else f"{signers} signer key(s) present + non-empty",
    )


def _pvc_free_space(R: H.Report) -> None:
    """Free-space floors on the irreplaceable-state volumes (P0-B: MinIO full).

    A data volume near its free-space floor halts writes: MinIO trips its
    minimum-free-drive guard and refuses every PutObject; a full Postgres/Kafka
    volume corrupts or wedges the platform. Alerts BEFORE the wedge.
    """
    for ns, prefix, container, mount in T.PVC_DF_TARGETS:
        pod = H.pod_by_prefix(ns, prefix)
        if not pod:
            R.warn("infra", f"disk free {prefix.rstrip('-')}", "pod not found")
            continue
        total, _used, avail = H.df_bytes(ns, pod, container, mount)
        if total <= 0 or avail < 0:
            R.warn("infra", f"disk free {prefix.rstrip('-')}", f"df unreadable on {mount}")
            continue
        free_pct = round(100 * avail / total, 1)
        avail_gib = round(avail / 1_073_741_824, 1)
        st = (
            H.FAIL
            if (free_pct < T.PVC_FREE_PCT_FAIL or avail < T.PVC_FREE_BYTES_FAIL)
            else H.WARN
            if free_pct < T.PVC_FREE_PCT_WARN
            else H.PASS
        )
        R.add("infra", f"disk free {prefix.rstrip('-')} ({mount})", st, f"{avail_gib} GiB free = {free_pct}%")

        # INODE headroom on the same volume — the P0 the byte-check missed. A tiny-
        # object firehose exhausts inodes long before bytes (bronze: 41% bytes but
        # 75% inodes used), and inode exhaustion halts writes exactly like a full
        # disk. df -i on the identical mount.
        i_total, i_used, i_free = H.df_inodes(ns, pod, container, mount)
        if i_total <= 0 or i_free < 0:
            R.warn("infra", f"inodes free {prefix.rstrip('-')}", f"df -i unreadable on {mount}")
            continue
        ifree_pct = round(100 * i_free / i_total, 1)
        ist = (
            H.FAIL
            if ifree_pct < T.PVC_FREE_INODE_PCT_FAIL
            else H.WARN
            if ifree_pct < T.PVC_FREE_INODE_PCT_WARN
            else H.PASS
        )
        R.add(
            "infra",
            f"inodes free {prefix.rstrip('-')} ({mount})",
            ist,
            f"{i_free:,} inodes free = {ifree_pct}% ({i_used:,}/{i_total:,} used)",
        )


def _referenced_secrets_exist(R: H.Report) -> None:
    """Every NON-optional Secret referenced by a workload must exist right now.

    Roll-fragility guard: a pod created while a secret existed keeps running after
    that secret is deleted (the value is already injected), so a missing secret is
    invisible until the next roll fails to start the pod. We diff live refs
    (envFrom / secretKeyRef / volume, optional=false only) against present
    secrets.
    """
    _, refs_out = H.kubectl(f"-n {H.NS} get deploy,statefulset -o json", timeout=60)
    try:
        objs = json.loads(refs_out).get("items", [])
    except ValueError:
        R.warn("infra", "referenced secrets exist", "could not read workload specs")
        return
    required: dict[str, set[str]] = {}  # secret name → workloads that require it
    for it in objs:
        wl = it.get("metadata", {}).get("name", "?")
        spec = it.get("spec", {}).get("template", {}).get("spec", {})
        for c in spec.get("containers", []) + spec.get("initContainers", []):
            for ef in c.get("envFrom", []):
                sr = ef.get("secretRef")
                if sr and not sr.get("optional", False):
                    required.setdefault(sr["name"], set()).add(wl)
            for e in c.get("env", []):
                skr = (e.get("valueFrom") or {}).get("secretKeyRef")
                if skr and not skr.get("optional", False):
                    required.setdefault(skr["name"], set()).add(wl)
        for v in spec.get("volumes", []):
            sec = v.get("secret")
            if sec and not sec.get("optional", False):
                required.setdefault(sec["secretName"], set()).add(wl)

    def _secret_names() -> set[str]:
        _, so = H.kubectl(f"-n {H.NS} get secrets --no-headers -o custom-columns=NAME:.metadata.name")
        return {ln.strip() for ln in so.splitlines() if ln.strip()}

    present = _secret_names()
    missing = sorted(n for n in required if n not in present)
    R.check(
        "infra",
        "referenced *-secrets all present (roll-safe)",
        not missing,
        f"MISSING (pods run now, next roll fails): {missing}"
        if missing
        else f"all {len(required)} referenced secrets exist",
    )

    # Stability across TWO samples: an ephemeral / pruned secret (helm-secrets or a
    # GC sweep deleting a secret still referenced by running pods) is the roll-
    # fragility trap the single presence-snapshot above cannot see if it happens to
    # exist at sample time. Re-list and assert no REFERENCED secret disappeared
    # between the two reads — a vanished ref is a latent next-roll failure.
    present2 = _secret_names()
    vanished = sorted(n for n in required if n in present and n not in present2)
    R.check(
        "infra",
        "referenced *-secrets stable across two samples",
        not vanished,
        f"VANISHED mid-run (prune/GC deleting live-referenced secret): {vanished}"
        if vanished
        else f"{len(required)} referenced secrets stable across 2 samples",
    )


def _synthetic_monitor(R: H.Report) -> None:
    """prod-smoke CronJob: recent runs must succeed, and the monitor must be live.

    A KubeJobFailed on the synthetic monitor means an end-to-end freshness /
    ingestion assertion is red — the earliest external signal of a data-plane
    regression. Individual Jobs are GC'd quickly (small history limits), so when
    no Jobs remain we fall back to the CronJob's own status: a suspended monitor
    or a stale lastSuccessfulTime is itself a finding (a silenced watchdog).
    """
    _, out = H.kubectl(
        f"-n {H.MON_NS} get jobs --no-headers "
        f"-o custom-columns=NAME:.metadata.name,SUCCEEDED:.status.succeeded,FAILED:.status.failed,"
        f"START:.status.startTime"
    )
    jobs = []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 4 and f[0].startswith(T.PROD_SMOKE_CRONJOB):
            jobs.append((f[3], f[0], f[1], f[2]))  # (start, name, succeeded, failed)
    if jobs:
        jobs.sort(reverse=True)  # newest start first
        window = jobs[: T.PROD_SMOKE_LOOKBACK]
        failed = [n for _s, n, succ, fail in window if H.as_int(fail, 0) > 0 or succ in ("", "<none>", "0")]
        st = H.FAIL if len(failed) > T.PROD_SMOKE_MAX_FAILED else H.WARN if failed else H.PASS
        R.add(
            "monitoring",
            f"prod-smoke last {len(window)} jobs succeeded",
            st,
            f"{len(failed)}/{len(window)} failed: {failed[:4]}"
            if failed
            else f"all {len(window)} recent runs Complete",
        )
        return

    # No Jobs retained → judge the CronJob status directly (durable signal).
    _, js = H.kubectl(
        f"-n {H.MON_NS} get cronjob {T.PROD_SMOKE_CRONJOB} "
        f"-o jsonpath='{{.spec.suspend}}|{{.status.lastScheduleTime}}|{{.status.lastSuccessfulTime}}'"
    )
    parts = js.strip().strip("'").split("|")
    if len(parts) < 3:
        R.warn("monitoring", "prod-smoke CronJob status", f"unreadable ({js[:60]})")
        return
    suspend, last_sched, last_success = parts[0], parts[1], parts[2]
    if suspend == "true":
        R.fail(
            "monitoring",
            "prod-smoke monitor active",
            f"CronJob SUSPENDED — synthetic monitor silenced (last success {last_success or 'never'})",
        )
        return
    # Not suspended: last success must not lag last schedule (recent runs failing).
    import datetime

    def _age_h(ts: str) -> float:
        try:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (datetime.datetime.now(datetime.UTC) - dt).total_seconds() / 3600
        except ValueError:
            return -1.0

    succ_age = _age_h(last_success)
    st = H.FAIL if (succ_age < 0 or succ_age > 2.0) else H.PASS  # */30 schedule → >2h stale = failing
    R.add(
        "monitoring",
        "prod-smoke recent run succeeded",
        st,
        f"last success {round(succ_age, 1)}h ago (last schedule {last_sched or '?'})",
    )


def _restart_rates(R: H.Report) -> None:
    """Restart-RATE (restarts/hour) on liveness-sensitive pods.

    Catches the recurring gliner OOM (P1-A, ~3/h at 12Gi cap) and the nlp
    article-consumer poison-pill (P0-A, restarts on a many-mention article) — a
    restart-COUNT check misses a pod that was recently recreated (count reset)
    but is still storming.
    """
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    for ns, prefix in T.RESTART_RATE_TARGETS:
        _, out = H.kubectl(
            f"-n {ns} get pods --no-headers "
            f"-o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp,"
            f"RESTARTS:.status.containerStatuses[0].restartCount"
        )
        worst_rate, worst_detail = -1.0, ""
        found = False
        for ln in out.splitlines():
            f = ln.split()
            if len(f) < 3 or not f[0].startswith(prefix):
                continue
            found = True
            try:
                created = datetime.datetime.fromisoformat(f[1].replace("Z", "+00:00"))
            except ValueError:
                continue
            age_h = max((now - created).total_seconds() / 3600, 0.1)
            restarts = H.as_int(f[2], 0)
            rate = restarts / age_h
            if rate > worst_rate:
                worst_rate = rate
                worst_detail = f"{f[0]} {restarts} restarts / {age_h:.1f}h = {rate:.2f}/h"
        if not found:
            R.warn("infra", f"restart-rate {prefix}", "no matching pod")
            continue
        st = (
            H.FAIL
            if worst_rate >= T.POD_RESTART_RATE_FAIL
            else H.WARN
            if worst_rate >= T.POD_RESTART_RATE_WARN
            else H.PASS
        )
        R.add("infra", f"restart-rate bounded ({prefix})", st, worst_detail)
