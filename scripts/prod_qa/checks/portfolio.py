"""Checks for portfolio (S1 / portfolio_db) and market-ingestion (S2 / ingestion_db).

Portfolio is a user-facing tenant service: on a fresh prod deploy with no signed-
up users the domain tables are legitimately empty, so we assert SCHEMA presence
and the readiness endpoint rather than row floors. Market-ingestion polling is
the upstream of all market data — we assert task throughput + no stuck-lease pile.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx


def run(ctx: Ctx) -> None:
    _portfolio(ctx)
    _market_ingestion(ctx)


def _portfolio(ctx: Ctx) -> None:
    R = ctx.report
    svc = "portfolio"
    q = H.psql_many(
        "portfolio_db",
        {
            "tenants": "SELECT count(*) FROM tenants",
            "users": "SELECT count(*) FROM users",
            "portfolios": "SELECT count(*) FROM portfolios",
            "instruments": "SELECT count(*) FROM instruments",
        },
    )
    schema_ok = all(q[k] != "" for k in ("tenants", "users", "portfolios"))
    R.check(
        svc,
        "portfolio_db schema present",
        schema_ok,
        f"tenants={q['tenants'] or '?'} users={q['users'] or '?'} portfolios={q['portfolios'] or '?'}",
    )
    # Local instrument cache is fed by market.instrument.* events even with no users.
    R.check(
        svc,
        "instrument cache populated (event consumers alive)",
        H.as_int(q["instruments"], 0) > 0,
        f"{q['instruments']} local instruments",
        soft=True,
    )
    # Readiness endpoint via ClusterIP.
    _readyz(R, svc, "portfolio", 8001)


def _market_ingestion(ctx: Ctx) -> None:
    R = ctx.report
    svc = "market-ingestion"
    q = H.psql_many(
        "ingestion_db",
        {
            "tasks": "SELECT count(*) FROM ingestion_tasks",
            "succeeded": "SELECT count(*) FILTER (WHERE status='succeeded') FROM ingestion_tasks",
            "running": "SELECT count(*) FILTER (WHERE status='running') FROM ingestion_tasks",
            "failed": "SELECT count(*) FILTER (WHERE status='failed') FROM ingestion_tasks",
        },
    )
    R.floor(svc, "ingestion_tasks throughput", H.as_int(q["tasks"]), T.MI_TASKS_FLOOR)
    running = H.as_int(q["running"], 0)
    R.check(svc, "no stuck-lease task pile", running < T.MI_RUNNING_STUCK_WARN, f"{running} RUNNING", soft=True)
    total = H.as_int(q["tasks"], 0)
    succ = H.as_int(q["succeeded"], 0)
    R.check(
        svc, "ingestion success dominates", total > 0 and succ / total >= 0.8, f"{succ}/{total} succeeded", soft=True
    )
    _readyz(R, svc, "market-ingestion", 8002)


def _readyz(R: H.Report, svc: str, dep: str, port: int) -> None:
    """Hit a service's /readyz over ClusterIP from inside its own pod."""
    pod = H.running_pod(f"app.kubernetes.io/name={dep}")
    if not pod:
        R.warn(svc, "readiness probe", "no Running pod")
        return
    _, code = H.kubectl(
        f"-n {H.NS} exec {pod} -- python3 -c "
        f"\"import urllib.request as u;print(u.urlopen('http://localhost:{port}/readyz',timeout=8).status)\""
    )
    R.check(svc, "readiness probe (/readyz 200)", code.strip().endswith("200"), f"got {code.strip()[-40:]}", soft=True)
