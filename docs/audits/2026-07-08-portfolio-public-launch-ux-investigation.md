# Investigation Report: Portfolio Experience — Public-Launch UX Readiness

**Date**: 2026-07-08
**Investigator**: Claude (`/investigate`, 4 parallel subagents)
**Severity**: HIGH (UX blockers, not correctness/data-loss)
**Status**: Root causes identified; ready for `/prd` (dual-mode) + `/fix-bug` (quick wins)

## 1. Issue Summary

The owner is making the portfolio product **public** and is concerned the portfolio page is
too complex for ordinary users across four flows: **creating a portfolio, adding a position,
connecting a brokerage, and deleting a position**. Four subagents traced the actual code
(frontend `apps/worldview-web`, backend `services/portfolio` + S9 gateway).

**Verdict**: The plumbing is largely sound and secure. The gap is **UX surface**: (a) the page
defaults to a power-user information wall, (b) a few high-value manual actions are missing or
hidden, and (c) the brokerage flow's copy under-sells its own safety and mis-sets timing
expectations. No data-integrity blockers. Estimated ~2–3 focused days for the must-fixes.

## 2. Two agent claims corrected during verification

| Claim | Reality (verified) |
|---|---|
| "No ticker→instrument search endpoint; users must paste UUIDs" (backend agent) | **FALSE.** `searchInstruments()` → `/v1/search/instruments` (S3 ILIKE) exists; exact-match `/v1/instruments/lookup?symbol=X` and `POST /v1/instruments/resolve-tickers` also exist. AddPositionDialog resolves tickers fine. Real issue = submit-time + 2–4s cold, no typeahead. `lib/api/search.ts:43,196-207` |
| "ManualPortfolioEmptyState not rendered (BUG)" (manual-flows agent) | **FALSE.** Rendered at `features/portfolio/components/HoldingsTab.tsx:622`, correctly gated manual+0-holdings. Agent read the wrong path (`components/portfolio/` vs `features/`). No bug. |

## 3. What is actually solid (do not touch)

- **Backend CRUD**: portfolio create/patch/archive, transaction recording — tight Pydantic
  validation, idempotency keys, clean domain→HTTP error mapping. `portfolio.py`, `transaction.py`, `error_mapping.py:24-45`
- **Brokerage integration is REAL and secure**: SnapTrade SDK v11, 25+ brokers, production
  creds present. `snaptrade_user_secret` never logged; raw API responses never logged; OAuth
  read-only (`connection_type="read"` hardcoded); JWT ownership check on callback.
  `snaptrade_client.py:197,249`, `brokerage_connection.py:39-51,185-189`
- **Empty states for 0-portfolios and 0-holdings** are clean and context-aware.
  `page.tsx:379-427`, `HoldingsTab.tsx:578-630`
- **Auth/tenant isolation**: all queries tenant-scoped; no cross-tenant leakage observed.

## 4. Root-cause findings, by flow

### 4a. Overall page complexity — THE primary concern (page-IA agent)
Main `/portfolio` renders a **6-layer, 40+ component** wall: 8-tile KPI strip, 3 overview
panels (β-adjusted exposure, leverage, HHI concentration), equity curve w/ SPY overlay,
14-column holdings table (Risk Δ, β-Adjusted, SPARK), 3-panel bottom cluster, 4 tabs whose
Analytics tab is ~entirely expert-only (Sharpe/Sortino/Calmar/Alpha/CAGR). A new user with
holdings lands straight into this with **no progressive disclosure and no tour**.
Cognitive-load rating: **7.5/10 overwhelming**. Files: `page.tsx:441-580`, `HoldingsTab.tsx`,
`PortfolioKPIStrip.tsx`, `SemanticHoldingsTable.tsx`, `AnalyticsTab.tsx`.

### 4b. Create portfolio (manual-flows agent)
Three required fields incl. **Cost-Basis-Method dropdown (FIFO/AVCO)** — accounting jargon on
step one. Validation is submit-time only (no onChange). `CreatePortfolioDialog.tsx:265-298,136-147`.

