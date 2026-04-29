# PLAN-0049 Wave C + Wave D — QA Iterations Report

**Date**: 2026-04-29
**Branch**: `feat/content-ingestion-wave-a1`
**Plan**: `docs/plans/0049-frontend-backend-stabilization-plan.md`
**Scope**: Final 8 unfinished tasks (Wave C × 4, Wave D × 4) — Waves A + B
already shipped via earlier commits and were marked done by this audit.

This audit captures the strict QA agent's findings across three iterations
on the Wave C + D batch implementation, the per-iteration fixes applied,
and the final SHIP verdict.

---

## Commits

| Commit | Subject |
|--------|---------|
| `c784782` | `feat(PLAN-0049): Wave C (backend wiring) + Wave D (frontend integration)` |
| `33c1e2a` | `fix(plan-0049-qa-iter1): close 1 CRITICAL + 6 MAJOR + 5 MINOR QA findings` |
| `e951722` | `fix(plan-0049-qa-iter2): close 1 CRITICAL regression + 3 MINOR doc/type fixes` |
| _next_   | `fix(plan-0049-qa-iter3): close 2 NITs + audit + TRACKING.md` |

---

## What landed in `c784782`

Two parallel implementation agents ran the remaining tasks:

**Wave C — Backend wiring (4 tasks)**:
- T-C-3-01: `services/alert/src/alert/scripts/backfill_alert_titles.py` —
  idempotent one-shot script that derives `title`/`signal_label`/
  `entity_name`/`ticker` for legacy `alerts` rows where `title IS NULL`.
  Mirrors `_derive_signal_label` + `_compose_alert_title` from the live
  `AlertFanoutUseCase`.
- T-C-3-03: `?category=` filter on `/signals/prediction-markets`
  end-to-end. Migration `010` adds nullable `category VARCHAR(50)` +
  partial index; plumbing through domain entity → ORM → repo SQL → use
  case → API router → api-gateway proxy.
- T-C-3-04: verified — `briefing_context._fetch_entity_articles`
  already used `limit=30` (no-op).
- T-C-3-05: docs updated for `alert-service.md`, `rag-chat.md`,
  `api-gateway.md`.

**Wave D — Frontend integration (4 tasks)**:
- T-D-4-02: `InstrumentAISubheader` expanded view now uses
  `<MarkdownContent size="compact">`.
- T-D-4-03: `IntelligenceTab` brief block uses
  `<MarkdownContent size="comfortable">` (replaced inline ReactMarkdown).
- T-D-4-05: 5 new Vitest test files (+14 specs).
- T-D-4-06: `e2e/stabilization-phase1.spec.ts` (4 Playwright scenarios).

---

## Iteration 1 — 12 findings

QA agent run on `c784782`. Verdict: NEEDS-FIXES; **1 CRITICAL** + **6 MAJOR**
+ **5 MINOR**.

### Closed in `33c1e2a`

| ID | Severity | Summary |
|----|----------|---------|
| F-QAC-01 | CRITICAL | Backfill missed JSONB type-codec — asyncpg returns JSONB as raw `str` by default, so `payload.get(...)` raised AttributeError on every row, got swallowed by the per-row except, and the script silently logged thousands of `derive_error` lines while updating zero rows. Fix: register `pg_catalog.jsonb` codec with `json.dumps`/`json.loads` on connect. |
| F-QAC-02 | MAJOR | `PgPredictionMarketRepository.upsert()` dropped `market.category` on insert / on-conflict / RETURNING — the entire write path was dead. Future polymarket adapter changes that emit `category` would silently fail to persist. Fix: add `category` to `.values()`, `set_=` with COALESCE policy (mirrors `market_slug` — never blank back to NULL on a poll without it), and the `.returning()` projection. |
| F-QAC-03 | MAJOR | `sector-heatmap-overflow` tests asserted `scrollWidth ≤ clientWidth` in jsdom where both default to `0` — tautology, never failed. Replaced with structural invariants: query tiles by aria-label suffix (`role=button` matched the period selector and capped at 3, missing the 11-tile assertion); assert closest `.overflow-hidden` ancestor exists; pin the post-fix `gap-0.5` class against regression to `gap-1`. |
| F-QAC-04 | MAJOR | Playwright SnapTrade scenario accepted "Activating your brokerage" loading copy — false-pass even if the page never hit the callback endpoint. Tightened to require "connected successfully" copy AND positively assert the request URL carried the v3-shaped query (later corrected in iter-2). |
| F-QAC-05 | MAJOR | `rag-chat.md` claimed both `<MorningBriefCard>` and `<InstrumentAISubheader>` render structured sections — false. Only `MorningBriefCard` does. Replaced with a per-surface table documenting actual fields each surface reads. |
| F-QAC-06 | MAJOR | SQL filter `LOWER(m.category) = :category` had zero test coverage. Added `ListPredictionMarketsUseCase` tests asserting `category="politics"` is forwarded to the repo port and `category=None` passes through verbatim. |
| F-QAC-07 | MAJOR | `PredictionMarketSummaryResponse` omitted `category` — frontend could filter but couldn't render category badges. Added optional field forwarded through both list and detail routers. |
| F-QAC-08 | MINOR | Backfill script had no unit tests — derivation logic could drift silently from `AlertFanoutUseCase`. Added 6 specs pinning each fallback rung against the live `_SIGNAL_LABEL_TABLE`. Side effect: moved the script from `services/alert/scripts/` to `services/alert/src/alert/scripts/` so it lives inside the importable package (the wheel only ships `src/alert/*`). |
| F-QAC-09 | MINOR | Gateway proxy comment claimed a non-existent security defence against client-spoofed `category=` duplicates (FastAPI parses from the same query string). Simplified to verbatim forward; rewrote comment to be honest about the explicit declaration's purpose (OpenAPI docs only). |
| F-QAC-10 | MINOR | Dead `^...$/m` regex in `recent-alerts.test.tsx` — `textContent` is a flat string with no `\n`. Replaced with substring assertions for both `"signal"` and `"alert"` suffix variants across 4 severities (8 total checks). |
| F-QAC-11 | MINOR | Backfill progress-log threshold logic broke if anyone tuned `_BATCH_SIZE` or `_PROGRESS_EVERY` off their 1000/10000 ratio. Replaced with explicit self-correcting threshold tracking. |
| F-QAC-12 | MINOR | Backfill connection lacked `application_name` and `command_timeout` — operator hygiene on multi-million-row jobs. Added both for `pg_stat_activity` identification and per-statement deadlock recovery. |

