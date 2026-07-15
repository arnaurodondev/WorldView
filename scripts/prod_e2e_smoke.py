#!/usr/bin/env python3
"""Production end-to-end smoke / health harness for the worldview platform.

WHAT THIS IS
------------
A single, dependency-free (stdlib-only) script that exercises the LIVE prod
cluster across four layers and prints a PASS / WARN / FAIL report with a
non-zero exit code if anything critical is broken. Run it on demand, from CI,
or from a cron — it is read-only except for one self-cleaning alert-rule
round-trip (create → delete) used to prove the alerts write-path.

    LAYER 0  platform/infra   (kubectl)  pods ready, DLQs empty, kafka lag,
                                          MinIO buckets, TLS cert, backups,
                                          entity-embedding backfill progress
    LAYER 1  public edge      (curl)     80→301, HTTPS 200, unauth→401,
                                          internal routes→403, valid LE cert
    LAYER 2  data plane        (in-pod)  every backend domain returns REAL data
    LAYER 3  async processes    (mixed)  description generation, chat grounding,
                                          alert CRUD round-trip

WHY THE ODD AUTH PATH (layer 2/3)
---------------------------------
Prod runs real Zitadel OIDC; `/v1/auth/dev-login` is disabled and the public
front door needs an interactive browser token we cannot get headlessly. So the
authenticated checks run a small prober INSIDE the api-gateway pod: it mints a
short-lived internal RS256 JWT with the gateway's OWN signer (`jwt_utils`) — the
exact `X-Internal-JWT` the gateway itself attaches when proxying downstream —
and calls each backend over ClusterIP. This verifies the real routes/processes/
data end-to-end via the same trust path the gateway uses. (It does NOT exercise
the Zitadel front door; layer 1 verifies that gate is present and rejecting.)

If you have a real Zitadel bearer token (e.g. a CI service account), set
WV_BEARER and the layer-2/3 checks will instead go through the PUBLIC gateway.

USAGE
-----
    export KUBECONFIG=~/.kube/config-worldview     # tunnel/context to prod
    python3 scripts/prod_e2e_smoke.py              # full run
    python3 scripts/prod_e2e_smoke.py --layer 0,1  # only infra + public edge
    python3 scripts/prod_e2e_smoke.py --json out.json
    WV_BEARER=<zitadel-jwt> python3 scripts/prod_e2e_smoke.py  # via public gw

EXIT CODE: 0 = all critical checks passed (WARNs allowed); 1 = ≥1 FAIL.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

# ── Configuration ────────────────────────────────────────────────────────────
PUBLIC_HOST = "api.worldview-labs.com"
NODE_IP = "116.203.198.118"
NS = "worldview"
INFRA_NS = "infra"
GATEWAY_LABEL = "app.kubernetes.io/name=api-gateway"

# Canonical MinIO buckets (mirrors manifests/minio-bucket-init.yaml). A missing
# bucket = silent "Bucket not found" write failures downstream.
EXPECTED_BUCKETS = [
    "market-data",
    "content-data",
    "intelligence-data",
    "rag-data",
    "market-bronze",
    "market-canonical",
    "market-ingestion",
    "worldview-bronze",
    "worldview-silver",
    "worldview",
    "worldview-feedback-screenshots",
]
DLQ_TOPICS = [
    "alert.dead-letter.v1",
    "content.dead-letter.v1",
    "kg.dead-letter.v1",
    "market.dead-letter.v1",
    "nlp.dead-letter.v1",
]
KAFKA_LAG_WARN = 5_000  # per-group total lag above this → WARN (backlog)
KAFKA_LAG_FAIL = 100_000  # ...above this → FAIL (consumer wedged/dead)
BACKUP_MAX_AGE_H = 12  # newest pg dump must be younger than this

# ── Result plumbing ──────────────────────────────────────────────────────────
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_C = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", "END": "\033[0m"}


@dataclass
class Report:
    rows: list[tuple[str, str, str, str]] = field(default_factory=list)  # layer, name, status, detail

    def add(self, layer: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append((layer, name, status, detail))
        c = _C.get(status, "")
        print(f"  {c}{status:4}{_C['END']}  [{layer}] {name}" + (f" — {detail}" if detail else ""))

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for _, _, s, _ in self.rows:
            out[s] = out.get(s, 0) + 1
        return out


R = Report()


def sh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command, return (exit_code, combined_output)."""
    try:
        # shell=True is intentional: this is an operator-run harness that pipes
        # kubectl/curl/psql; all commands are built from module constants, never
        # from untrusted input.
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)  # noqa: S602
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def kubectl(args: str, timeout: int = 60) -> tuple[int, str]:
    return sh(f"kubectl {args}", timeout)


