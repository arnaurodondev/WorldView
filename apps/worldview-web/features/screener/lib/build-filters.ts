/**
 * build-filters.ts — buildScreenerFilters utility
 *
 * WHY THIS EXISTS: Extracted from app/(app)/screener/page.tsx so the function
 * can be imported by unit tests without re-exporting from a Next.js page
 * (which causes TS2344 — page files may not export non-Next.js symbols).
 *
 * WHO USES IT: screener/page.tsx (at query build time), screener-build-filters.test.ts
 * DATA SOURCE: FilterState UI state → ScreenerRequest.filters[] for POST /v1/fundamentals/screen
 */

import type { ScreenerFilter } from "@/types/api";
import type { FilterState } from "./filter-state";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pushIfRange(
  out: ScreenerFilter[],
  metric: string,
  min: number | undefined,
  max: number | undefined,
): void {
  if (min === undefined && max === undefined) return;
  out.push({ metric, min_value: min, max_value: max });
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * buildScreenerFilters — converts UI FilterState to ScreenerRequest.filters[].
 *
 * Maps each fundamental UI filter to the canonical backend metric name from
 * docs/services/market-data.md (PLAN-0051 T-B-2-01).
 *
 * Part 4 fix: daily_return and pe_ratio are always appended so the backend
 * computes those columns on every row even when the user set no range filter.
 */
export function buildScreenerFilters(f: FilterState): ScreenerFilter[] {
  const filters: ScreenerFilter[] = [];

  // Cap tier → market_capitalization range.
  // WHY also check marketCapMin/Max: FilterChipStrip may add exact USD thresholds
  // that go beyond the tier buckets (e.g. "$50B" = 50_000_000_000). When both are
  // present we take the more-restrictive of tier vs explicit range by using Math.max
  // for the lower bound and Math.min for the upper bound.
  let capMin: number | undefined = f.marketCapMin;
  let capMax: number | undefined = f.marketCapMax;
  if (f.capTier === "LARGE") capMin = Math.max(capMin ?? 0, 10_000_000_000) || undefined;
  else if (f.capTier === "MID") {
    capMin = Math.max(capMin ?? 0, 2_000_000_000) || undefined;
    capMax = capMax != null ? Math.min(capMax, 10_000_000_000) : 10_000_000_000;
  } else if (f.capTier === "SMALL") {
    capMax = capMax != null ? Math.min(capMax, 2_000_000_000) : 2_000_000_000;
  }
  pushIfRange(filters, "market_capitalization", capMin, capMax);

  // ── Valuation (SERVER_SIDE) ────────────────────────────────────────────────
  pushIfRange(filters, "pe_ratio", f.peMin, f.peMax);
  pushIfRange(filters, "pb_ratio", f.pbMin, f.pbMax);
  pushIfRange(filters, "price_sales_ttm", f.psMin, f.psMax);
  pushIfRange(filters, "dividend_yield", f.divYieldMin, f.divYieldMax);
  // forward_pe — echoed back by the backend in the ScreenerResult so the column
  // can render without an extra round-trip (design §3.2 "echo back" pattern).
  pushIfRange(filters, "forward_pe", f.forwardPeMin, f.forwardPeMax);

  // ── Profitability (SERVER_SIDE) ────────────────────────────────────────────
  pushIfRange(filters, "roe_ttm", f.roeMin, f.roeMax);
  pushIfRange(filters, "profit_margin", f.netMarginMin, f.netMarginMax);
  pushIfRange(filters, "operating_margin_ttm", f.opMarginMin, f.opMarginMax);

  // ── Growth (SERVER_SIDE) ───────────────────────────────────────────────────
  pushIfRange(filters, "quarterly_revenue_growth_yoy", f.revGrowthMin, f.revGrowthMax);
  pushIfRange(filters, "quarterly_earnings_growth_yoy", f.earningsGrowthMin, f.earningsGrowthMax);

  // ── Performance / Returns (SERVER_SIDE — IB-L3) ────────────────────────────
  // WHY field names must match backend BYTE-FOR-BYTE: mismatches silently drop
  // filters (backend ignores unknown metric names). Names from:
  // services/market-data/src/market_data/api/schemas/fundamental_metrics.py
  pushIfRange(filters, "dist_from_52w_high_pct", f.dist52wHighPctMin, f.dist52wHighPctMax);
  pushIfRange(filters, "dist_from_52w_low_pct", f.dist52wLowPctMin, f.dist52wLowPctMax);
  pushIfRange(filters, "return_1m", f.return1mMin, f.return1mMax);
  pushIfRange(filters, "return_3m", f.return3mMin, f.return3mMax);
  pushIfRange(filters, "return_6m", f.return6mMin, f.return6mMax);
  pushIfRange(filters, "return_ytd", f.returnYtdMin, f.returnYtdMax);
  pushIfRange(filters, "return_1y", f.return1yMin, f.return1yMax);
  pushIfRange(filters, "return_3y", f.return3yMin, f.return3yMax);

  // ── Analyst / Insider / Ownership (SERVER_SIDE — IB-L4) ──────────────────
  // BUGFIX 2026-06-15 (screener filter audit): these five fields are NOT rows
  // in the ``fundamental_metrics`` table — they are COLUMNS on
  // ``instrument_fundamentals_snapshot``. Sending them as
  // ``{metric: "short_percent", min_value: ...}`` made the backend build a
  // ``WHERE fundamental_metrics.metric = 'short_percent'`` subquery; because no
  // such metric row exists, the INNER JOIN matched zero instruments and the
  // ENTIRE Ownership section silently returned 0 results (live-verified:
  // ``{metric:"short_percent",min_value:0.05}`` → total 0, vs the named-field
  // form below → total 192). The backend's ``ScreenFilterRequest`` exposes each
  // snapshot column as a per-filter NAMED sibling of min_value/max_value
  // (``short_percent_min`` / ``short_percent_max`` etc.) — see
  // services/market-data/.../api/schemas/fundamental_metrics.py:64-71,109-110
  // and the ``numeric_snap_filters`` handling in fundamental_metrics_query.py.
  // This is the SAME trap already documented for the intelligence rollup +
  // avg_volume_30d blocks below; the merge helper applies the identical pattern.
  //
  // WHY merged onto an existing filter (not pushed as a new entry): the named
  // fields are siblings on a ScreenFilterRequest object, and the backend
  // collapses each ``*_min``/``*_max`` across all filter entries with the first
  // non-None value. Attaching them to the first filter (or a synthetic
  // market_capitalization carrier when none exists) keeps them on the request
  // without needing a numeric metric range of their own — exactly how the
  // intelligence + volume blocks attach below.
  //
  // WHY a local interface (not new fields on the shared types/api.ts
  // ScreenerFilter): types/api.ts is shared across surfaces and this sprint runs
  // several agents concurrently; an additive local intersection type keeps the
  // change inside the screener surface. The fields serialise identically —
  // JSON.stringify ignores the nominal type (same precedent as
  // SnapshotVolumeFields below).
  interface SnapshotOwnershipFields {
    analyst_target_price_min?: number;
    analyst_target_price_max?: number;
    analyst_consensus_rating_min?: number;
    analyst_consensus_rating_max?: number;
    insider_net_buy_90d_min?: number;
    insider_net_buy_90d_max?: number;
    institutional_ownership_pct_min?: number;
    institutional_ownership_pct_max?: number;
    short_percent_min?: number;
    short_percent_max?: number;
  }
  const own: SnapshotOwnershipFields = {};
  if (f.analystTargetPriceMin !== undefined) own.analyst_target_price_min = f.analystTargetPriceMin;
  if (f.analystTargetPriceMax !== undefined) own.analyst_target_price_max = f.analystTargetPriceMax;
  if (f.analystConsensusMin !== undefined) own.analyst_consensus_rating_min = f.analystConsensusMin;
  if (f.analystConsensusMax !== undefined) own.analyst_consensus_rating_max = f.analystConsensusMax;
  if (f.insiderNetBuy90dMin !== undefined) own.insider_net_buy_90d_min = f.insiderNetBuy90dMin;
  if (f.insiderNetBuy90dMax !== undefined) own.insider_net_buy_90d_max = f.insiderNetBuy90dMax;
  if (f.instOwnPctMin !== undefined) own.institutional_ownership_pct_min = f.instOwnPctMin;
  if (f.instOwnPctMax !== undefined) own.institutional_ownership_pct_max = f.instOwnPctMax;
  if (f.shortPctMin !== undefined) own.short_percent_min = f.shortPctMin;
  if (f.shortPctMax !== undefined) own.short_percent_max = f.shortPctMax;
  if (Object.keys(own).length > 0) {
    if (filters.length > 0) {
      filters[0] = { ...filters[0], ...own };
    } else {
      // Synthetic carrier: ScreenFilterRequest requires a ``metric`` (regex
      // validated), and market_capitalization with no min/max is the canonical
      // no-op carrier — the backend LEFT JOINs the snapshot directly, so no
      // numeric bound is applied on the metric itself.
      filters.push({ metric: "market_capitalization", ...own });
    }
  }

  // ── Intelligence rollup (SERVER_SIDE — IB-L5) ────────────────────────────
  // WHY merged into ONE filter object (not pushed as separate filters[]
  // entries): the backend ScreenFilterRequest exposes the 6 intelligence fields
  // as PER-FILTER named siblings of min_value/max_value. Pushing them as
  // `{metric: "news_count_7d", min_value: 1}` silently returns 0 rows because
  // `news_count_7d` is not a known computed metric — the INNER JOIN path drops
  // unmatched rows. Same merge pattern used for `sector` below.
  // Reference: services/market-data/.../api/schemas/fundamental_metrics.py:115-124.
  const intel: Partial<ScreenerFilter> = {};
  if (f.newsCount7dMin !== undefined) intel.news_count_7d_min = f.newsCount7dMin;
  if (f.newsCount7dMax !== undefined) intel.news_count_7d_max = f.newsCount7dMax;
  if (f.llmRelevance7dMin !== undefined) intel.llm_relevance_7d_max_min = f.llmRelevance7dMin;
  if (f.llmRelevance7dMax !== undefined) intel.llm_relevance_7d_max_max = f.llmRelevance7dMax;
  if (f.displayRelevance7dMin !== undefined) intel.display_relevance_7d_weighted_min = f.displayRelevance7dMin;
  if (f.displayRelevance7dMax !== undefined) intel.display_relevance_7d_weighted_max = f.displayRelevance7dMax;
  if (f.contradictionsMin !== undefined) intel.recent_contradiction_count_min = f.contradictionsMin;
  if (f.contradictionsMax !== undefined) intel.recent_contradiction_count_max = f.contradictionsMax;
  if (f.hasAiBrief === true) intel.has_ai_brief = true;
  if (f.hasActiveAlert === true) intel.has_active_alert = true;
  if (Object.keys(intel).length > 0) {
    if (filters.length > 0) {
      filters[0] = { ...filters[0], ...intel };
    } else {
      // WHY synthetic filter: ScreenFilterRequest requires `metric` (regex-validated).
      // market_capitalization is the canonical "always-present" metric with no
      // numeric bounds — the backend's INNER JOIN handles the snapshot columns
      // directly without needing a min/max on the metric itself.
      filters.push({ metric: "market_capitalization", ...intel });
    }
  }

  // ── 30d average volume (SERVER_SIDE — Round 2) ───────────────────────────
  // WHY merged as PER-FILTER NAMED FIELDS (not a `{metric: "avg_volume_30d"}`
  // entry): avg_volume_30d is NOT a fundamental_metrics row — it is a COLUMN
  // on instrument_fundamentals_snapshot, exposed by the backend as the
  // `avg_volume_30d_min` / `avg_volume_30d_max` siblings of min_value/max_value
  // on ScreenFilterRequest (services/market-data/.../api/schemas/
  // fundamental_metrics.py:48-49, Wave L-2). Sending it as a metric filter
  // would silently return 0 rows via the INNER JOIN path — exactly the trap
  // documented for the intelligence rollup fields above.
  //
  // WHY a local interface (not fields on types/api.ts ScreenerFilter): Round 2
  // runs six surface agents concurrently and types/api.ts is shared; an
  // additive intersection type here keeps the change inside the screener
  // surface. The fields serialise identically — JSON.stringify doesn't care
  // about the nominal type.
  interface SnapshotVolumeFields {
    avg_volume_30d_min?: number;
    avg_volume_30d_max?: number;
  }
  const snap: SnapshotVolumeFields = {};
  if (f.avgVolume30dMin !== undefined) snap.avg_volume_30d_min = f.avgVolume30dMin;
  if (f.avgVolume30dMax !== undefined) snap.avg_volume_30d_max = f.avgVolume30dMax;
  if (Object.keys(snap).length > 0) {
    if (filters.length > 0) {
      filters[0] = { ...filters[0], ...snap };
    } else {
      // Same synthetic-filter pattern as the intelligence block: the request
      // schema requires a `metric`, and market_capitalization with no bounds
      // is the canonical no-op carrier (backend LEFT JOINs handle the
      // snapshot column directly).
      filters.push({ metric: "market_capitalization", ...snap });
    }
  }

  // Sector filter: when sector is selected but no other metric filters are active
  // we still need to communicate the sector restriction. S3's sector field lives on
  // ScreenFilterRequest, so we attach it to the first filter or add a synthetic one.
  if (f.sector && f.sector !== "ALL") {
    if (filters.length > 0) {
      filters[0] = { ...filters[0], sector: f.sector };
    } else {
      // WHY synthetic filter with no numeric range: S3 accepts filters[] with both
      // min_value and max_value omitted — it just uses the filter for sector restriction
      // without applying any numeric threshold. Sending {metric, sector} alone tells S3
      // to restrict the universe to that sector and return key metrics via LEFT JOIN.
      filters.push({ metric: "market_capitalization", sector: f.sector });
    }
  }

  // WHY no fallback filter when filters is empty: S3 v2 accepts filters:[] and
  // responds with the optimised "no filter" path — LEFT JOINs across key metrics
  // (market_cap, pe_ratio, beta, daily_return, revenue_usd) for ALL instruments.
  // Previously we sent [{market_cap, min: 0}] here, which triggered S3's INNER JOIN
  // path and only populated the market_cap column, leaving all others "—".

  return filters;
}
