# QA Report: PLAN-0027 Full Implementation Review

**Date**: 2026-04-14 09:00 UTC
**Skill**: qa
**Scope**: PLAN-0027 — Frontend MVP UI (design canvas gaps + frontend code + backend auth/security)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL (design/code implementation severely incomplete; backend auth CRITICAL issues)
**Report file**: docs/audits/2026-04-14-qa-plan-0027-impl-review.md

---

## Executive Summary

This QA pass reviewed the full branch (1,543 changed files) spanning all 11 services, 6 libs, and the frontend. Three specialist agents independently reviewed frontend code quality, backend security, and design-vs-code gap analysis.

**Backend health is good**: 3,569+ unit tests pass across all services, ruff clean (1,479 files), mypy clean for all services with configs. The recent PLAN-0025 auth work is mostly solid (PKCE atomic, issuer validated in S9 middleware, JWKS endpoint correct) with three residual CRITICAL issues: InternalJWTMiddleware's fail-open unverified decode path, hardcoded issuer string, and brokerage routes reading headers instead of validated JWT claims.

**Frontend code is severely incomplete**: PLAN-0027 specifies a full professional financial terminal UI, but the actual frontend code implements only ~5-10% of the design spec. CompanyDetailPage, DashboardPage, and PortfolioPage are functional stubs (< 40 lines each). The 5-tab structure, header rows, entity graph, fundamentals accordion, news feed with tier badges — none of these exist in code. CSS tokens are also mismatched (legacy `--bg-secondary` vs canonical `--card`).

**Canvas design**: States B, C, D of Instrument Detail have never been built in the pencil.dev canvas. State F exists (sL0wd) but candlestick quality is poor (rectangles, no wicks). Status tracking in TRACKING.md and DESIGN.md was incorrectly showing all 6 states done — corrected during this session.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| Frontend Code | 14 source + 2 design docs | 21 | 1 | 4 | 8 | 8 | 0 |
| Security | 8 service files | 15 | 0 | 3 open (4 fixed) | 4 | 4 | 0 |
| Design Gap | 5 pages + gateway client | 23 | 0 | 12 | 9 | 2 | 0 |
| **Total** | — | **59** | **1** | **19** | **21** | **14** | **0** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents)

1. **CSS token mismatch**: Frontend agent (F-FE-001/002) + Design agent (F-DESIGN-017) both independently found that `index.css` uses `--bg-secondary`, `--text-secondary`, `--accent` instead of Midnight Pro canonical names (`--card`, `--foreground`, `--primary`).

2. **CompanyDetailPage tab structure missing**: Frontend agent (F-FE-003) + Design agent (F-DESIGN-001/006) both found no tab bar exists in CompanyDetailPage.tsx.

3. **Font compliance failure**: Frontend agent (F-FE-009/010) + Design agent's per-component check both confirmed IBM Plex Mono not applied to numeric values.

4. **Sidebar incomplete**: Frontend agent (F-FE-017) + Design agent (F-DESIGN-015) both found sidebar has no Watchlist or Alerts sections.

### Fixes Applied (Auto-fixable, Bucket A)

None applied in this session — all auto-fixable items are CSS/color changes that require file-by-file context to apply correctly. Listed in plan below.

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Lint (ruff check) | all libs + services | — | — | 0 | — | ✅ PASS |
| Format (ruff format) | 1479 py files | — | — | 0 | — | ✅ PASS |
| Type Check (mypy) | 6 services with mypy.ini | — | — | 0 | — | ✅ PASS |
| Library Unit | 6 libs | ~500+ | all | 0 | — | ✅ PASS |
| Service Unit | 9 services | 3,569 | 3,569 | 0 | — | ✅ PASS |
| Contract | (not run — no infra) | — | — | — | — | SKIP |
| Integration | (not run — no infra) | — | — | — | — | SKIP |
| E2E | (not run — no infra) | — | — | — | — | SKIP |
| Frontend Unit (vitest) | 7 test files | 36 | 36 | 0 | — | ✅ PASS |
| Frontend Type (tsc) | apps/frontend/ | — | — | 0 | — | ✅ PASS |
| Frontend E2E | not configured | — | — | — | — | N/A |

