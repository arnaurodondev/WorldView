# W9 Completion Report — Visible Regression Cleanup + Full Observability

> **Date**: 2026-05-04
> **Plan**: PLAN-0065 Wave E
> **PRD**: PRD-0034 §3 FR-T2-3 + FR-T3-1
> **Status**: CODE COMPLETE — Operational verification pending live environment

---

## Executive Summary

PLAN-0065 Wave E ships all code-deliverable items for the UptimeRobot uptime
monitoring, public status page, Grafana error-observability dashboard, Sentry
alert runbook, and monitoring contract test. Operational verification items
(live UptimeRobot monitors, Sentry alert rule screenshots, email delivery test)
require a publicly-accessible deployment environment and are tracked as follow-up
actions below.

---

## Deliverables Shipped

### T-E-01 — UptimeRobot contract test + runbook

| Item | Status | Evidence |
|------|--------|---------|
| `services/api-gateway/tests/contract/test_health_keyword_stability.py` | ✅ DONE | 3 tests pass: 200 response, `"status":"ok"` literal present, valid JSON |
| `docs/runbooks/uptime-monitoring.md` | ✅ DONE | Includes monitor setup steps, `/healthz` vs `/readyz` rationale, API key scoping, rotation procedure |
| UptimeRobot account created | ⏳ PENDING | Requires public URL (staging/prod environment) |
| Monitor 1 `/healthz` active | ⏳ PENDING | Requires public URL |
| Monitor 2 `/readyz` active | ⏳ PENDING | Requires public URL |
| Read-only API key generated | ⏳ PENDING | Requires UptimeRobot account |
| Test alert fires within 10 min | ⏳ PENDING | Requires live monitor |

### T-E-02 — Public status page

| Item | Status | Evidence |
|------|--------|---------|
| `app/(public)/status/page.tsx` | ✅ DONE | Server Component; renders per-component pills, 30-day strip, incident banner |
| `app/(public)/status/api/uptime/route.ts` | ✅ DONE | Server-only; `UPTIMEROBOT_READONLY_API_KEY` never exposed client-side |
| `app/(public)/status/api/uptime/helpers.ts` | ✅ DONE | Pure functions `projectMonitor()` + `readIncidentsSync()` (testable without Next.js runtime) |
| `app/(public)/status/components.ts` | ✅ DONE | `resolveComponentLabel()`, `statusInfo()`, type definitions |
| `app/(public)/status/incidents.json` | ✅ DONE | Empty array (no active incidents) |
| `__tests__/status-page.test.tsx` | ✅ DONE | 17 tests covering: up/down state, 30-day strip, incident banner (yes/no), per-component labels, no direct UptimeRobot calls |
| `__tests__/status-uptime-route.test.ts` | ✅ DONE | 7 tests: url stripped, alert_contacts stripped, other sensitive fields stripped, whitelisted fields preserved, 30 buckets, readIncidentsSync fail-open |
| `grep -r 'NEXT_PUBLIC_UPTIMEROBOT' apps/worldview-web/` | ✅ PASS | 0 results — API key never exposed as NEXT_PUBLIC_* |
| Status page accessible at `/status` | ⏳ PENDING | Requires live deployment |

### T-E-03 — Grafana error-observability dashboard

| Item | Status | Evidence |
|------|--------|---------|
| `infra/grafana/dashboards/error-observability.json` | ✅ DONE | 4 panels: exception rate, rate-limiter stat+timeseries, init status table, top exception types |
| `docs/runbooks/error-observability.md` | ✅ DONE | Panel guide, drill-down steps, escalation |
| Dashboard import into running Grafana | ⏳ PENDING | Requires live Grafana instance |

### T-E-04 — Sentry alert rules

| Item | Status | Evidence |
|------|--------|---------|
| `docs/runbooks/sentry-alerts.md` | ✅ DONE | Documents 4 rules, UI paths, escalation ladder, email update procedure |
| Rule 1: New Issue alert configured | ⏳ PENDING | Requires Sentry SaaS UI |
| Rule 2: Regression alert configured | ⏳ PENDING | Requires Sentry SaaS UI |
| Rule 3: Error Spike alert configured | ⏳ PENDING | Requires Sentry SaaS UI |
| Rule 4: Quota 80% alert configured | ⏳ PENDING | Requires Sentry SaaS UI |
| Email delivery test (new issue → email within 5 min) | ⏳ PENDING | Requires live Sentry + DSN |

### T-E-05 — PRD-0034 §3 FR-T3-1 amendment

| Item | Status | Evidence |
|------|--------|---------|
| "Atlassian Statuspage" reference removed | ✅ DONE | PRD §3 FR-T3-1 at line 98 already reflects the in-tree Next.js page decision (amended during Wave D preparation on 2026-05-03). The amendment was applied before this wave started — no further edit required. |

### T-E-07 — Footer Status link

