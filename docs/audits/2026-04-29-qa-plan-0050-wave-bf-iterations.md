# PLAN-0050 Wave B + F batch — QA Iterations Report

**Date**: 2026-04-29
**Branch**: `feat/content-ingestion-wave-a1`
**Plan**: `docs/plans/0050-dashboard-instruments-polish-plan.md`
**Scope**: Wave B (composite watchlist insights endpoint + WatchlistMovers redesign) + 5 of 13 deferred Wave F tasks

This audit captures the strict QA agent's findings across two iterations on the
Wave B + F batch implementation, the per-iteration fixes applied, and what
remains deferred.

---

## Commits

| Commit | Subject |
|--------|---------|
| `9044b20` | `feat(PLAN-0050): Wave B (insights endpoint + WatchlistMovers redesign) + 5 Wave F tasks` |
| `02ba0c2` | `fix(plan-0050-qa-iter1): close 2 BLOCKING + 3 CRITICAL + 4 MAJOR + 1 MINOR` |
| _next_   | `fix(plan-0050-qa-iter2): close 1 CRITICAL + 1 MINOR + audit + S6 contract fix` |

---

## Iteration 1 — 16 findings

QA agent run on `9044b20`. Verdict: 6/10 confidence; 2 BLOCKING, 8 CRITICAL,
6 MAJOR, 5 MINOR (some collapsed).

### Closed in `02ba0c2`

