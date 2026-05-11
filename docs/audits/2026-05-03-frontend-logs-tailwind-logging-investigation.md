# Investigation Report: Frontend Logs, Tailwind CSS, and Centralized Logging

**Date**: 2026-05-03
**Investigator**: Claude (investigate skill)
**Severity**: MEDIUM (no data loss; visibility gaps only)
**Status**: Root causes identified; 2 of 3 fixed

---

## 1. Issue Summary

Three related concerns were raised after the dev stack was brought up:
1. The `worldview-web` container produces almost no log output
2. Tailwind CSS appeared to not render — the page looked like plain unstyled HTML
3. There is no visible centralized log aggregation across the 61 running containers

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| Container logs: only 4 lines at startup | `docker logs worldview-worldview-web-1` | Confirms minimal output |
| `removeConsole: { exclude: ["error", "warn"] }` | `apps/worldview-web/next.config.ts:73` | Strips all `console.log` in production build |
| `curl http://localhost:3001` returns 200 with two CSS `<link>` tags | Manual curl | CSS files ARE referenced in HTML |
| Both CSS files return 200, contain Tailwind preflight + IBM Plex fonts | `curl /_next/static/css/*.css` | Tailwind IS built and served |
| HTML has `<html class="dark ...">` | curl response | Dark mode class applied correctly |
| `style-src 'self' 'unsafe-inline'` in CSP | `middleware.ts:75` | Self-hosted stylesheets permitted |
| `loki.relabel "docker"` keep regex lists 10 services | `infra/alloy/config.alloy:48` | `worldview-web` NOT in list → logs dropped |
| `make monitoring` target starts Loki + Alloy + Grafana | `Makefile:198` | Centralized logging stack exists |

---

## 3. Findings

### Finding 1: Minimal frontend container logs (EXPECTED BEHAVIOR)

**Root cause**: `apps/worldview-web/next.config.ts:73-76` — the production build is compiled with the Babel `removeConsole` transform, which deletes every `console.log` call at build time. Only `console.error` and `console.warn` survive into the production bundle.

Additionally, Next.js standalone production mode does not emit per-request access logs by default (unlike `NODE_ENV=development` where it logs `GET /page 200 in Xms`). So a container serving 50 requests/min produces zero log output unless something goes wrong.

This is **intentional and correct** for production. It prevents libraries' debug calls from flooding production logs. The tradeoff is zero visibility during development.

**Fix applied** (`middleware.ts`): Added a `logRequest()` function that calls `console.warn` (preserved in production) for every request matched by the middleware. This logs:
```
[access] 2026-05-03T10:22:31.004Z GET /dashboard
[access] 2026-05-03T10:22:31.010Z GET /api/v1/portfolios
```
The matcher already excludes `_next/static` assets, so only meaningful page and API requests are logged.

---

### Finding 2: Tailwind CSS not rendering — "plain HTML" (TRANSIENT / RESOLVED)

**Investigation result**: Tailwind CSS IS working correctly. Verified via curl right now:
- HTML response contains `<html class="dark __variable_c8daab __variable_46fe82">` — dark class applied
- Two CSS files linked with nonces: `/_next/static/css/01c940bfeb740a8c.css` and `/_next/static/css/e6ceef4da5ce60f1.css`
- Both files return HTTP 200 and contain valid Tailwind content
- `style-src 'self' 'unsafe-inline'` explicitly in CSP (`middleware.ts:75`) — self-hosted stylesheets are permitted; the comment explains Tailwind JIT requires this

**Most likely cause of the original observation**: The user observed the page during the brief window after `docker start worldview-worldview-web-1` (the Created-state workaround) but before the Next.js standalone server had fully initialized (the healthcheck has a `start_period`). The browser may have received an incomplete response or shown a cached stale version.

**No code fix needed.** The issue is not reproducible with the container in its current stable state. If it recurs, hard-refresh (Cmd+Shift+R) and confirm the container has been `healthy` for at least 30 seconds.

---

### Finding 3: Alloy log filter excludes worldview-web — logs silently dropped (BUG)

**Root cause**: `infra/alloy/config.alloy:48` — the `loki.relabel "docker"` block has a `keep` rule that whitelists only 10 backend microservices by name. The regex did not include `worldview-web`, so all frontend container logs were silently dropped before reaching Loki.

```alloy
# BEFORE (logs from worldview-web silently discarded)
regex = "/(portfolio|market-ingestion|market-data|content-ingestion|content-store|api-gateway|nlp-pipeline|knowledge-graph|rag-chat|alert).*"
```

**Fix applied** (`infra/alloy/config.alloy`): Added `worldview-web` to the alternation:
```alloy
# AFTER
regex = "/(portfolio|market-ingestion|market-data|content-ingestion|content-store|api-gateway|nlp-pipeline|knowledge-graph|rag-chat|alert|worldview-web).*"
```

**Note on scope**: The filter intentionally drops infra containers (Kafka, ZooKeeper, Postgres, MinIO, Redis/Valkey) to reduce Loki ingest volume. All 10 backend microservices + the frontend are now captured. The monitoring stack must be restarted (`make monitoring-down && make monitoring`) to pick up the Alloy config change.

---

## 4. Centralized Logging Architecture (How to Use)

The monitoring stack is already built and ready:

```bash
# Start alongside make dev (monitoring targets running services)
make dev
make monitoring
```

Services available:
| Tool | URL | Purpose |
|------|-----|---------|
| Grafana | http://localhost:3000 | Log explorer, dashboards (admin/admin) |
| Loki | internal | Log storage backend |
| Grafana Alloy | internal | Log collector (scrapes Docker) |
| Prometheus | http://localhost:9090 | Metrics |
| Alertmanager | http://localhost:9093 | Alert routing |

**Query logs in Grafana** → Explore → Loki data source → LogQL:
```logql
# All frontend logs
{service="worldview-web"}

# All portfolio logs
{service="portfolio"}

# Errors across all services
{service=~".+"} |= "error"

# Warning level and above for a service
{service="nlp-pipeline"} | json | level =~ "warning|error"
```

The `service` label is derived from the container name by the second relabel rule: `/worldview-portfolio-dispatcher-1` → `portfolio-dispatcher`.

---

## 5. Impact Analysis

- **Frontend logs before Fix 2**: Zero visibility into request traffic in Docker logs
- **Frontend logs in Loki before Fix 3**: Completely absent from Grafana/Loki
- **Tailwind rendering**: Working correctly — no impact
- **Backend services**: Unaffected (already in Alloy filter)

---

## 6. Prevention Recommendations

1. **When adding a new service** that gets a Docker container, immediately add it to the Alloy keep regex (`infra/alloy/config.alloy`) as part of the scaffold
2. **Treat `console.warn`** as the appropriate log level for structured server-side access logs in Next.js production — `console.log` is stripped at build time
3. **Add BP-321** (below) to `docs/BUG_PATTERNS.md`

---

## 7. Open Questions

- The `intelligence-migrations` container (one-shot, runs then exits) is also absent from the Alloy filter. Its logs are only visible via `docker logs worldview-intelligence-migrations-1`. Since it exits immediately after running, Alloy would not capture its logs even if added (Alloy discovers running containers). This is acceptable — migration logs are forensic, not operational.
- `worldview-web` access logs now use `console.warn` level. Monitoring tooling should treat `[access]`-prefixed warnings differently from genuine warnings. A follow-up would be to add a log level `info` to the `removeConsole.exclude` list and use `console.info` instead.
