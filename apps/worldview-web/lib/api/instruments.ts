/**
 * lib/api/instruments.ts — Instruments / Market Data domain.
 *
 * SCOPE: composite instrument bundle, OHLCV bars (single + batch), live quotes
 * (single + batch), and the full fundamentals surface (overview metrics,
 * timeseries, technicals, share statistics, insider transactions, earnings
 * history, splits/dividends, derived snapshot).
 *
 * WHY one file: every method here ultimately resolves through S3 (market-data)
 * or S6 (fundamentals enrichment) and shares the `instrumentId` argument shape.
 * Splitting by sub-domain (quotes vs OHLCV vs fundamentals) would multiply
 * imports without buying isolation — they're already tightly coupled at the
 * backend.
 */

import type {
  CompanyOverview,
  InstrumentPageBundle,
  OHLCVResponse,
  Quote,
  BatchQuoteResponse,
  Fundamentals,
  FundamentalsSnapshot,
  FundamentalsSectionResponse,
  FundamentalsTimeseriesResponse,
} from "@/types/api";
import { apiFetch, GatewayError } from "./_client";

export function createInstrumentsApi(t: string | undefined) {
  return {
    /**
     * getCompanyOverview — composite response: fundamentals + OHLCV + news
     * Used by Instrument Detail page for the initial page load
     */
    getCompanyOverview(instrumentId: string): Promise<CompanyOverview> {
      return apiFetch<CompanyOverview>(
        `/v1/companies/${encodeURIComponent(instrumentId)}/overview`,
        { token: t },
      );
    },

    /**
     * getInstrumentPageBundle — single-round-trip composite for /instruments/[id].
     *
     * PLAN-0059 I-5: collapses the overview-tab waterfall (overview + fundamentals
     * + technicals + insider + top-news) into one HTTP request. The S9 endpoint
     * fans out via asyncio.gather; failed sub-resources degrade to null in the
     * response so the FE can render partial UIs.
     *
     * Children of /instruments/[id] can keep their own per-feature useQuery calls
     * to populate tab-specific surfaces; this bundle covers the OVERVIEW tab's
     * initial paint without requiring those children to be migrated.
     */
    getInstrumentPageBundle(instrumentId: string): Promise<InstrumentPageBundle> {
      return apiFetch<InstrumentPageBundle>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/page-bundle`,
        { token: t },
      );
    },

    /**
     * getOHLCV — candlestick bars for lightweight-charts
     * timeframe: "5M" | "1H" | "1D" | "1W" | "1M" (frontend convention: uppercase)
     *
     * WHY transform: S3 market-data returns OHLCVListResponse with `items` (not `bars`),
     * `bar_date` (not `timestamp`), and string OHLCV values (not numbers). The frontend
     * OHLCVBar type expects `timestamp: string` and numeric open/high/low/close. Transform
     * here at the gateway boundary so components stay decoupled from S3's schema.
     *
     * WHY lowercase timeframe before sending: S3 accepts "1d"/"1h"/"5m"/"1w" (lowercase)
     * BUT "1M" (uppercase M) for monthly — S3's Timeframe.ONE_MONTH = "1M" is
     * case-sensitive. Simple toLowerCase() would produce "1m" which S3 rejects.
     * The chart sends "5M"/"1H"/"1D"/"1W"/"1M" (uppercase frontend convention).
     * Normalize here so S3 doesn't return 422.
     */
    async getOHLCV(
      instrumentId: string,
      params: { timeframe?: string; start?: string; end?: string } = {},
    ): Promise<OHLCVResponse> {
      // WHY special-case "1M": S3's Timeframe enum is case-sensitive.
      // All timeframes are lowercase EXCEPT ONE_MONTH which is "1M" (uppercase M).
      // Frontend sends "1M" (its own uppercase convention), which happens to match
      // S3's expected casing — so we preserve it. Everything else lowercases normally.
      const normalizeTimeframe = (tf: string): string =>
        tf === "1M" ? "1M" : tf.toLowerCase();

      const normalized = {
        ...params,
        ...(params.timeframe ? { timeframe: normalizeTimeframe(params.timeframe) } : {}),
      };
      const qs = new URLSearchParams(
        Object.entries(normalized).filter(([, v]) => v != null) as [string, string][],
      ).toString();

      // WHY raw type: apiFetch would cast to OHLCVResponse directly, bypassing transform
      const raw = await apiFetch<{
        items: Array<{
          bar_date: string;
          open: string;
          high: string;
          low: string;
          close: string;
          volume: number | null;
        }>;
        total: number;
        timeframe: string;
      }>(`/v1/ohlcv/${encodeURIComponent(instrumentId)}${qs ? `?${qs}` : ""}`, { token: t });

      return {
        instrument_id: instrumentId,
        ticker: "",
        // Keep the frontend's uppercase convention in the response
        timeframe: (params.timeframe ?? "1D").toUpperCase(),
        bars: (raw.items ?? []).map((item) => ({
          timestamp: item.bar_date,
          open: parseFloat(item.open),
          high: parseFloat(item.high),
          low: parseFloat(item.low),
          close: parseFloat(item.close),
          volume: item.volume ?? 0,
        })),
      };
    },

    /**
     * getQuote — live quote for a single instrument (5s Valkey cache on S9)
     */
    getQuote(instrumentId: string): Promise<Quote> {
      return apiFetch<Quote>(
        `/v1/quotes/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
    },

    /**
     * getBatchQuotes — prices for multiple instruments at once
     * Used by: Sidebar watchlist (30s refetch), Portfolio page, TopBar index tickers
     * Body: { instrument_ids: string[] } — field name matches BatchQuoteRequest Pydantic model
     */
    getBatchQuotes(ids: string[]): Promise<BatchQuoteResponse> {
      return apiFetch<BatchQuoteResponse>("/v1/quotes/batch", {
        method: "POST",
        body: { instrument_ids: ids },
        token: t,
      });
    },

    /**
     * getBatchOhlcvBars — fetch recent OHLCV bars for many instruments at once.
     *
     * WHY THIS EXISTS (PLAN-0051 T-B-2-09): the screener renders an inline
     * 30-day sparkline per row. N parallel /v1/ohlcv calls would mean 50+
     * round-trips for a default page — way too slow. This batch endpoint is
     * one round-trip for up to ~100 instruments (PLAN-0049 T-A-1-05).
     *
     * WHY a 404 fallback to per-instrument calls: if a deployment drifts and
     * the batch endpoint is missing, the screener still works at degraded
     * performance instead of breaking entirely.
     *
     * RESPONSE SHAPE: { results: [{ instrument_id, bars: OHLCVBar[] }, ...] }
     */
    async getBatchOhlcvBars(params: {
      instrument_ids: string[];
      timeframe?: string;
      limit?: number;
    }): Promise<{ results: Array<{ instrument_id: string; bars: OHLCVResponse["bars"] }> }> {
      // WHY normalize lowercase: S3 enum values are lowercase ("1d"/"1h"). The
      // single-instrument getOHLCV does the same normalization.
      const tf = (params.timeframe ?? "1d").toLowerCase();
      const body = {
        requests: params.instrument_ids.map((id) => ({
          instrument_id: id,
          timeframe: tf,
          limit: params.limit ?? 30,
        })),
      };

      try {
        const raw = await apiFetch<{
          results: Array<{
            instrument_id: string;
            items: Array<{
              bar_date: string;
              open: string;
              high: string;
              low: string;
              close: string;
              volume: number | null;
            }>;
          }>;
        }>("/v1/ohlcv/batch", {
          method: "POST",
          body,
          token: t,
        });
        return {
          results: (raw.results ?? []).map((r) => ({
            instrument_id: r.instrument_id,
            bars: (r.items ?? []).map((item) => ({
              timestamp: item.bar_date,
              open: parseFloat(item.open),
              high: parseFloat(item.high),
              low: parseFloat(item.low),
              close: parseFloat(item.close),
              volume: item.volume ?? 0,
            })),
          })),
        };
      } catch (err) {
        // WHY only 404: missing endpoint → degrade. Other errors propagate.
        if (err instanceof GatewayError && err.status === 404) {
          // WHY inline (not this.getOHLCV): destructured calls would lose `this`.
          const limit = params.limit ?? 30;
          const tfNorm = params.timeframe ?? "1D";
          const tfPath = tfNorm === "1M" ? "1M" : tfNorm.toLowerCase();
          const results = await Promise.all(
            params.instrument_ids.map(async (id) => {
              try {
                const raw = await apiFetch<{
                  items: Array<{
                    bar_date: string;
                    open: string;
                    high: string;
                    low: string;
                    close: string;
                    volume: number | null;
                  }>;
                }>(`/v1/ohlcv/${encodeURIComponent(id)}?timeframe=${tfPath}`, { token: t });
                const bars = (raw.items ?? []).slice(-limit).map((item) => ({
                  timestamp: item.bar_date,
                  open: parseFloat(item.open),
                  high: parseFloat(item.high),
                  low: parseFloat(item.low),
                  close: parseFloat(item.close),
                  volume: item.volume ?? 0,
                }));
                return { instrument_id: id, bars };
              } catch {
                return { instrument_id: id, bars: [] };
              }
            }),
          );
          return { results };
        }
        throw err;
      }
    },

    /**
     * getFundamentals — all fundamental metrics for an instrument.
     * Used by Instrument Detail → Fundamentals tab.
     *
     * WHY transformer: S3 returns {security_id, records: [{section, data}]} but
     * FundamentalsTab expects a flat Fundamentals object (market_cap, pe_ratio…).
     * The transformer extracts the singleton "highlights", "valuation_ratios", and
     * "technicals_snapshot" sections and assembles the flat shape. Fields that
     * require time-series joins (debt_to_equity, current_ratio) return null until
     * the backfill populates the snapshot table. (BP-369)
     */
    async getFundamentals(instrumentId: string): Promise<Fundamentals> {
      const raw = await apiFetch<{ security_id: string; records: Array<Record<string, unknown>> }>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
      const num = (v: unknown): number | null => {
        if (v == null || v === "") return null;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      };
      // Extract singleton sections (one record each)
      let hi: Record<string, unknown> = {};
      let vr: Record<string, unknown> = {};
      let ts: Record<string, unknown> = {};
      let updatedAt: string | null = null;
      for (const rec of raw.records ?? []) {
        const data = (rec["data"] ?? {}) as Record<string, unknown>;
        const section = rec["section"] as string | undefined;
        if (section === "highlights" && !Object.keys(hi).length) { hi = data; updatedAt = rec["ingested_at"] as string ?? null; }
        else if (section === "valuation_ratios" && !Object.keys(vr).length) vr = data;
        else if (section === "technicals_snapshot" && !Object.keys(ts).length) ts = data;
      }
      const grossMarginTTM = (num(hi["GrossProfitTTM"]) != null && num(hi["RevenueTTM"]) != null && num(hi["RevenueTTM"])! > 0)
        ? num(hi["GrossProfitTTM"])! / num(hi["RevenueTTM"])!
        : null;
      const eps = num(hi["EarningsShare"]);
      const div = num(hi["DividendShare"]);
      const payoutRatio = eps != null && eps > 0 && div != null ? div / eps : null;
      return {
        instrument_id: raw.security_id ?? instrumentId,
        ticker: "",  // populated by overview; FundamentalsTab doesn't render this
        name: "",    // populated by overview
        market_cap:           num(hi["MarketCapitalization"]),
        pe_ratio:             num(hi["PERatio"]),
        forward_pe:           num(vr["ForwardPE"]),
        price_to_book:        num(vr["PriceBookMRQ"]),
        price_to_sales:       num(vr["PriceSalesTTM"]),
        ev_to_ebitda:         num(vr["EnterpriseValueEbitda"]),
        gross_margin:         grossMarginTTM,
        operating_margin:     num(hi["OperatingMarginTTM"]),
        net_margin:           num(hi["ProfitMargin"]),
        roe:                  num(hi["ReturnOnEquityTTM"]),
        roa:                  num(hi["ReturnOnAssetsTTM"]),
        revenue_growth_yoy:   num(hi["QuarterlyRevenueGrowthYOY"]),
        earnings_growth_yoy:  num(hi["QuarterlyEarningsGrowthYOY"]),
        dividend_yield:       num(hi["DividendYield"]),
        payout_ratio:         payoutRatio,
        debt_to_equity:       null, // requires balance-sheet join; populated by snapshot
        current_ratio:        null, // requires balance-sheet join; populated by snapshot
        quick_ratio:          null, // requires balance-sheet join; populated by snapshot
        week_52_high:         num(ts["52WeekHigh"]),
        week_52_low:          num(ts["52WeekLow"]),
        daily_return:         null, // derived from OHLCV; available in overview.fundamentals
        updated_at:           updatedAt,
      };
    },

    /**
     * getFundamentalsTimeseries — single-metric time series for sparklines
     *
     * WHY no auth: S9 route /v1/fundamentals/timeseries is a public endpoint —
     * it issues a system JWT internally (not a user JWT). No Bearer token sent.
     *
     * WHY instrument_id + metric as query params (not path): the S3 endpoint
     * is designed as a filter over the fundamentals_metrics table, not a
     * resource path. Multiple instruments or metrics could be fetched with the
     * same route shape.
     *
     * Used by: FundamentalSparkline (Overview sidebar panels + Fundamentals tab inline charts)
     * Default limit of 20 gives enough points for a sparkline without over-fetching.
     */
    getFundamentalsTimeseries(
      instrumentId: string,
      metric: string,
      params?: {
        start_date?: string;
        end_date?: string;
        period_type?: string;
        limit?: number;
        // order: 'asc' returns the oldest N rows, 'desc' returns the most recent N
        // (DESC is what UI charts almost always want — see audit 2026-04-28 / BP-261).
        // Returned data is always chronologically ascending regardless of order.
        order?: "asc" | "desc";
      },
    ): Promise<FundamentalsTimeseriesResponse> {
      // WHY URLSearchParams with conditional spread: filters out undefined values so
      // optional params don't appear as "undefined" strings in the query string.
      const qs = new URLSearchParams({
        instrument_id: instrumentId,
        metric,
        ...(params?.start_date ? { start_date: params.start_date } : {}),
        ...(params?.end_date ? { end_date: params.end_date } : {}),
        ...(params?.period_type ? { period_type: params.period_type } : {}),
        ...(params?.limit != null ? { limit: String(params.limit) } : {}),
        ...(params?.order ? { order: params.order } : {}),
      });
      return apiFetch<FundamentalsTimeseriesResponse>(
        `/v1/fundamentals/timeseries?${qs.toString()}`,
        {}, // no auth — public endpoint uses system JWT internally
      );
    },

    /**
     * getTechnicals — technical indicators snapshot from S3
     *
     * WHY /technicals (not /technicals-snapshot): S9 exposes the shortened path.
     * S3 internally stores this as "technicals_snapshot" section.
     * Used by: TechnicalSnapshot component (Wave D-3), OverviewSidebarMetrics (Wave C-1)
     */
    getTechnicals(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/technicals`,
        { token: t },
      );
    },

    /**
     * getShareStatistics — share count and ownership percentages from S3
     *
     * Data fields: shares_outstanding, shares_float, percent_insiders, percent_institutions.
     * Cast records[0].data to ShareStatisticsData for typed access.
     * Used by: OwnershipSnapshotPanel (Wave D-2)
     */
    getShareStatistics(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/share-statistics`,
        { token: t },
      );
    },

    /**
     * getInsiderTransactions — recent insider buys/sells from S3
     *
     * Returns records with section="insider_transactions_snapshot". Each record's
     * data array contains individual transactions (date, owner_name, type, shares, value).
     * Used by: InsiderTransactionsTable (Wave D-3)
     */
    getInsiderTransactions(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/insider-transactions`,
        { token: t },
      );
    },

    /**
     * getEarningsHistory — historical EPS actuals from S3 (ANNUAL records)
     *
     * WHY /earnings-annual-trend (not /earnings-trend): The S9 /earnings-trend
     * endpoint maps to EODHD's EarningsTrend section which contains FORWARD-LOOKING
     * analyst consensus estimates (period "+1q", "+1y") — not historical actuals.
     * The /earnings-annual-trend endpoint contains historical per-fiscal-year EPS
     * actuals stored as `{date: "YYYY-MM-DD", epsActual: N}` records. This is what
     * analysts need to see the multi-year EPS growth trajectory (the primary input
     * for P/E target valuation). Live data confirms: 33 historical annual EPS records
     * for AAPL from /earnings-annual-trend vs 0 records from the timeseries endpoint.
     * Used by: EarningsHistoryChart (Wave D-3)
     */
    getEarningsHistory(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/earnings-annual-trend`,
        { token: t },
      );
    },

    /**
     * getSplitsDividends — stock split and dividend history from S3
     *
     * Returns records with section="splits_dividends". Contains forward and
     * historical split ratios, dividend dates, and ex-dividend dates.
     * Used by: FundamentalsTab (Wave D-1 splits section), future D-3 enrichment
     */
    getSplitsDividends(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/splits-dividends`,
        { token: t },
      );
    },

    /**
     * getFundamentalsSnapshot — pre-computed derived metrics snapshot from S3
     *
     * WHY SEPARATE FROM getFundamentals: The main getFundamentals call returns
     * fields assembled from EODHD highlights/technicals JSONB sections (market cap,
     * P/E, margins). This snapshot contains 10 additional derived metrics that
     * require multi-section joins (FCF = operating_cf - |capex|, interest coverage
     * = ebit / interest_expense, net debt/EBITDA, beta, avg_volume_30d, eps_ttm).
     * Pre-computing these at backfill time keeps the API response fast and avoids
     * complex JSONB arithmetic in hot query paths.
     *
     * WHY NO 404: S3 always returns 200 for this endpoint — all fields are null
     * when the instrument hasn't been through the backfill yet (e.g. newly-listed
     * stocks, ETFs with no cash flow statements). The frontend shows "—" for nulls.
     *
     * Used by: InstrumentKeyMetrics (EPS TTM, Beta, Avg Volume rows),
     *          FundamentalsTab Cash Flow section + Debt & Credit section.
     * PLAN-0050 Wave D (T-D-4-04).
     */
    getFundamentalsSnapshot(instrumentId: string): Promise<FundamentalsSnapshot> {
      return apiFetch<FundamentalsSnapshot>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/snapshot`,
        { token: t },
      );
    },
  };
}