| ID | Severity | Summary |
|----|----------|---------|
| F-QA-01 | BLOCKING | `_safe_get` swallowed S1 auth errors on `/watchlists/{id}/members` — silent ownership leak. Members fanout now uses `_checked_get`; 403/404 propagate. New regression test asserts S1 403 → gateway 403. |
| F-QA-02 | BLOCKING | XSS via unvalidated `window.location.href`/`window.open` for S6 article URLs (React's auto-sanitisation does NOT cover imperative APIs). New `isSafeNewsUrl()` helper accepts only `http:`/`https:`. Both `PortfolioNewsWidget.handleClick` and `BiggestNewsRow` gate on it. 4-spec coverage. |
| F-QA-03 | CRITICAL | `useNewsLinkTarget` writes did not propagate to other hook instances in the same tab (only cross-tab `storage` events fire natively). Now dispatches a synthetic `StorageEvent` (no `storageArea` — jsdom + some browsers reject it for non-real-Storage instances, silently aborting the dispatch). Listener accepts `e.key === null` for synthetic events. |
| F-QA-04 | CRITICAL | The T-F-6-08 fix (52WeekRangeBar vertical alignment) had only the populated branch — the no-data branch still used the broken flex-col layout. Now both branches short-circuit on `!showLabels`. |
| F-QA-05 | CRITICAL | 3 backend tests added — S1 auth propagation (F-QA-01), member without `entity_id` does NOT match empty-string alert (F-QA-06), malformed `published_at` handled gracefully. |
| F-QA-06 | MAJOR | Defensive `bool(eid) and eid in alerts_by_entity` guard against an empty-string entity_id false-positive. |
| F-QA-07 | MAJOR | Row-level enrichment badges (newspaper count + alert dot) gated on `showEnrichmentBadges = period === "1D"` — prevents 1D semantics leaking into 1W/1M views. aria-label enumeration follows the same gate. |
| F-QA-09 | MAJOR | New 1W period regression test verifies OHLCV-derived change_pct overrides the insights' 1D change_pct after period switch. |
| F-QA-10 | MAJOR | OHLCV chart container now always-mounted; Skeleton overlays via `absolute inset-0 pointer-events-none` only on first load; "refreshing" pill renders only when `isLoading && data`. Closes the effect-ordering race between Skeleton unmount and lightweight-charts WebGL init. |

### Iter-1 deferred (judged acceptable for ship)

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| F-QA-08 | MAJOR | Hardcoded `member_overview_cap=25` and `news_lookback_hours=24` not exposed via query params; no `enrichment_truncated` flag on the response | Deferred — current scope (≤25-symbol watchlists) makes this academic; expose as needed when watchlist size grows. |
| F-QA-11 | MINOR | Imports inside function body in `clients.py` | Deferred — cosmetic. |
| F-QA-12 | MINOR | Vitest setup polyfill is unconditional, masks future jsdom upgrades | Deferred — acceptable until Vitest ships a real Storage shim. |
| F-QA-13 | MINOR | Dead `try/except` block in route handler | Resolved by F-QA-01 (now reachable). |
| F-QA-14 | MINOR | `cast("int", x["count"])` lacks an explanatory comment | Deferred. |
| F-QA-15 | MINOR | Visual alignment between row + sub-headers after 6px slot | Deferred — superseded by F-QA-07 which removes the slot on non-1D entirely. |
| F-QA-16 | MINOR | Biggest news amber tint heaviness | Deferred — visual polish. |

---

## Iteration 2 — 4 new findings

QA agent run on `02ba0c2`. Verdict: NEEDS-ITER-2-FIXES; 1 CRITICAL contract
mismatch, 3 MINOR. All 10 iter-1 closures CONFIRMED-CLOSED via code reading.

### Closed in iter-2 commit

| ID | Severity | Summary |
|----|----------|---------|
| F-QA2-01 | CRITICAL | The composer read `art.get("entity_ids")` (plural list) but S6's actual `RankedArticleResponse` schema emits `primary_entity_id` (singular UUID). In production, `news_by_entity` was always empty → every member's `news_count_24h` was 0 and `biggest_news` was always None — the entire news-enrichment half of the insights endpoint silently degraded. The 11-spec backend test passed because fixtures used the wrong shape, MASKING the production bug. Fix: composer now reads `primary_entity_id` (correct contract) AND falls back to `entity_ids` list for forward-compat with any future multi-entity schema. Fixtures rewritten to match the real S6 contract. New legacy-list-shape test pins the fallback path. |
| F-QA2-02 | MINOR | `PortfolioNewsWidget.ArticleRow` granted focus + role=button for any truthy article URL — including `javascript:` URLs that F-QA-02 silently blocks. Keyboard users could tab into a dead row that did nothing on Enter. Now `isSafeNewsUrl()` gates `tabIndex`, `role`, `onClick`, `onKeyDown`, hover cursor, and `aria-label` — unsafe URLs make the row fully non-interactive (skipped by AT and keyboard nav). |

### Iter-2 deferred (judged acceptable for ship)

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| F-QA2-03 | MINOR | Listener accepts `e.key === null` so any cross-tab `storage` event triggers a re-read. One localStorage lookup per event — cheap; widens contract slightly. | Deferred — the synthetic-event path requires this loose match; revisit when more keyed prefs land. |
| F-QA2-04 | MINOR | Stale comment "PLAN-0049 added top-level entity_id…" in `clients.py` predated F-QA2-01 fix | Resolved by the F-QA2-01 fix (comment rewritten). |

---

## Verification (post iter-2)

```
api-gateway pytest:         247 passed (was 244 → +3)
worldview-web typecheck:    PASS  (tsc --noEmit, no output)
worldview-web vitest:       497 passed (was 491 → +6)
worldview-web lint:         No ESLint warnings or errors
```

Tests grew from 480 (pre Wave B + F) → 491 (Wave B + F shipped) → 497 (post
iter-1) → 497 (post iter-2 in count, but 1 widget test rewritten to cover the
1W path and 4 new tests covered the F-QA2-01 contract). Backend grew by 7
specs across the two iterations.

---

## Status

PLAN-0050 Wave B + Wave F batch (5 of 13 deferred) **SHIPS** subject to one
more QA iteration to confirm iter-2 closures held without new regressions.

Wave F still deferred (8 tasks): T-F-6-03 (padding standard), T-F-6-05
(responsive breakpoints below 1024px), T-F-6-07 (sparkline axes), T-F-6-11
(FundamentalSparkline showAxis — already wired), T-F-6-12 (skeleton 9-section
match), T-F-6-13 (no news date filter component exists), T-F-6-16 (sidebar
scroll unification), T-F-6-18 (mobile baseline — plan explicitly says skip
for thesis demo).

---

## Notes for the next iteration

- The F-QA2-01 finding is the strongest argument yet for keeping QA test
  fixtures **schema-driven** rather than hand-rolled. A `RankedArticleResponse`
  fixture imported from a shared schema-conformance module would have caught
  the contract mismatch immediately. Worth investing in next time we touch
  the gateway test layer.
- `useNewsLinkTarget`'s loose `e.key === null` listener is acceptable today
  (one preference) but will get noisy as more prefs land. Consider migrating
  to a custom event bus (`worldview:prefs:*`) when adding the second pref.