### 4c. Add position (manual-flows agent)
- **No trade-date field** — position always recorded as "now"; can't enter historical buys.
  `lib/api/portfolios.ts:656`
- **Ticker resolution is submit-time + slow** (ILIKE 2-4s cold), no typeahead. Misspelling →
  cryptic "not found" only after submit. `AddPositionDialog.tsx:212-238,146`
- "Avg Price (optional)" = cost basis in disguise; blank → cost_basis 0 → skewed P&L.

### 4d. Edit / Delete position (manual-flows agent)
- **NO Edit Position dialog exists.** Fixing a typo requires close (SELL) + re-add (BUY),
  polluting the transaction ledger. `SemanticHoldingsTable.tsx:646-679`
- **No partial close** — closing forces full quantity. `ClosePositionDialog.tsx:267-277`
- Delete only reachable via **right-click context menu** — undiscoverable for touch/trackpad
  users; no visible row action. Close price defaults to avg cost (not market).

### 4e. Brokerage connect (brokerage agent)
- **"Syncing shortly" copy is misleading** — real cycle is 4h (`config.py:114`) despite an
  immediate post-activation background sync; users churn when holdings don't appear in minutes.
  `callback/page.tsx:196`
- **No "we never store your password" reassurance** — the #1 trust barrier for linking a real
  brokerage; scope of "read-only" unexplained. `ConnectBrokerageModal.tsx:182`
- No sync-progress indicator (60s poll, invisible); generic error copy ("Unknown instruments").

## 5. Recommended action plan (prioritized)

### Tier 0 — Public-launch blockers (~2-3 days)
1. **Dual-mode page (Simple default / Advanced opt-in)** — Simple = 4 KPI tiles, Holdings tab
   only, 6-column table, no exposure/HHI/analytics. ~60-70% cognitive-load reduction, zero loss
   for power users. Feature flag via localStorage/URL. *(→ `/prd`)*
2. **Brokerage trust + timing copy** — add "credentials stay with SnapTrade, never Worldview;
   read-only" to modal; replace "shortly" with explicit "minutes to a few hours; use Sync Now."
   *(~30 min, `/fix-bug`)*
3. **Add Position: trade-date picker + inline ticker typeahead** — use existing
   `resolve-tickers`/search endpoints; debounced dropdown. Removes the two biggest manual-entry
   frictions.

### Tier 1 — High value (next sprint)
4. **Edit Position dialog** (adjust qty/avg-cost without close+re-add).
5. **Partial close** (quantity input in ClosePositionDialog).
6. **Visible row delete affordance** (trash-on-hover) in addition to context menu.
7. **Column-visibility toggle** on holdings table (Core / Portfolio / Advanced groups).
8. **Guided onboarding tour** after first portfolio creation.

### Tier 2 — Polish
9. Default portfolio auto-create on provision (removes an empty-landing step). `provision.py`
10. Tooltips on jargon (HHI, β-adjusted, Realized P&L, Buying Power).
11. Sync-progress indicator; concrete brokerage error messages.
12. Rate-limiting on mutation endpoints before public traffic.

## 6. Contributing factors
- Product grew feature-first for a power-user/thesis-demo audience; no "casual default" mode.
- Finance jargon surfaced directly in UI instead of behind progressive disclosure.
- Two mature editing capabilities (edit, partial close) never built — close was the only lever.

## 7. Compounding / prevention
- Add review-checklist item: "new UI surfaces must define a casual-user default + progressive
  disclosure before public exposure."
- Note in `apps/worldview-web` context: HoldingsTab canonical path is
  `features/portfolio/components/HoldingsTab.tsx` (stale duplicate under `components/portfolio/`
  misled a subagent).

## 8. Open questions
- Is a public launch single-tenant-per-user (self-serve signup) fully wired end-to-end
  (Zitadel → provision → default portfolio)? Provision creates user+tenant but **not** a
  portfolio — confirm the signup path hands the user a usable landing state.
