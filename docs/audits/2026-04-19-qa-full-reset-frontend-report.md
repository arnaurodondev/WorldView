# QA Report: Full Platform Reset + Frontend Runtime Validation

**Date**: 2026-04-19 08:30 UTC
**Skill**: qa
**Scope**: full (clean reset + frontend + dev-login + seed data)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: **PASS**
**Report file**: docs/audits/2026-04-19-qa-full-reset-frontend-report.md

---

## Executive Summary

Complete platform reset (`make dev-reset`) followed by clean `make dev` launch. All 52 containers healthy (10 APIs + 31 workers + 6 infra + 2 ML + 3 dev tools). Frontend serves pages at :3001, proxies API calls to gateway at :8000 via Next.js rewrites. Dev login flow works end-to-end: `POST /v1/auth/dev-login` → JWT → authenticated API calls return seeded data. Three issues discovered and fixed during this pass.

---

## Issues Found & Fixed

### 1. Port conflict: Kafka UI vs GLiNER (8090)
- **Root cause**: Both `kafka-ui` (dev overlay) and `gliner-server` (base compose) mapped to host port 8090
- **Fix**: Changed kafka-ui to port 8092 in `docker-compose.dev.yml`

### 2. Seed script `\connect` broken in piped SQL
- **Root cause**: PostgreSQL `\connect` metacommand doesn't work when SQL is piped via `docker exec psql -f /dev/stdin`
- **Fix**: Replaced `scripts/seed-dev-data.sql` with `scripts/seed-dev-data.sh` that makes separate `psql -d <db>` calls per database

### 3. Dev-login token rejected by gateway auth middleware
- **Root cause**: `OIDCAuthMiddleware` skipped auth entirely when OIDC was unavailable — it never checked the Bearer token. Dev-login issues a gateway-signed internal JWT, but the middleware didn't recognize it without OIDC config.
- **Fix**: Added internal JWT validation fallback in `OIDCAuthMiddleware.dispatch()` — when OIDC is unavailable and a Bearer token is present, validates it as an internal JWT using the gateway's own RSA public key. Looks up user from Valkey cache.

### 4. pgweb healthcheck uses wget (not available)
- **Fix**: Changed to `curl -sf` in dev compose overlay

---

## Validated Flows

| Flow | Result |
|------|--------|
| `make dev-reset` + `make dev` | 52/52 containers healthy |
| `make seed` | 5 instruments, 1 user, 1 portfolio, 1 watchlist |
| `POST /v1/auth/dev-login` | Returns RS256 JWT (765 chars) |
| Bearer token → `GET /v1/portfolios` | 200 — Demo Portfolio |
| Bearer token → `GET /v1/watchlists` | 200 — Tech Watchlist |
| Bearer token → `GET /v1/market/heatmap` | 200 — 11 GICS sectors |
| `GET /v1/search/instruments?q=AAPL` (public) | 200 — returns Apple Inc. |
| `GET /v1/fundamentals/screen/fields` (public) | 200 — 12 screener fields |
| Frontend at :3001 | 200 on /, /login, /dashboard, /callback |
| Frontend `/api/*` proxy | 200 — proxies to gateway correctly |
| MailHog at :8025 | 200 |
| pgweb at :8091 | 200 |
| Kafka UI at :8092 | 200 |
| MinIO Console at :7481 | 200 |

---

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| Backend unit (10 services) | 3,471 | PASS |
| Architecture | 95 | PASS |
| worldview-web Vitest | 237 | PASS |
| TypeScript (tsc) | — | PASS |
| ruff check | 1,485 files | PASS |
| ruff format | 1,485 files | PASS |
| **Total** | **3,803** | **PASS** |

---

## Verdict: **PASS**

The platform launches cleanly from scratch with `make dev`, seeds data with `make seed`, authenticates via dev-login, and serves real data through the frontend. All tests pass.

Compounding check: no additional document updates needed — docs agent already updated all files in the previous pass.
