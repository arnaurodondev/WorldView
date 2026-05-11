# Runbook: Uptime Monitoring

> **Owner**: On-call engineer
> **Last updated**: 2026-05-04 (PLAN-0065 T-E-01)
> **Related**: `docs/runbooks/sentry-alerts.md`, PRD-0034 §3 FR-T3-1

---

## Overview

Worldview uses **UptimeRobot** (free tier, 50 monitors) to probe the API Gateway
from an external network. Two monitors are configured:

| Monitor | URL | Interval | Alert threshold | What it signals |
|---------|-----|----------|-----------------|-----------------|
| `/healthz` — liveness | `https://<prod-domain>/healthz` | 5 min | 1 failure | Process is down — page immediately |
| `/readyz` — readiness | `https://<prod-domain>/readyz` | 15 min | 3 consecutive failures | Dependency (Valkey) is down — caching degraded |

**Why two monitors**: `/healthz` catches "gateway dead → no UI" immediately.
`/readyz` catches the slower-burning class "Valkey down → briefs stale or 503-ing"
without false-positive alarm fatigue from transient blips.

---

## Why `/healthz` Not `/v1/health`

The api-gateway does **not** have a `/v1/health` route. The correct routes are:
- `GET /healthz` — returns `{"status":"ok"}` (HTTP 200 when process is alive)
- `GET /readyz` — returns `{"status":"ok"}` + Valkey check (HTTP 200 = healthy, 503 = degraded)

Verified at `services/api-gateway/src/api_gateway/routes/health.py`.

UptimeRobot uses keyword check `"status":"ok"` on `/healthz`.
The contract test `services/api-gateway/tests/contract/test_health_keyword_stability.py`
asserts this literal string is always present so a future response-shape change
is caught at PR time before it silently breaks the monitor.

---

## UptimeRobot API Key — Security Scoping

The API key used for the public status page is **monitor-scoped read-only**,
not the main account key. This limits the blast radius if the key leaks:
- Can only read monitor status (not modify monitors or contacts)
- Cannot access billing, account settings, or alert contact details

The key is stored as `UPTIMEROBOT_READONLY_API_KEY` environment variable.
It is **never** set as `NEXT_PUBLIC_*` — setting it client-side would expose
it in the browser's network requests and JS bundle.

### How to rotate the key

1. Log into UptimeRobot dashboard → My Settings → API Keys
2. Revoke the old monitor-scoped key
3. Generate a new monitor-scoped read-only key
4. Update `UPTIMEROBOT_READONLY_API_KEY` in `worldview-gitops/env/prod/worldview-web.env`
   and `worldview-gitops/values/worldview-web.yaml` (SOPS-encrypted)
5. Roll the worldview-web deployment (the Route Handler reads the env var at request time)

---

## Setting Up the Monitors (Reproducible Steps)

1. Create a UptimeRobot account at `https://uptimerobot.com` (free tier).
2. **Monitor 1 — `/healthz` liveness:**
   - Type: HTTP(s)
   - URL: `https://<prod-domain>/healthz`
   - Monitoring Interval: 5 minutes
   - Monitor Timeout: 30 seconds
   - Keyword: `"status":"ok"` (type: Keyword exists)
   - Alert Contacts: founder email (alert threshold: 1 failure)
3. **Monitor 2 — `/readyz` readiness:**
   - Type: HTTP(s)
   - URL: `https://<prod-domain>/readyz`
   - Monitoring Interval: 15 minutes
   - Alert Contacts: founder email (alert threshold: 3 consecutive failures)
4. Generate a **Monitor-Scoped Read-Only API Key** (My Settings → API Keys → Add API Key):
   - Name: `worldview-web-status-page`
   - Scope: read-only
   - Capture the key as `UPTIMEROBOT_READONLY_API_KEY`
5. Record both monitor IDs as `UPTIMEROBOT_MONITOR_ID_HEALTHZ` and `UPTIMEROBOT_MONITOR_ID_READYZ`
   in the gitops env files.
6. Set `STATUS_PAGE_URL` to `https://<prod-domain>/status`.

---

## Responding to Alerts

### `/healthz` alert (1 failure → page immediately)

The API Gateway process is down. Users cannot reach the application at all.

1. Check Grafana → Service Overview → api-gateway panel for recent errors.
2. Check Docker/Kubernetes logs for the `api-gateway` container.
3. Check Sentry → Error Observability for any crash-loop exception.
4. Restart the container if healthy checks show it exited.
5. If the root cause is a code regression, roll back the last deployment.

### `/readyz` alert (3 consecutive failures ≈ 45 min sustained degradation)

Valkey is unreachable. The gateway is alive but:
- Rate limiting is degraded (fail-open: requests pass without limiting)
- JWT jti checks are disabled (replay possible)
- Brief/alert caches are stale

1. Check Valkey container health: `docker inspect worldview_valkey | grep Status`
2. Check Valkey logs for OOM or connection errors.
3. Restart Valkey if it crashed.
4. Once Valkey is back, the gateway reconnects automatically (the client has a connection pool).

---

## Free-Tier Quota

- 50 monitors total (using 2)
- 10 alert contacts total (using 1)
- 5-minute minimum check interval (using 5 min for healthz, 15 min for readyz)

No quota concern for the MVP.

---

## Future: Adding More Monitors

As W6 (full-text search) and W4 (AI briefs) add dedicated health endpoints,
add UptimeRobot monitors for them. Update `app/(public)/status/components.ts`
with the new `component_label` mapping so the status page shows meaningful
pills ("Search", "AI Briefs") rather than raw monitor names.