---

## Iteration 2 — 4 findings (1 was a regression I introduced)

QA agent run on `33c1e2a`. Verdict: NEEDS-FIXES; **1 CRITICAL** + **3 MINOR**.

### Closed in `e951722`

| ID | Severity | Summary |
|----|----------|---------|
| F-QAC-04-REGRESSION | CRITICAL | My iter-1 "tightened" Playwright assertions on the SnapTrade v4 callback **inverted the actual outbound URL contract**. The callback page (`callback/page.tsx:67-74,119-126`) DELIBERATELY renames v4's `connection_id` query param to v3's `authorizationId` before sending to S9 — so the gateway client builds `/v1/.../callback?authorizationId=...`, NOT `?connection_id=...`. My iter-1 assertions (`toContain("connection_id=")` + `not.toContain("authorizationId=")`) would have failed on the first real Playwright run. Iter-1's vitest+typecheck-only validation missed this because Playwright is not run in CI without a dev-server. **Lesson learned**: when tightening test assertions, read the page code (not just the URL the test feeds in). Fix: invert to assert the v3-shaped outbound URL. |
| F-QAC-05-DOC-ACCURACY | MINOR | `rag-chat.md` surface-contract table claimed `<MorningBriefCard>` reads `headline + summary + sections + citations` but the component never references `brief.headline`. Dropped `headline +`. |
| F-QAC-08-DOC-LAG | MINOR | The script moved to `src/alert/scripts/` in iter-1 but operator docs still showed the old `services/alert/scripts/` path. Updated `docs/services/alert-service.md` and the script's own `__doc__` to use `python -m alert.scripts.backfill_alert_titles` (cleanest invocation now that the script is an importable module). |
| F-QAC-07-FRONTEND-DRIFT | MINOR | Iter-1 added `category` to the wire response schema but the frontend `PredictionMarket` interface didn't declare it — type-safe consumers couldn't read it. Added `category?: string \| null`. |

---

## Iteration 3 — 2 NITs (cosmetic only)

QA agent run on `e951722`. Verdict: **SHIP**. All 4 iter-2 fixes verified
intact. Forward-looking sweep found two non-blocking cosmetic items.

### Closed in iter-3 commit (this one)

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| N-01 | NIT | `services/alert/src/alert/scripts/__init__.py` package docstring still mentioned the obsolete `services/alert/scripts/<name>.py` invocation. | Fixed — single `python -m alert.scripts.<name>` form. |
| N-02 | NIT | `_derive_for_row` annotated `payload: dict[str, Any]` but a JSONB row whose top-level value is a JSON array post-codec would be a `list`, surviving the truthy `or {}` and crashing on `.get(...)`. The outer try/except caught it, but the contract was dishonest. Added an explicit `isinstance(raw, dict)` coercion. | Fixed. |

---

## Verification (post iter-3)

```
api-gateway pytest:                250 passed (was 248 → +2 category contract)
market-data pytest -k prediction:   51 passed (was 49 → +2 use-case kwargs)
alert pytest tests/unit/scripts:     6 passed (NEW)
worldview-web vitest:              511 passed (was 497 → +14 stabilization)
worldview-web tsc + lint:           clean
```

Pre-existing failures NOT caused by this work (verified by reverting to
parent of `c784782` and reproducing):
- `market-data test_batch_request_min_max_length` (UUID validator — test
  fixture predates the validator).
- `market-data test_migrations_run_successfully` (needs Postgres infra).
- `market-data test_internal_jwt_rejects_wrong_issuer` (asyncio loop).

---

## Status

PLAN-0049 (Frontend & Backend Stabilization Phase 1) **SHIPS** with all
4 waves complete:
- Waves A + B: shipped in earlier commits (`45efe6c`, `01e848f`, etc.)
  and discovered already-landed during this audit.
- Wave C + D: shipped in `c784782` + iter-1/2/3 fixes.

---

## Notes for the next iteration

1. **Iter-1's CRITICAL F-QAC-01 (silent backfill no-op) is the most valuable
   finding** of this audit. The script tested green in unit tests because
   the unit tests fed `dict` directly; production reality (`asyncpg` JSONB
   round-trip) was different. Lesson: **a one-shot operational script
   should have at least one integration test against a real Postgres**
   even if it costs CI time. Consider adding such a test in PLAN-0051.
2. **Iter-2's CRITICAL was a regression I introduced in iter-1** — I
   tightened a Playwright assertion against the URL the test FEEDS rather
   than the URL the page SENDS, because I didn't read the callback page's
   v4→v3 rename logic. Lesson: when "tightening" a test, walk the full
   data flow before adjusting assertions; an inverted assertion is worse
   than a loose one because it green-lights the wrong contract.
3. **Three iterations were needed to converge** — same as PLAN-0050. The
   QA-loop's value is highest in iter-1 (catches systemic bugs the
   implementer can't see) and falls fast in iter-3 (NIT-only). A two-
   iteration default with a third only-on-needs is probably right.