| Item | Status | Evidence |
|------|--------|---------|
| `components/landing/Footer.tsx` — Status href updated | ✅ DONE | `https://status.worldview.local` → `/status` (in-tree route, no external dependency) |
| Globe icon link updated | ✅ DONE | `<a href="https://status.worldview.local">` → `<Link href="/status">` |

---

## Test Counts

| Suite | Before Wave E | After Wave E | Delta |
|-------|--------------|--------------|-------|
| Frontend Vitest | 1,726 | 1,750 | +24 |
| api-gateway contract | 0 | 3 | +3 |
| **Total new tests** | | | **+27** |

---

## FR-T2-3 Acceptance Status

(Wave B first verified; re-confirming at Wave E close.)

1. **WCAG AA on `text-muted-foreground`**: Previously verified in Wave B. Status page
   uses `text-muted-foreground` with ≥4.5:1 contrast (Terminal Dark palette verified
   in PLAN-0069 Bloomberg-grade audit 2026-05-04).

2. **Zero `/undefined` 500-errors**: F-E8 guard shipped in commit `f27e266b` (before Wave A).
   Contract test `services/api-gateway/tests/contract/test_health_keyword_stability.py`
   ensures the keyword format is stable.

3. **Article-consumer offset healthy**: Verified in Wave B (T-B-02/T-B-03).

4. **F-D4 backend EU date parse**: Verified in Wave B (T-B-03/T-B-04 — `_parse_event_date`
   confirmed correct, EU economic events replayed).

---

## FR-T3-1 Acceptance Status

| Item | Status | Notes |
|------|--------|-------|
| Sentry on all 10 backends | ✅ DONE | Wave C T-C-05/T-C-05-EXT wired `init_sentry()` in all 10 services |
| Frontend `@sentry/nextjs` | ✅ DONE | Wave D T-D-01/T-D-02/T-D-03 |
| PII guard (`before_send`) | ✅ DONE | Wave C + D — unit tests for both backend and frontend strips |
| Status page accessible | ✅ CODE DONE | `/status` route exists; live deploy pending |
| UptimeRobot dual monitors | ⏳ PENDING | Requires public URL |
| Grafana dashboard live | ✅ CODE DONE | JSON provisioned to `infra/grafana/dashboards/`; visible in next `make dev` |
| Sentry alert rules active | ⏳ PENDING | Requires Sentry SaaS UI configuration |
| Synthetic exception captured ≤60s | ⏳ PENDING | Requires DSN + live Sentry |

---

## Security Review

| Check | Result |
|-------|--------|
| No `NEXT_PUBLIC_UPTIMEROBOT*` in codebase | ✅ PASS — `grep -r 'NEXT_PUBLIC_UPTIMEROBOT' apps/worldview-web/` = 0 results |
| `url`, `alert_contacts` stripped in projection | ✅ PASS — enforced by `projectMonitor()` + 2 unit tests |
| API key never in client JS bundle | ✅ PASS — `UPTIMEROBOT_READONLY_API_KEY` read only in Node-runtime Route Handler |
| Status page shows uptime only (PRD §9) | ✅ PASS — no error details, no stack traces, no internal hostnames |
| No hardcoded emails in codebase for Sentry alerts | ✅ PASS — alert destinations in Sentry UI only |

---

## Pending Operational Actions (User Must Complete)

The following items require a live environment with a publicly-accessible URL.
When completed, update this report with screenshot evidence.

1. **Create UptimeRobot account** → configure 2 monitors → generate read-only API key
   → set `UPTIMEROBOT_READONLY_API_KEY`, `UPTIMEROBOT_MONITOR_ID_HEALTHZ`, `UPTIMEROBOT_MONITOR_ID_READYZ` in gitops env files
2. **Configure 4 Sentry alert rules** per `docs/runbooks/sentry-alerts.md`
3. **Verify Sentry capture ≤60s**: trigger synthetic exception via `/(app)/dev-tools/sentry-test` route in staging with `NEXT_PUBLIC_SENTRY_DSN` set
4. **Verify status page live**: navigate to `/status`, confirm 30-day strip visible, check no `api.uptimerobot.com` calls in browser DevTools
5. **Verify Grafana dashboard**: open Error Observability dashboard in Grafana, confirm all 4 panels load
6. **Verify UptimeRobot alert delivery**: temporarily set keyword to `"status":"impossible"` → alert fires → revert
7. **Verify Sentry email delivery**: trigger synthetic exception → "New Issue" email arrives within 5 min

---

## Cross-References

- Plan: `docs/plans/0065-w9-regression-cleanup-observability-plan.md`
- Revision audit: `docs/audits/2026-05-03-revise-plan-0065-w9.md`
- PRD: `docs/specs/0034-mvp-launch-readiness-program.md` §3 FR-T2-3 + FR-T3-1
- Prior waves: Wave A (2026-05-04), Wave B (2026-05-04), Wave C (2026-05-04), Wave D (2026-05-04)
