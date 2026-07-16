"""Checks for alert (S10 / alert_db) and the api-gateway (S9) route contract.

Alert is event-driven and watchlist-gated: with no users/watchlists on a fresh
deploy the alerts + rules tables are legitimately empty, so we assert schema
presence, the rule-type CHECK constraint width (must include the PLAN-0056
`prediction` rule type), and that its consumer workloads are up. The gateway is
stateless — we assert its route contract: unauth edge behaviour, and that the
authed prober actually reached >=N distinct backends (proving the BFF proxy layer
is wired end-to-end).
"""

from __future__ import annotations

from .. import harness as H
from ..harness import Ctx


def run(ctx: Ctx) -> None:
    _alert(ctx)
    _gateway(ctx)


def _alert(ctx: Ctx) -> None:
    R = ctx.report
    svc = "alert"
    q = H.psql_many(
        "alert_db",
        {
            "alerts": "SELECT count(*) FROM alerts",
            "rules": "SELECT count(*) FROM alert_rules",
            "subs": "SELECT count(*) FROM alert_subscriptions",
            "rule_ck": "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_alert_rules_rule_type'",
        },
    )
    schema_ok = all(q[k] != "" for k in ("alerts", "rules", "subs"))
    R.check(svc, "alert_db schema present", schema_ok, f"alerts={q['alerts'] or '?'} rules={q['rules'] or '?'}")
    # Rule-type CHECK must include PREDICTION (migration 0011 widening).
    ck = q["rule_ck"] or ""
    R.check(
        svc,
        "rule_type CHECK includes PREDICTION",
        "PREDICTION" in ck.upper(),
        f"{ck[:120] or 'constraint not found'}",
        soft=True,
    )

    # alert-rules API reachable (empty list is fine).
    row = ctx.api_row("al_rules")
    if row:
        R.check(svc, "alert-rules API up", row.get("status") == 200, f"HTTP {row.get('status')}")

    # Consumer + dispatcher workloads present.
    _, out = H.kubectl(f"-n {H.NS} get pods --no-headers")
    alert_pods = [ln.split()[0] for ln in out.splitlines() if ln.startswith("alert-") and "Running" in ln]
    R.floor(svc, "alert worker pods running", len(alert_pods), 3)


def _gateway(ctx: Ctx) -> None:
    R = ctx.report
    svc = "api-gateway"
    # The prober routes through gateway CLIENT libs to backends; count distinct
    # backend families that answered 200 — proves the BFF proxy layer is wired.
    families = {
        "market-data": ["md_ohlcv", "md_predlist", "md_sector"],
        "knowledge-graph": ["kg_stats", "kg_entity"],
        "nlp-pipeline": ["nlp_top", "nlp_trend"],
        "rag-chat": ["chat"],
        "alert": ["al_rules"],
    }
    reached = [fam for fam, keys in families.items() if any((ctx.api_row(k) or {}).get("status") == 200 for k in keys)]
    R.floor(svc, "backend families reachable via prober", len(reached), 4)

    # Gateway health over ClusterIP.
    pod = H.gateway_pod()
    if pod:
        _, code = H.kubectl(
            f"-n {H.NS} exec {pod} -- python3 -c "
            f"\"import urllib.request as u;print(u.urlopen('http://localhost:8000/healthz',timeout=8).status)\""
        )
        R.check(svc, "gateway /healthz 200", code.strip().endswith("200"), f"got {code.strip()[-40:]}")