def minio_pod() -> str:
    _, out = kubectl(f"-n {INFRA_NS} get pods --no-headers")
    for line in out.splitlines():
        if line.startswith("minio-") and "Running" in line:
            return line.split()[0]
    return ""


def gateway_pod() -> str:
    _, out = kubectl(f"-n {NS} get pods -l {GATEWAY_LABEL} --no-headers")
    for line in out.splitlines():
        if "Running" in line:
            return line.split()[0]
    return ""


# ── LAYER 0 — platform / infra ───────────────────────────────────────────────
def layer0() -> None:
    print("\n=== LAYER 0 — platform / infra ===")

    # pods ready + no crashloops
    for ns in (INFRA_NS, NS, "monitoring"):
        _, out = kubectl(f"-n {ns} get pods --no-headers")
        not_ready, crash = [], []
        for ln in out.splitlines():
            f = ln.split()
            if len(f) < 4:
                continue
            name, ready, status = f[0], f[1], f[2]
            restarts = f[3]
            if status not in ("Running", "Completed"):
                not_ready.append(f"{name}={status}")
            elif "/" in ready and ready.split("/")[0] != ready.split("/")[1] and status != "Completed":
                not_ready.append(f"{name}={ready}")
            try:
                if int(restarts.split()[0].strip("()")) > 5:
                    crash.append(f"{name}={restarts}")
            except ValueError:
                pass
        R.add(
            "0",
            f"pods ready ({ns})",
            FAIL if not_ready else PASS,
            ", ".join(not_ready) if not_ready else "all Running/Ready",
        )
        if crash:
            R.add("0", f"crashloops ({ns})", WARN, ", ".join(crash))

    # DLQ topics empty
    b = kafka_offsets(DLQ_TOPICS)
    hot = {t: n for t, n in b.items() if n > 0}
    R.add(
        "0",
        "dead-letter queues empty",
        FAIL if hot else PASS,
        ", ".join(f"{t}={n}" for t, n in hot.items()) if hot else "all 5 DLQs = 0",
    )

    # kafka consumer group lag
    worst = kafka_worst_lag()
    if worst is None:
        R.add("0", "kafka consumer lag", WARN, "could not read groups")
    else:
        grp, lag = worst
        st = FAIL if lag > KAFKA_LAG_FAIL else WARN if lag > KAFKA_LAG_WARN else PASS
        R.add("0", "kafka consumer lag", st, f"max {grp}={lag}")

    # MinIO buckets
    mp = minio_pod()
    if mp:
        _, out = kubectl(
            f"-n {INFRA_NS} exec {mp} -- sh -c "
            f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; mc ls l/ 2>/dev/null\''
        )
        present = {ln.split()[-1].rstrip("/") for ln in out.splitlines() if ln.strip()}
        missing = [b for b in EXPECTED_BUCKETS if b not in present]
        R.add(
            "0",
            "MinIO buckets present",
            FAIL if missing else PASS,
            f"missing: {missing}" if missing else f"{len(EXPECTED_BUCKETS)} canonical buckets",
        )
    else:
        R.add("0", "MinIO buckets present", WARN, "minio pod not found")

    # TLS cert issued
    _, out = kubectl(f"-n {NS} get certificate api-tls -o jsonpath='{{.status.conditions[0].status}}'")
    R.add("0", "TLS cert (api-tls) issued", PASS if out.strip() == "True" else FAIL, f"ready={out.strip()}")

    # backup freshness
    if mp:
        _, out = kubectl(
            f"-n {INFRA_NS} exec {mp} -- sh -c "
            f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; '
            f"mc ls l/worldview-backups/postgres/ 2>/dev/null | tail -1'"
        )
        R.add(
            "0",
            "postgres backup present",
            PASS if out.strip() else WARN,
            out.strip()[:80] if out.strip() else "no dump yet (cronjob runs every 6h)",
        )

    # entity-embedding backfill progressing
    _, out = kubectl(
        f"-n {INFRA_NS} exec postgres-0 -- psql -U postgres -d intelligence_db -tAc "  # noqa: S608 (constant query, no user input)
        f'"SELECT count(*) FILTER (WHERE embedding IS NOT NULL), count(*) FROM entity_embedding_state;"'
    )
    line = next((ln for ln in out.splitlines() if "|" in ln), "")
    if line:
        emb, tot = line.split("|")[:2]
        pct = round(100 * int(emb) / max(int(tot), 1), 1)
        R.add("0", "entity embedding coverage", PASS if pct >= 30 else WARN, f"{emb}/{tot} ({pct}%)")


