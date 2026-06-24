#!/usr/bin/env python3
"""
Dashboard load stress test — simulates N concurrent dashboard page loads.
Measures p50/p95/p99 latency per endpoint tier.

Usage:
    python tests/validation/stress_test_dashboard.py

Prerequisites:
    pip install httpx
    Platform must be running (docker compose up)
"""

import asyncio
import json
import statistics
import subprocess
import time
from typing import NamedTuple

import httpx

BASE = "http://localhost:8000"

# Discovered from: POST /v1/auth/dev-login + GET /v1/holdings/<portfolio_id>
INSTRUMENT_IDS = [
    "01900000-0000-7000-8000-000000001004",  # TSLA
    "01900000-0000-7000-8000-000000001005",  # AMZN
    "01900000-0000-7000-8000-000000001003",  # GOOGL
    "01900000-0000-7000-8000-000000001007",  # META
    "01900000-0000-7000-8000-000000001008",  # JPM
    "01900000-0000-7000-8000-000000001009",  # NFLX
    "01900000-0000-7000-8000-000000001001",  # AAPL
]

ENTITY_IDS = [
    "11111111-0005-7000-8000-000000000001",  # TSLA
    "11111111-0004-7000-8000-000000000001",  # AMZN
    "11111111-0001-7000-8000-000000000001",  # AAPL
]

PORTFOLIO_ID = "01900000-0000-7000-8000-000000000100"

CONCURRENT_USERS = 8


class Result(NamedTuple):
    endpoint: str
    latency: float
    status: int