### Per-Service Breakdown (Unit tests)

| Service | Unit | Overall |
|---------|------|---------|
| portfolio | 476 pass | ✅ |
| market-data | 437 pass | ✅ |
| market-ingestion | 409 pass | ✅ |
| content-ingestion | 533 pass | ✅ |
| nlp-pipeline | 405 pass | ✅ |
| knowledge-graph | 577 pass | ✅ |
| rag-chat | 322 pass | ✅ |
| api-gateway | 76 pass | ✅ |
| alert | 334 pass | ✅ |

---

## BLOCKING Issues

### Finding F-FE-001: CSS Token Mismatch — Wrong Color Variables in index.css

**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Frontend Code Agent, Design Gap Agent

**Root Cause**: `apps/frontend/src/index.css` defines legacy variables (`--bg-primary: #0f172a`, `--bg-secondary: #1e293b`, `--accent: #3b82f6`) instead of the Midnight Pro P0 palette (`--background: #080A0E`, `--card: #10141C`, `--primary: #0EA5E9`). All components that use `var(--bg-secondary)` render with the wrong dark blue instead of `#10141C`.

**Evidence**:
```css
/* WRONG — current index.css */
--bg-primary: #0f172a;
--bg-secondary: #1e293b;
--accent: #3b82f6;

/* CORRECT — Midnight Pro P0 */
--background: #080A0E;
--card: #10141C;
--primary: #0EA5E9;
```

**Impact**: Every rendered page has wrong background colors, wrong accent colors. The visual output does not match the REDESIGN_PLAN design system at all.

**Fix** (Wave 1):
1. Replace all variables in `index.css` with canonical Midnight Pro names and values
2. Add IBM Plex Mono + IBM Plex Sans `@import`
3. Update all component references from old names to new names

---

## CRITICAL Issues

### F-SEC-001: InternalJWTMiddleware Fail-Open Unverified Decode

**Severity**: CRITICAL | **File**: `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py:141`

When JWKS is unavailable (startup race or S9 outage), the middleware decodes the JWT **without signature verification** (`options={"verify_signature": False}`), populating `request.state` with attacker-controlled claims. An attacker can forge any `tenant_id`, `user_id`, `role` and bypass authentication entirely during startup or S9 unavailability.

**Fix**: Remove unverified decode path. If public key unavailable, return 503 Service Unavailable. JWKS must be loaded before the app accepts traffic (enforce in lifespan startup sequence).

---

### F-SEC-009: Brokerage Routes Read Headers Not JWT Claims

**Severity**: CRITICAL | **File**: `services/portfolio/src/portfolio/api/routes/brokerage_connections.py:37-42`

`_require_user_headers()` reads `X-User-Id` and `X-Tenant-Id` from raw HTTP headers instead of from `request.state` (which InternalJWTMiddleware already validated). The headers are not signed and can be injected by any intermediary.

**Fix**: Replace `request.headers.get("X-User-Id")` with `request.state.user_id` (set by validated middleware).

---

### F-FE-003: CompanyDetailPage Missing Tab Bar and All 5 States

**Severity**: CRITICAL | **File**: `apps/frontend/src/pages/CompanyDetailPage.tsx`

The page renders only `<h2>`, an OHLCV chart, a news list, and similar companies panel. REDESIGN_PLAN P4 requires: 4-row header, 5-tab bar (Overview/Fundamentals/Intelligence/News/Chat), and full content for each state.

**Fix**: Wave 3–8 in the implementation plan below.

---

### F-DESIGN-008: DashboardPage Is a 5% Stub

**Severity**: CRITICAL | **File**: `apps/frontend/src/pages/DashboardPage.tsx`