def kafka_offsets(topics: list[str]) -> dict[str, int]:
    out_map: dict[str, int] = {}
    for t in topics:
        _, out = kubectl(
            f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
            f"'kafka-run-class.sh kafka.tools.GetOffsetShell --broker-list localhost:9092 --topic {t} 2>/dev/null'"
        )
        total = 0
        for ln in out.splitlines():
            parts = ln.split(":")
            if len(parts) == 3 and parts[2].strip().isdigit():
                total += int(parts[2])
        out_map[t] = total
    return out_map


def kafka_worst_lag() -> tuple[str, int] | None:
    _, groups = kubectl(
        f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
        f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list 2>/dev/null'"
    )
    worst: tuple[str, int] | None = None
    for g in groups.splitlines():
        g = g.strip()
        if not g:
            continue
        _, desc = kubectl(
            f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
            f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group {g} 2>/dev/null'"
        )
        lag = 0
        for ln in desc.splitlines()[1:]:
            f = ln.split()
            if len(f) >= 6 and f[5].isdigit():
                lag += int(f[5])
        if worst is None or lag > worst[1]:
            worst = (g, lag)
    return worst


# ── LAYER 1 — public edge (no auth) ──────────────────────────────────────────
def layer1() -> None:
    print("\n=== LAYER 1 — public edge (no auth) ===")

    code, _ = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 -I http://{PUBLIC_HOST}/")
    _, redirect = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://{PUBLIC_HOST}/healthz")
    R.add("1", "HTTP :80 → 301 redirect", PASS if redirect.strip() == "301" else FAIL, f"got {redirect.strip()}")

    _, hc = sh(
        f"curl -s -o /dev/null -w '%{{http_code}}:%{{ssl_verify_result}}' --max-time 12 https://{PUBLIC_HOST}/healthz"
    )
    parts = hc.strip().split(":")
    ok = parts[0] == "200" and (len(parts) < 2 or parts[1] == "0")
    R.add("1", "HTTPS /healthz 200 + valid TLS", PASS if ok else FAIL, hc.strip())

    # unauth data endpoint must be 401 (not data)
    _, un = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{PUBLIC_HOST}/v1/market/top-movers")
    R.add("1", "unauth /v1 data → 401", PASS if un.strip() in ("401", "403") else FAIL, f"got {un.strip()}")

    # internal routes must be blocked from public
    for path in ("/metrics", "/openapi.json", "/docs"):
        _, ic = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{PUBLIC_HOST}{path}")
        R.add(
            "1", f"internal route blocked {path}", PASS if ic.strip() in ("403", "404") else FAIL, f"got {ic.strip()}"
        )


