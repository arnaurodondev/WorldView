# Runbook: Error Observability

> **Owner**: On-call engineer
> **Last updated**: 2026-05-04 (PLAN-0065 T-E-03)
> **Related**: `docs/runbooks/sentry-alerts.md`, PRD-0034 §3 FR-T3-1

---

## Overview

The **Error Observability** Grafana dashboard (`worldview-error-observability`) provides
a Loki-based view of exception activity across all 10 backend services.
It complements Sentry (which gives stack frames and issue tracking) with
an aggregate view that is always visible, even when Sentry events are rate-limited.

**Dashboard URL**: `http://localhost:3100` (local dev) or your Grafana instance → Dashboards → Error Observability

---

## Panel Guide

### Panel 1 — Unhandled Exception Rate per Service

**What it shows**: Count of `unhandled_exception` structlog events per service per 5-minute window.

**Healthy baseline**: near-zero. A spike means 500-errors are occurring and being
captured by `register_error_handlers()` in `libs/observability/src/observability/error_capture.py`.

**What to do when it spikes**:
1. Select the affected service from the `$service` variable at the top.
2. Open Sentry → Issues → filter by the service tag to see the stack trace.
3. If the rate is extremely high (>20/window), check Panel 2 (rate-limiter) —
   Sentry may be dropping events to protect the free-tier quota.
4. Fix the root cause in the code; the exception rate should drop to zero.

---

### Panel 2 — Sentry Events Rate-Limited (Stat + Time Series)

**What it shows**: Count of Sentry events dropped by the `_before_send` per-fingerprint
rate-limiter (`libs/observability/src/observability/sentry.py`).

**Default rate limit**: 10 events per fingerprint per hour (`SENTRY_FINGERPRINT_RATE_LIMIT`).

**Healthy baseline**: 0. Non-zero means a single exception class is repeating fast enough
to exhaust the free-tier quota (5,000 events/month). The structlog record for each
dropped event includes the `fingerprint` field — use it to find the culprit in Sentry.

**What to do when non-zero**:
1. Check the Loki log line for `sentry_event_rate_limited` — extract the `fingerprint` value.
2. Open Sentry → Issues → search for that exception type + service.
3. Fix the root cause (most likely a query handler throwing on every request).
4. Consider raising `SENTRY_FINGERPRINT_RATE_LIMIT` temporarily if the event is important
   and you need more than 10 events per hour in Sentry while debugging.

---

### Panel 3 — Sentry Initialisation Status (Table)

**What it shows**: Per-service count of `sentry_initialised`, `sentry_disabled`, and
`sentry_init_failed` log events in the last hour.

| Event | Meaning |
|-------|---------|
| `sentry_initialised` | Sentry SDK started successfully in this service |
| `sentry_disabled` | `SENTRY_ENABLED=false` for this service (expected in dev/test) |
| `sentry_init_failed` | DSN misconfigured or Sentry unreachable at startup (investigate!) |

**What to do when `sentry_init_failed` appears**:
1. Check the service log for the `sentry_init_failed` event — it includes an `error` field.
2. Verify `SENTRY_DSN` and `SENTRY_ENABLED=true` are set in the service's environment.
3. Restart the service after fixing the configuration.

**What to do when `sentry_disabled` appears in production**:
This means `SENTRY_ENABLED=false` is set in the production env for that service.
Check `worldview-gitops/env/prod/<service>.env` and `values/<service>.yaml`.
Set `SENTRY_ENABLED=true` and `SENTRY_DSN=<dsn>`.

---

### Panel 4 — Top Exception Types (Table, last 24h)

**What it shows**: Top 10 exception events grouped by `service` and `path` (the HTTP
endpoint that triggered the exception). This gives on-call a "what is failing and where"
view without opening Sentry.

**What to do**: Use the `path` column to identify which endpoint is throwing,
then cross-reference with Sentry for the full stack trace.

---

## Drilling from Grafana to Sentry

1. Note the `service` and exception pattern from Grafana panels.
2. Open Sentry → `worldview-backend` project (or `worldview-web` for frontend).
3. Filter by `service:<name>` tag (set by `init_sentry()` via `sentry_sdk.set_tag`).
4. Find the matching issue — it includes the full stack trace, breadcrumbs, and user context.

---

## Dashboard Not Showing Data

**Symptom**: All panels show "No data".

**Possible causes**:
1. Loki is not running — check `docker compose ps loki`.
2. The `$service` variable is set to a service that has no logs — set to "All".
3. The time range is too narrow (default 24h) — widen to 7d.
4. Alloy (the Loki agent) is not scraping the service — check Alloy logs.
5. The service is healthy and truly has zero exceptions (this is the happy path).