DashboardPage.tsx only renders "Recent Alerts" (36 lines). REDESIGN_PLAN P3 requires 8 sections: Morning Brief, Portfolio Summary, Market Heatmap, Top Movers, Intelligence Stream, Watchlist News, Economic Calendar, Recent Alerts.

**Fix**: Wave 9 in the implementation plan.

---

## MAJOR Issues (Selected)

| Finding | Category | File | Fix Wave |
|---------|----------|------|----------|
| F-FE-009/010 | font-compliance | PredictionMarketsPanel, SimilarCompaniesPanel | W1 |
| F-FE-004/005/006/007 | design-token | SeverityBadge, FlashOverlay, PredictionMarketsPanel, SimilarCompaniesPanel | W1 |
| F-SEC-002 | security-auth | InternalJWTMiddleware hardcoded issuer | W11 |
| F-SEC-007 | security-config | RateLimitMiddleware silent fail-open | W11 |
| F-SEC-010 | security-secrets | SnapTrade credentials as plain str | W11 |
| F-DESIGN-010 | missing-feature | gateway-client.ts missing 6 endpoints | W8 |
| F-DESIGN-015 | style-gap | Sidebar missing Watchlist + Alerts | W2 |
| F-DESIGN-016 | missing-feature | No global search bar | W2 |
| F-DESIGN-021 | missing-feature | No top nav bar | W2 |
| F-DESIGN-018 | partial-impl | ScreenerPage table styling | W10 |
| F-DESIGN-022 | style-gap | OHLCVChart wrong candlestick colors | W1 |

## MINOR Issues

| Finding | Category | Fix |
|---------|----------|-----|
| F-FE-012..016 | test-coverage | Create 5 missing test files |
| F-FE-019 | font-compliance | Add IBM Plex font @import to index.css |
| F-SEC-008 | security-secrets | Standardize X-Tenant-ID header casing |
| F-SEC-012/013/015 | security-config | Config + logging improvements |
| F-DESIGN-022/023 | style-gap | OHLCVChart colors, expand chart button |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | PASS | No violations found |
| Service Structure | PASS | All services maintain hexagonal arch |
| Avro Schema Validation | SKIP | gen-contracts.sh not run in this session |
| Doc Freshness | WARN | DESIGN.md + TRACKING.md status markers corrected this session |
| Security Scan | WARN | F-SEC-001/009 require manual fix |
| Dependency Check | PASS | No new CVE-flagged packages identified |

---

## Portfolio Test Warning (MINOR)

```
PytestWarning: The test <Function test_initiate_request_tos_false_raises_validation_error>
is marked with '@pytest.mark.asyncio' but it is not an async function.
```
File: `services/portfolio/tests/unit/api/test_brokerage_connections.py:350`
Fix: Remove `@pytest.mark.asyncio` from 2 non-async test functions.

---

## Canvas Design Status (Corrected This Session)

| State | Canvas Node | Status |
|-------|-------------|--------|
| State A — Overview | wE7LT | ✅ DONE |
| State B — Fundamentals | VEVln | ⬜ NOT BUILT |
| State C — Intelligence | M1GXQ | ⬜ NOT BUILT |
| State D — News | jZEVF | ⬜ NOT BUILT |
| State E — Chat | RnKhf | ✅ DONE |
| State F — Full-Screen Graph | sL0wd | ⚠️ BUILT — candlestick quality poor |
| Intelligence/News page | tUPQd | ⬜ NOT BUILT |
| Portfolio page | 57eKB | ⬜ NOT BUILT |

---

## Recommendations

1. Execute Wave 11 (security fixes) immediately — F-SEC-001 is an auth bypass vulnerability
2. Execute Wave 1 (CSS foundation) before any other frontend work — everything else renders wrong
3. Execute Canvas waves C1–C4 in pencil.dev sessions (requires MCP connection)
4. Execute frontend waves W2–W10 in dependency order (sidebar before pages, tabs before content)
5. Execute Wave 14 (test coverage) after all feature waves complete

Report written to: docs/audits/2026-04-14-qa-plan-0027-impl-review.md