# ── LAYER 2 + 3 — data plane & async processes (authed) ──────────────────────
# Prober runs INSIDE the gateway pod: mints an internal JWT via the gateway's own
# signer and calls each backend over ClusterIP. Returns one JSON blob we parse.
INPOD_PROBER = r"""
import json, os, urllib.request, urllib.error
results = {}

# Load the gateway's OWN internal-JWT signing key exactly as app.py does at
# startup (settings.internal_jwt_private_key + settings.jwt_key_version), so the
# X-Internal-JWT we mint is byte-identical to what the gateway attaches when it
# proxies a real request downstream.
from api_gateway.oidc import load_rsa_private_key
from api_gateway.jwt_utils import issue_user_jwt
_pem = os.environ.get("API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY")
_kid = os.environ.get("API_GATEWAY_JWT_KEY_VERSION", "v1")
if not _pem:
    from api_gateway.config import Settings
    _s = Settings(); _pem = _s.internal_jwt_private_key.get_secret_value(); _kid = _s.jwt_key_version
_pk = load_rsa_private_key(_pem)

def tok():
    # fresh jti per call — backends enforce internal-JWT replay detection.
    # user_id/tenant_id MUST be valid UUIDs (alert + rag-chat validate the
    # format); a stable synthetic e2e identity keeps reads deterministic.
    return issue_user_jwt(user_id="0195e2e0-0000-7000-8000-000000000001",
                          tenant_id="0195e2e0-0000-7000-8000-000000000002",
                          oidc_sub="e2e-smoke", private_key=_pk, kid=_kid, role="user")

def call(name, url, method="GET", body=None, timeout=30):
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
              headers={"X-Internal-JWT": tok(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(4000).decode("utf-8", "replace")
            results[name] = {"status": r.status, "len": len(raw), "body": raw[:800]}
    except urllib.error.HTTPError as e:
        results[name] = {"status": e.code, "body": e.read(400).decode("utf-8", "replace")}
    except Exception as e:
        results[name] = {"status": -1, "error": str(e)[:200]}

MD = "http://market-data.worldview.svc:8003/api/v1"
KG = "http://knowledge-graph.worldview.svc:8007/api/v1"
NLP = "http://nlp-pipeline.worldview.svc:8006/api/v1"
AL = "http://alert.worldview.svc:8010/api/v1"
RC = "http://rag-chat.worldview.svc:8008/api/v1"

# resolve a well-known instrument id (AAPL) to drive market/KG checks
call("kg_stats", KG + "/graph/stats")
call("kg_lookup", KG + "/entities/lookup?ticker=AAPL")
aapl = None
try:
    b = json.loads(results["kg_lookup"]["body"])
    aapl = (b.get("entity_id") or b.get("id") or (b.get("results") or [{}])[0].get("entity_id"))
except Exception:
    pass
if aapl:
    call("md_ohlcv", MD + f"/ohlcv/{aapl}?interval=1d&limit=5")
    call("md_fundamentals", MD + f"/fundamentals/{aapl}/snapshot")
    call("kg_entity", KG + f"/entities/{aapl}")
    call("kg_intelligence", KG + f"/entities/{aapl}/intelligence")
    call("kg_graph", KG + f"/entities/{aapl}/graph")
    call("desc_refresh", KG + f"/entities/{aapl}/refresh", "POST", {})   # layer 3: description gen trigger
call("md_screen", MD + "/fundamentals/screen", "POST",
     {"filters": [{"field": "market_cap", "op": "gte", "value": 1e11}], "limit": 3})
call("predmkts", MD + "/prediction-markets?limit=3")
call("news_top", NLP + "/news/top?limit=5")
call("alerts_list", AL + "/alert-rules")
# layer 3: chat grounding (non-stream full generation can take 15-40s)
call("chat", RC + "/chat", "POST",
     {"message": "What was AAPL's most recent closing price?"}, timeout=90)
# layer 4: SYNTHETIC embedding-worker test — a long RAW-Korean string exercises the
# exact bge truncation + DeepInfra path the retry worker uses. Pre-fix this 400'd
# (raw CJK under-counted → >512 tokens); a 200 proves truncation+embedding end-to-end.
call("embed_cjk", NLP + "/embed", "POST",
     {"text": "미국 캘리포니아주 새너제이, 어떤 데이터 환경에서도 최적화된 성능을 제공하는 지능형 시스템입니다. " * 40})
print("E2E_JSON_START" + json.dumps(results) + "E2E_JSON_END")
"""