def get_token() -> str:
    import urllib.request

    req = urllib.request.Request(  # noqa: S310 — fixed local dev-login endpoint (BASE), not user input.
        f"{BASE}/v1/auth/dev-login",
        data=json.dumps({"email": "dev@worldview.local"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed local dev-login endpoint.
        return json.loads(resp.read())["access_token"]


async def timed_get(client: httpx.AsyncClient, endpoint: str, headers: dict) -> Result:
    t0 = time.monotonic()
    try:
        r = await client.get(f"{BASE}{endpoint}", headers=headers, timeout=90)
        return Result(endpoint, time.monotonic() - t0, r.status_code)
    except Exception:
        return Result(endpoint, time.monotonic() - t0, -1)


async def timed_post(client: httpx.AsyncClient, endpoint: str, headers: dict, body: dict) -> Result:
    t0 = time.monotonic()
    try:
        r = await client.post(f"{BASE}{endpoint}", headers=headers, json=body, timeout=90)
        return Result(endpoint, time.monotonic() - t0, r.status_code)
    except Exception:
        return Result(endpoint, time.monotonic() - t0, -1)


async def simulate_one_dashboard_load(client: httpx.AsyncClient, headers: dict) -> list[Result]:
    """Fire all dashboard-page concurrent requests, mirroring real browser behavior."""
    tasks = [
        # Tier 1: fast reads served from Valkey cache
        timed_get(client, "/v1/dashboard/bundle", headers),
        timed_get(client, "/v1/dashboard/snapshot", headers),
        timed_get(client, f"/v1/holdings/{PORTFOLIO_ID}", headers),
        # Tier 2: market-data heavy endpoints
        timed_get(client, "/v1/market/top-movers", headers),
        # Tier 3: market-data batch query
        timed_post(
            client,
            "/v1/companies/overviews:batch",
            headers,
            {"instrument_ids": INSTRUMENT_IDS},
        ),
        # Tier 4: intelligence/KG per-entity (pick first entity)
        timed_get(client, f"/v1/entities/{ENTITY_IDS[0]}/intelligence-bundle", headers),
    ]
    return await asyncio.gather(*tasks)


def collect_docker_stats() -> str:
    """Collect docker stats snapshot (CPU%, MEM%) for key containers."""
    try:
        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [
            line
            for line in result.stdout.strip().splitlines()
            if any(
                kw in line
                for kw in [
                    "api-gateway",
                    "market-data",
                    "rag-chat",
                    "postgres",
                    "valkey",
                    "intelligence",
                ]
            )
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[docker stats error: {exc}]"


def collect_db_connections() -> str:
    """Query pg_stat_activity for connection pool state."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "worldview-postgres-1",
                "psql",
                "-U",
                "postgres",
                "-c",
                "SELECT count(*) as count, state, datname FROM pg_stat_activity "
                "WHERE datname IS NOT NULL GROUP BY state, datname ORDER BY count DESC;",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout
    except Exception as exc:
        return f"[pg error: {exc}]"


def collect_valkey_stats() -> str:
    """Get Valkey hit/miss/memory stats."""
    try:
        result = subprocess.run(
            ["docker", "exec", "worldview-valkey-1", "redis-cli", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        relevant_keys = {
            "used_memory_human",
            "maxmemory_human",
            "keyspace_hits",
            "keyspace_misses",
            "instantaneous_ops_per_sec",
            "connected_clients",
            "mem_fragmentation_ratio",
        }
        lines = []
        for line in result.stdout.splitlines():
            key = line.split(":")[0]
            if key in relevant_keys:
                lines.append(line.strip())
        return "\n".join(lines)
    except Exception as exc:
        return f"[valkey error: {exc}]"


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


async def run_stress_test() -> dict:
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    results = {}

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50)) as client:
        # ---- Cold run (single load, no concurrent pressure) ----
        print("Phase 1: Cold single load...")
        cold_results = await simulate_one_dashboard_load(client, headers)
        cold_by_ep: dict[str, list[Result]] = {}
        for r in cold_results:
            cold_by_ep.setdefault(r.endpoint, []).append(r)

        print("  Cold latencies:")
        for ep, rlist in sorted(cold_by_ep.items()):
            lats = [r.latency for r in rlist]
            statuses = [r.status for r in rlist]
            print(f"    {ep}: {lats[0]:.3f}s  status={statuses[0]}")

        # ---- Warm single load (1 second after cold) ----
        await asyncio.sleep(1)
        print("\nPhase 2: Warm single load...")
        warm_results = await simulate_one_dashboard_load(client, headers)
        warm_by_ep: dict[str, list[Result]] = {}
        for r in warm_results:
            warm_by_ep.setdefault(r.endpoint, []).append(r)

        print("  Warm latencies:")
        for ep, rlist in sorted(warm_by_ep.items()):
            lats = [r.latency for r in rlist]
            statuses = [r.status for r in rlist]
            print(f"    {ep}: {lats[0]:.3f}s  status={statuses[0]}")

        # ---- Collect baseline DB/Valkey stats before stress ----
        print("\nCollecting baseline infrastructure stats...")
        baseline_db = collect_db_connections()
        baseline_valkey = collect_valkey_stats()
        baseline_docker = collect_docker_stats()

        # ---- Stress: N concurrent dashboard loads ----
        print(f"\nPhase 3: Stress — {CONCURRENT_USERS} concurrent dashboard loads...")
        t_stress_start = time.monotonic()

        all_loads = await asyncio.gather(
            *[simulate_one_dashboard_load(client, headers) for _ in range(CONCURRENT_USERS)]
        )
        stress_wall = time.monotonic() - t_stress_start

        # Collect infra stats immediately after stress
        print("Collecting stress-peak infrastructure stats...")
        stress_db = collect_db_connections()
        stress_valkey = collect_valkey_stats()
        stress_docker = collect_docker_stats()

        # Aggregate stress results
        stress_by_ep: dict[str, list[Result]] = {}
        for load in all_loads:
            for r in load:
                stress_by_ep.setdefault(r.endpoint, []).append(r)

        print(f"\nStress wall time ({CONCURRENT_USERS} concurrent loads): {stress_wall:.2f}s")
        print("\nStress latency breakdown:")
        stress_stats = {}
        for ep, rlist in sorted(stress_by_ep.items()):
            lats = [r.latency for r in rlist]
            errors = sum(1 for r in rlist if r.status >= 400 or r.status == -1)
            p50 = statistics.median(lats)
            p95 = percentile(lats, 95)
            p99 = percentile(lats, 99)
            stress_stats[ep] = {
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "min": min(lats),
                "max": max(lats),
                "n": len(rlist),
                "errors": errors,
            }
            print(
                f"  {ep}: "
                f"p50={p50:.2f}s  p95={p95:.2f}s  p99={p99:.2f}s  "
                f"min={min(lats):.2f}s  max={max(lats):.2f}s  "
                f"errors={errors}/{len(rlist)}"
            )

        results = {
            "cold": {r.endpoint: r.latency for r in cold_results},
            "warm": {r.endpoint: r.latency for r in warm_results},
            "stress_wall_time_s": stress_wall,
            "concurrent_users": CONCURRENT_USERS,
            "stress_stats": stress_stats,
            "baseline_db_connections": baseline_db,
            "stress_db_connections": stress_db,
            "baseline_valkey": baseline_valkey,
            "stress_valkey": stress_valkey,
            "baseline_docker_stats": baseline_docker,
            "stress_docker_stats": stress_docker,
        }

    return results


def identify_bottleneck(results: dict) -> str:
    """Heuristic bottleneck analysis based on latency + infra stats."""
    stress_stats = results.get("stress_stats", {})

    # Find slowest endpoint under stress
    worst = max(stress_stats.items(), key=lambda x: x[1]["p95"], default=None)
    if not worst:
        return "Insufficient data"

    worst_ep, worst_data = worst
    p95 = worst_data["p95"]
    errors = worst_data["errors"]
    total = worst_data["n"]

    lines = []
    lines.append(f"Slowest endpoint (p95={p95:.2f}s): {worst_ep}")

    # Parse DB connection counts
    db_info = results.get("stress_db_connections", "")
    total_db_conns = 0
    for line in db_info.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 1 and parts[0].strip().isdigit():
            total_db_conns += int(parts[0].strip())

    lines.append(f"DB connections under stress: ~{total_db_conns}")

    # Parse Valkey hit rate
    valkey_info = results.get("stress_valkey", "")
    hits = misses = 0
    for line in valkey_info.splitlines():
        if line.startswith("keyspace_hits:"):
            hits = int(line.split(":")[1])
        elif line.startswith("keyspace_misses:"):
            misses = int(line.split(":")[1])
    hit_rate = hits / max(hits + misses, 1) * 100
    lines.append(f"Valkey hit rate: {hit_rate:.1f}% ({hits} hits / {misses} misses)")

    # Verdict
    if "/v1/market/top-movers" in worst_ep or "/v1/companies/overviews" in worst_ep:
        tier = "market-data service (DB queries, no pre-warming)"
    elif "/v1/dashboard" in worst_ep:
        tier = "api-gateway orchestration / Valkey cache miss"
    elif "/v1/entities" in worst_ep:
        tier = "rag-chat / knowledge-graph service"
    else:
        tier = "unknown tier"

    if total_db_conns >= 90:
        lines.append("WARNING: DB connection pool near saturation (>=90% of max_connections=100)")
        lines.append("PRIMARY BOTTLENECK: postgres connection pool")
    elif hit_rate < 30:
        lines.append(f"WARNING: Valkey hit rate very low ({hit_rate:.1f}%) — most reads go to DB")
        lines.append(f"PRIMARY BOTTLENECK: {tier} (cache-cold DB reads)")
    elif p95 > 10:
        lines.append(f"PRIMARY BOTTLENECK: {tier} (p95={p95:.2f}s exceeds 10s SLO)")
    else:
        lines.append(f"PRIMARY BOTTLENECK: {tier}")

    if errors > 0:
        lines.append(f"ERRORS: {errors}/{total} requests returned 4xx/5xx/timeout on {worst_ep}")

    return "\n".join(lines)


def format_report(results: dict) -> str:
    bottleneck = identify_bottleneck(results)

    cold = results.get("cold", {})
    warm = results.get("warm", {})
    stress = results.get("stress_stats", {})
    wall = results.get("stress_wall_time_s", 0)
    n_users = results.get("concurrent_users", 0)

    lines = [
        "# Dashboard Stress Test Report",
        "**Date**: 2026-06-08",
        f"**Concurrent users**: {n_users}",
        f"**Instrument IDs tested**: {len(INSTRUMENT_IDS)} "
        f"({', '.join(['TSLA', 'AMZN', 'GOOGL', 'META', 'JPM', 'NFLX', 'AAPL'])})",
        "",
        "## 1. Baseline Latency (single user)",
        "",
        "| Endpoint | Cold (s) | Warm (s) |",
        "|----------|----------|----------|",
    ]

    all_eps = sorted(set(list(cold.keys()) + list(warm.keys())))
    for ep in all_eps:
        c = cold.get(ep, 0)
        w = warm.get(ep, 0)
        lines.append(f"| `{ep}` | {c:.3f} | {w:.3f} |")

    lines += [
        "",
        f"## 2. Stress Test Results ({n_users} concurrent dashboard loads)",
        f"**Total wall time**: {wall:.2f}s",
        "",
        "| Endpoint | p50 (s) | p95 (s) | p99 (s) | min (s) | max (s) | errors |",
        "|----------|---------|---------|---------|---------|---------|--------|",
    ]

    for ep, s in sorted(stress.items()):
        lines.append(
            f"| `{ep}` | {s['p50']:.2f} | {s['p95']:.2f} | {s['p99']:.2f} | "
            f"{s['min']:.2f} | {s['max']:.2f} | {s['errors']}/{s['n']} |"
        )

    lines += [
        "",
        "## 3. Infrastructure Stats",
        "",
        "### DB Connections — Baseline",
        "```",
        results.get("baseline_db_connections", "N/A").strip(),
        "```",
        "",
        "### DB Connections — Under Stress",
        "```",
        results.get("stress_db_connections", "N/A").strip(),
        "```",
        "",
        "### Valkey Stats — Baseline",
        "```",
        results.get("baseline_valkey", "N/A").strip(),
        "```",
        "",
        "### Valkey Stats — Under Stress",
        "```",
        results.get("stress_valkey", "N/A").strip(),
        "```",
        "",
        "### Docker Container Stats — Baseline",
        "```",
        results.get("baseline_docker_stats", "N/A").strip(),
        "```",
        "",
        "### Docker Container Stats — Under Stress",
        "```",
        results.get("stress_docker_stats", "N/A").strip(),
        "```",
        "",
        "## 4. Bottleneck Analysis",
        "",
        "```",
        bottleneck,
        "```",
        "",
        "## 5. Verdict",
        "",
    ]

    # Add concise verdict
    stress_items = sorted(stress.items(), key=lambda x: x[1]["p95"], reverse=True)
    if stress_items:
        worst_ep, worst_s = stress_items[0]
        second_ep, second_s = stress_items[1] if len(stress_items) > 1 else ("", {"p95": 0})

        verdict_lines = [
            f"**Primary bottleneck**: `{worst_ep}` (p95={worst_s['p95']:.2f}s under {n_users} concurrent loads)",
            "",
            "**Tiers ranked by p95 latency under stress:**",
        ]
        for ep, s in stress_items:
            tag = ""
            if "/top-movers" in ep or "/overviews" in ep:
                tag = "← market-data DB"
            elif "/dashboard/bundle" in ep:
                tag = "← api-gateway orchestration"
            elif "/dashboard/snapshot" in ep:
                tag = "← api-gateway cache"
            elif "/intelligence-bundle" in ep:
                tag = "← knowledge-graph / rag-chat"
            elif "/holdings" in ep:
                tag = "← portfolio service"
            verdict_lines.append(f"  1. `{ep}` p95={s['p95']:.2f}s {tag}")

        # Valkey hit rate assessment
        valkey_info = results.get("stress_valkey", "")
        hits = misses = 0
        for line in valkey_info.splitlines():
            if line.startswith("keyspace_hits:"):
                hits = int(line.split(":")[1])
            elif line.startswith("keyspace_misses:"):
                misses = int(line.split(":")[1])
        hit_rate = hits / max(hits + misses, 1) * 100

        verdict_lines += [
            "",
            f"**Valkey cache effectiveness**: {hit_rate:.1f}% hit rate — "
            + ("cache is helping" if hit_rate > 60 else "most requests bypass cache and hit DB"),
            "",
            "**DB connection pressure**: max_connections=100 (shared across all services)",
        ]
        lines += verdict_lines

    return "\n".join(lines)


async def main() -> None:
    print("=" * 60)
    print("Dashboard Stress Test")
    print("=" * 60)
    print(f"Target: {BASE}")
    print(f"Concurrent users: {CONCURRENT_USERS}")
    print(f"Instruments: {len(INSTRUMENT_IDS)}")
    print()

    print("Getting auth token...")
    results = await run_stress_test()

    report = format_report(results)

    output_path = (
        "/Users/arnaurodon/Projects/University/final_thesis/worldview"
        "/docs/audits/2026-06-06-stress-test-dashboard.md"
    )
    with open(output_path, "w") as f:
        f.write(report)

    print(f"\nReport saved to: {output_path}")
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(identify_bottleneck(results))


if __name__ == "__main__":
    asyncio.run(main())