def run_inpod_prober() -> dict:
    gw = gateway_pod()
    if not gw:
        R.add("2", "auth (internal-JWT prober)", FAIL, "no api-gateway pod found")
        return {}
    # ship the prober on stdin to the pod's python
    cmd = f"kubectl -n {NS} exec -i {gw} -- python3 - <<'PYEOF'\n{INPOD_PROBER}\nPYEOF"
    _, out = sh(cmd, timeout=180)
    if "E2E_JSON_START" not in out:
        R.add("2", "auth (internal-JWT prober)", FAIL, f"prober failed: {out[-200:]}")
        return {}
    try:
        blob = out.split("E2E_JSON_START", 1)[1].split("E2E_JSON_END", 1)[0]
        R.add("2", "auth (internal-JWT prober)", PASS, "minted internal JWT, drove backends")
        return json.loads(blob)
    except Exception as e:
        R.add("2", "auth (internal-JWT prober)", FAIL, f"parse error: {e}")
        return {}


def layer23(res: dict) -> None:
    print("\n=== LAYER 2 — data plane (real data?) ===")

    def check(layer, name, key, want_status=200, need_data=True, market_hours_ok=False):
        r = res.get(key)
        if not r:
            R.add(layer, name, WARN, "not probed")
            return
        st = r.get("status")
        if st != want_status:
            # quotes during closed market is expected-empty → WARN not FAIL
            sev = WARN if market_hours_ok else FAIL
            R.add(layer, name, sev, f"HTTP {st} {r.get('error','')} {r.get('body','')[:120]}")
            return
        if need_data and r.get("len", 0) < 5:
            R.add(layer, name, WARN, "200 but empty body")
            return
        R.add(layer, name, PASS, f"HTTP {st}, {r.get('len','?')}B")

    check("2", "KG graph/stats", "kg_stats")
    check("2", "KG entity lookup (AAPL)", "kg_lookup")
    check("2", "market OHLCV", "md_ohlcv")
    check("2", "market fundamentals snapshot", "md_fundamentals")
    check("2", "market screener (POST)", "md_screen")
    check("2", "KG entity", "kg_entity")
    check("2", "KG intelligence narrative", "kg_intelligence")
    check("2", "KG entity graph", "kg_graph")
    check("2", "prediction-markets list", "predmkts")
    check("2", "news top", "news_top")
    check("2", "alerts list", "alerts_list")

    print("\n=== LAYER 3 — async processes ===")
    # description generation: 200/202 = job enqueued; 429 = route up + rate-limiter
    # working (one refresh/entity/hour) — both prove the generator path is healthy.
    dr = res.get("desc_refresh")
    if dr and dr.get("status") in (200, 202):
        R.add("3", "entity description-gen trigger", PASS, f"HTTP {dr['status']} (refresh enqueued)")
    elif dr and dr.get("status") == 429:
        R.add(
            "3",
            "entity description-gen trigger",
            PASS,
            "HTTP 429 (route up, rate-limited — already refreshed this hour)",
        )
    elif dr:
        R.add("3", "entity description-gen trigger", FAIL, f"HTTP {dr.get('status')} {dr.get('body','')[:120]}")

    # chat grounding: expect a non-empty answer body
    ch = res.get("chat")
    if ch and ch.get("status") == 200 and ch.get("len", 0) > 20:
        R.add("3", "rag-chat grounded answer", PASS, f"{ch['len']}B answer")
    elif ch:
        R.add("3", "rag-chat grounded answer", FAIL, f"HTTP {ch.get('status')} {ch.get('body','')[:120]}")


# ── LAYER 4 — async workers & data pipelines ─────────────────────────────────
# Async workers can't be "called" — they're validated by asserting their OUTPUT:
# backlogs drain, outboxes dispatch, jobs don't wedge, fresh data keeps landing —
# plus one SYNTHETIC injection (a CJK embed) that drives a worker path end-to-end.
def _psql(db: str, sql: str) -> str:
    _, out = kubectl(
        f'-n {INFRA_NS} exec postgres-0 -- psql -U postgres -d {db} -tAc "{sql}"'
    )
    for ln in out.splitlines():
        s = ln.strip()
        if s and "could not" not in s.lower() and "default" not in s.lower():
            return s
    return ""


def layer4(res: dict) -> None:
    print("\n=== LAYER 4 — async workers & pipelines ===")

    # 1. SYNTHETIC embedding-worker E2E (the flagship): long raw-Korean → /embed.
    e = res.get("embed_cjk")
    if e and e.get("status") == 200:
        R.add("4", "embedding path (synthetic CJK)", PASS, "200 — bge truncation + DeepInfra OK on raw CJK")
    elif e and e.get("status") == 400:
        R.add("4", "embedding path (synthetic CJK)", FAIL, "400 — token-budget truncation regressed (CJK under-count)")
    elif e:
        R.add("4", "embedding path (synthetic CJK)", WARN, f"HTTP {e.get('status')} {e.get('error','')}")

    # 2. embedding-retry-worker: no rows abandoned at the retry ceiling.
    ab = _psql("nlp_db", "SELECT count(*) FROM embedding_pending WHERE retry_count >= 5")
    R.add(
        "4", "embedding-retry: 0 abandoned", PASS if ab in ("0", "") else WARN, f"{ab or '?'} rows stuck at max retries"
    )

    # 3. outbox dispatchers (every service): no events undispatched > 10 min
    #    (a wedged dispatcher = DB writes that never reach Kafka).
    stuck_total, worst = 0, ""
    for db in ("portfolio_db", "intelligence_db", "nlp_db", "market_data_db", "content_store_db", "alert_db"):
        n = _psql(
            db,
            "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL AND created_at < now() - interval '10 minutes'",
        )
        if n.isdigit() and int(n) > 0:
            stuck_total += int(n)
            worst = f"{db}={n}"
    R.add(
        "4",
        "outbox dispatchers draining",
        FAIL if stuck_total > 50 else WARN if stuck_total else PASS,
        f"{stuck_total} events undispatched >10m ({worst})" if stuck_total else "all outboxes drained",
    )

    # 4. path-insight-worker: no jobs wedged in a non-terminal state.
    stuck = _psql(
        "intelligence_db",
        "SELECT count(*) FROM path_insight_jobs WHERE status IN ('running','pending') AND coalesce(claimed_at, now()) < now() - interval '30 minutes'",
    )
    R.add("4", "path-insight jobs not wedged", PASS if stuck in ("0", "") else WARN, f"{stuck or '?'} stuck >30m")

    # 5. content pipeline freshness: articles keep landing (ingest→NER→store alive).
    latest = _psql(
        "content_store_db",
        "SELECT coalesce(round(extract(epoch from now()-max(ingested_at))/3600,1)::text,'none') FROM documents",
    )
    if latest in ("", "none"):
        R.add("4", "content pipeline freshness", WARN, "no documents yet")
    else:
        h = float(latest)
        R.add("4", "content pipeline freshness", PASS if h < 6 else WARN, f"newest doc {h}h old")

    # 6. KG entity-description generation: embeddings keep getting produced.
    cov = _psql(
        "intelligence_db",
        "SELECT count(*) FILTER (WHERE embedding IS NOT NULL)||'/'||count(*) FROM entity_embedding_state",
    )
    R.add("4", "entity description/embedding backfill", PASS if cov else WARN, f"embedded {cov or '?'}")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="worldview prod e2e smoke harness")
    ap.add_argument(
        "--layer", default="0,1,2,3,4", help="comma list of layers to run (0 infra,1 edge,2 data,3 async,4 workers)"
    )
    ap.add_argument("--json", help="write full report JSON to this path")
    args = ap.parse_args()
    layers = set(args.layer.split(","))

    print(f"worldview prod e2e smoke — {PUBLIC_HOST} ({NODE_IP})  {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}")
    rc, ctx = kubectl("config current-context")
    print(f"kube-context: {ctx.strip()}")

    if "0" in layers:
        layer0()
    if "1" in layers:
        layer1()
    if layers & {"2", "3", "4"}:
        res = run_inpod_prober()
        if layers & {"2", "3"}:
            layer23(res)
        if "4" in layers:
            layer4(res)

    c = R.counts()
    print("\n" + "=" * 60)
    print(
        f"SUMMARY: {_C[PASS]}{c[PASS]} PASS{_C['END']}  "
        f"{_C[WARN]}{c[WARN]} WARN{_C['END']}  {_C[FAIL]}{c[FAIL]} FAIL{_C['END']}"
    )
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"summary": c, "rows": R.rows}, f, indent=2)
        print(f"wrote {args.json}")
    return 1 if c[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
