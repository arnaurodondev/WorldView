/**
 * lib/api/dashboard.ts — Dashboard composed endpoints (heatmap, top movers,
 * economic calendar, AI briefings, AI signals).
 */

import type {
  DashboardSnapshotResponse,
  EarningsCalendarResponse,
  EconomicCalendarResponse,
  MarketHeatmapResponse,
  TopMoversResponse,
  AiSignalsResponse,
  BriefingResponse,
} from "@/types/api";
import { apiFetch } from "./_client";

/**
 * DashboardBundleResponse — F-2 single composite for the dashboard page.
 *
 * WHY a NEW shape distinct from DashboardSnapshotResponse:
 * The older snapshot prefetcher (PLAN-0070 C-2) stored under qk.dashboard.snapshot()
 * but the per-widget hooks use DIFFERENT keys (qk.dashboard.morningBrief(),
 * ["alerts-pending"], ["sector-heatmap-widget", "1D"], …). The snapshot
 * therefore did not eliminate widget wave-serialization on cold start.
 *
 * The bundle below is shape-aligned with the per-widget cache keys so the
 * page hydrates them via queryClient.setQueryData and the widgets render
 * without firing their own initial fetches.
 *
 * All legs are nullable — failed legs degrade to null at the gateway and the
 * page renders partial UIs (skeletons or "—") for them.
 */
export interface DashboardBundleResponse {
  brief: unknown | null;
  portfolios: unknown | null;
  top_gainers: unknown | null;
  top_losers: unknown | null;
  sector_heatmap: unknown | null;
  recent_alerts: unknown | null;
  workspace: unknown | null;
  _meta?: { partial: boolean; legs_failed: number };
}

/**
 * RawTopMoversResponse — the wire shape S9 GET /v1/market/top-movers actually
 * returns (S3 period-movers envelope), BEFORE the frontend transform.
 *
 * WHY exported: the DashboardBundleHydrator receives the SAME raw envelope in
 * its `top_gainers` / `top_losers` legs and must apply the SAME transform as
 * getTopMovers() before seeding the widget caches — otherwise widgets that
 * expect `{movers: Mover[]}` would read `{results: [...]}` from the hydrated
 * cache and render empty (silent shape-mismatch, see BP audit feedback on
 * "prompt input vs lookup mismatch" — same class of bug).
 */
export interface RawTopMoversResponse {
  results?: Array<{
    instrument_id?: string;
    // WHY entity_id optional here: S3 screener results do not always include entity_id.
    // When present (e.g. after S7 entity-linking enrichment) we preserve it so downstream
    // navigation can use the stable ADR-F-12 entity_id rather than instrument_id.
    entity_id?: string;
    ticker?: string; // S3 ScreenInstrumentResponse field name
    symbol?: string; // legacy / alternate field name kept for forward compat
    name?: string;
    exchange?: string;
    // S3 /market/period-movers returns the latest price as a TOP-LEVEL
    // `last_price` (no `metrics` nesting) — e.g. {ticker:"ABT", last_price:99.1,
    // period_return_pct:11.01}. Kept explicit so the transform can read it
    // instead of silently defaulting price to 0 (the "—" price-cell bug).
    last_price?: number | null;
    metrics?: {
      daily_return?: number;
      market_cap?: number;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  }>;
  // S9 may also return the shaped response if it's been fixed server-side
  movers?: Array<{
    instrument_id: string;
    entity_id?: string | null; // present when S9 enriches top-movers with knowledge graph IDs
    ticker: string;
    name: string;
    price: number;
    change_pct: number;
    volume: number | null;
  }>;
  type?: string;
  total?: number;
}

/**
 * transformTopMoversResponse — pure transform from the raw S9/S3 top-movers
 * envelope into the `{movers, type}` shape the dashboard widgets consume.
 *
 * WHY a standalone exported function (extracted from getTopMovers, Round 1
 * foundation fix): TWO call sites need the identical transform —
 *   1. getTopMovers() below (per-widget refetch path), and
 *   2. DashboardBundleHydrator (cold-start cache-seeding path).
 * Previously the hydrator seeded the RAW envelope under a query key whose
 * consumers expect the TRANSFORMED shape — the per-widget queryFn and the
 * hydrated cache disagreed about the data shape. Extracting the transform
 * makes "one wire shape → one display shape" a single source of truth.
 *
 * Field-mapping notes (root causes of the $0.00 / 0.00% bugs this fixes):
 *   - S3 period-movers rows are `{instrument_id, ticker, name, period_return_pct}`
 *     — `period_return_pct` is TOP-LEVEL and already in percent units.
 *   - Legacy screener rows nest `metrics.daily_return` as a DECIMAL fraction
 *     (0.031 = 3.1%) — multiply by 100 only on that fallback path.
 *   - Neither shape carries a price — widgets patch price from the batched
 *     company-overview lookup (see TopMovers.tsx priceByInstrumentId).
 */
export function transformTopMoversResponse(
  raw: RawTopMoversResponse,
  moverType: "gainers" | "losers",
): TopMoversResponse {
  // WHY check both shapes: S9 may be updated in the future to return the correct shape.
  // If `movers` is already present, use it directly. Otherwise, transform from screener results.
  if (raw.movers) {
    return {
      movers: raw.movers,
      type: (raw.type as "gainers" | "losers") ?? moverType,
      // Already-shaped path is not directionally filtered, so raw == displayed.
      rawCount: raw.movers.length,
    };
  }

  // Transform screener results into Mover[] format.
  // WHY ticker ?? symbol fallback: S3's ScreenInstrumentResponse uses `ticker`.
  // Some older or alternate responses may use `symbol`. Try both so the widget
  // always shows a symbol string instead of an empty cell.
  // F-304 fix (PLAN-0048 QA iter-1): pull the latest close/price from
  // any of the metric fields S3 may surface so we never display $0.00
  // for a real ticker — and apply strict directional filtering below.
  const movers = (raw.results ?? []).map((r) => {
    const metrics = (r.metrics ?? {}) as Record<string, unknown>;
    // S3's screener returns price under various keys depending on the
    // configured metric set: `close`, `last_price`, or sometimes a flat
    // `price`. Probe all three before falling back to 0 — this rescues
    // the $0.00 rows the audit captured in /tmp/qa-iter1/d1920-top-movers.
    const priceFromMetrics =
      typeof metrics.close === "number"
        ? metrics.close
        : typeof metrics.last_price === "number"
          ? metrics.last_price
          : typeof metrics.price === "number"
            ? metrics.price
            : // S3 /market/period-movers exposes the latest price at the TOP level
              // as `last_price` — probe it before `price`/0 so populated movers
              // rows show their real price without waiting on the secondary
              // company-overview batch (which, when slow/failing, left "—").
              typeof r.last_price === "number"
              ? r.last_price
              : typeof (r as Record<string, unknown>).price === "number"
                ? ((r as Record<string, unknown>).price as number)
                : 0;
    return {
      instrument_id: r.instrument_id ?? "",
      // WHY propagate entity_id when present: top-mover rows need it for correct
      // instrument detail navigation. ADR-F-12 mandates entity_id in URLs.
      // Falls back to undefined so the UI can degrade to instrument_id-based routing.
      entity_id: r.entity_id ?? undefined,
      ticker:
        r.ticker ??
        r.symbol ??
        r.name?.split(" ")[0] ??
        r.instrument_id?.slice(0, 6) ??
        "",
      name: r.name ?? r.ticker ?? r.symbol ?? "", // name for tooltip/detail
      price: priceFromMetrics,
      // WHY * 100: S3 daily_return is a decimal fraction (0.031 = 3.1%).
      // The Mover.change_pct field is treated as a percentage by MoverRow
      // (mover.change_pct.toFixed(2) → "3.11"). Multiply to convert.
      // WHY period_return_pct first: the /top-movers endpoint returns
      // period_return_pct at the top level (not nested under metrics).
      // Fall back to metrics.daily_return for any legacy screener responses.
      change_pct:
        typeof (r as Record<string, unknown>).period_return_pct === "number"
          ? ((r as Record<string, unknown>).period_return_pct as number)
          : (r.metrics?.daily_return ?? 0) * 100,
      volume: null as number | null,
    };
  });

  // F-304 fix (PLAN-0048 QA iter-1): the audit observed the gainers
  // list contained negative-% rows (e.g. GOOGL -0.54%) and the same
  // ticker appeared in BOTH the gainers and losers panes. The screener
  // sometimes returns rows whose daily_return is opposite to the
  // requested side when the underlying sort is unstable — strict
  // directional filtering on the client guarantees gainers > 0 and
  // losers < 0 regardless of upstream behaviour.
  const filtered = movers.filter((m) =>
    moverType === "gainers" ? m.change_pct > 0 : m.change_pct < 0,
  );

  // rawCount is the PRE-filter page size — the infinite-scroll pager advances
  // its S3 `offset` by this (not by the filtered length) so it never re-requests
  // rows it has already seen.
  return { movers: filtered, type: moverType, rawCount: (raw.results ?? []).length };
}

export function createDashboardApi(t: string | undefined) {
  return {
    /**
     * getMarketHeatmap — GICS sector performance for dashboard
     *
     * WHY period param: PLAN-0043 B-4 wires the period selector buttons (1D/1W/1M)
     * in the dashboard SectorHeatmapWidget to the S9 endpoint. Passing period here
     * ensures TanStack Query re-fetches when the user switches periods.
     * - 1D: S9 makes 11 parallel screener calls (one per GICS sector)
     * - 1W/1M: S9 delegates to S3 OHLCV aggregate endpoint (more accurate)
     */
    getMarketHeatmap(period: "1D" | "1W" | "1M" = "1D"): Promise<MarketHeatmapResponse> {
      return apiFetch<MarketHeatmapResponse>(`/v1/market/heatmap?period=${period}`, {
        token: t,
      });
    },

    /**
     * getTopMovers — top gainers or losers by daily return
     *
     * WHY transform: S9's get_top_movers() composed endpoint returns the raw S3 screener
     * response `{results: [{instrument_id, symbol, exchange, metrics: {daily_return, ...}}], total, ...}`
     * — NOT the `{movers: Mover[], type}` shape the frontend expects. Each screener result
     * uses `symbol` (not `ticker`), nests daily_return inside a `metrics` object, and has
     * no `price` or `name` field. We extract what we can and default the rest.
     */
    async getTopMovers(
      moverType: "gainers" | "losers" = "gainers",
      limit = 10,
      // WHY period param: PLAN-0043 B-4 wires the period selector buttons (1D/1W/1M)
      // in PreMarketMoversWidget to the S9 endpoint. The period is passed through to
      // S9 which routes 1D → screener and 1W/1M → S3 OHLCV period-movers endpoint.
      // Default 1D keeps backward compatibility.
      period: "1D" | "1W" | "1M" = "1D",
      // WHY offset param: backend S3 /market/period-movers now accepts an `offset`
      // for paginating through the universe-wide leaderboard (Dashboard Regression
      // #3). Default 0 keeps the dashboard widget behaviour unchanged; a future
      // standalone /markets/movers page can call with offset>0 to load further pages.
      offset = 0,
    ): Promise<TopMoversResponse> {
      // S9 composed endpoint returns raw screener results from S3.
      // The exact wire shape is documented on RawTopMoversResponse above.
      const raw = await apiFetch<RawTopMoversResponse>(
        // WHY include offset: backend supports pagination through the sorted
        // universe; the dashboard always passes 0 today but future leaderboard
        // pages will use offset to fetch subsequent pages.
        `/v1/market/top-movers?type=${moverType}&limit=${limit}&period=${period}&offset=${offset}`,
        { token: t },
      );

      // WHY delegate to transformTopMoversResponse: the SAME transform must be
      // applied by DashboardBundleHydrator when it seeds widget caches from the
      // bundle legs. One shared pure function = no shape drift between the
      // hydrated cache and the per-widget refetch path (Round 1 foundation fix).
      return transformTopMoversResponse(raw, moverType);
    },

    /**
     * getMarketSparklines — batch N-day close-price arrays for sparkline rows.
     *
     * WHY THIS EXISTS (Round 1 foundation): the TopMovers widget renders a
     * 5-day sparkline per mover row. One GET /v1/ohlcv per row would be 10-20
     * round-trips; S9's batch endpoint (PLAN-0108 W2) fans out server-side and
     * returns everything in ONE request.
     *
     * RESPONSE SHAPE (S9): `{ data: { "<instrument_id>": [close, ...] },
     * meta: {...} }` — close arrays are oldest-first, which is exactly the
     * order the <Sparkline> primitive expects (left = oldest).
     *
     * WHY return the unwrapped Record (not the envelope): callers always do
     * `series[id]` immediately; unwrapping at the API boundary matches the
     * convention set by getCompanyOverviewsBatch.
     *
     * WHY sort ids before joining: [A,B] and [B,A] are the same logical
     * request — a stable param string lets TanStack Query share one cache
     * entry across row-order changes (same rationale as useHoldingsSeries).
     */
    async getMarketSparklines(
      instrumentIds: string[],
      days = 5,
    ): Promise<Record<string, number[]>> {
      const idsParam = [...instrumentIds].sort().join(",");
      const resp = await apiFetch<{ data: Record<string, number[]> }>(
        `/v1/market/sparklines?instrument_ids=${encodeURIComponent(idsParam)}&days=${days}`,
        { token: t },
      );
      return resp.data ?? {};
    },

    /**
     * getEconomicCalendar — upcoming macro economic events
     *
     * WHY transform: S9 passes through S7's raw TemporalEventsListResponse which
     * uses different field names. S7 uses `active_from` (not `event_date`), `region`
     * (not `country`), `confidence` (not `impact`), and embeds values in a free-text
     * `description` field ("Actual: X, Previous: Y"). Without this transform,
     * `new Date(event.event_date)` throws RangeError: Invalid time value (BP-370)
     * because `event.event_date` is undefined — crashing the panel silently.
     */
    async getEconomicCalendar(params?: {
      limit?: number;
      offset?: number;
    }): Promise<EconomicCalendarResponse> {
      // WHY URLSearchParams: only forward params the caller actually set so we
      // don't send "?limit=undefined" which some FastAPI validators reject.
      const qs = new URLSearchParams();
      if (params?.limit != null) qs.set("limit", String(params.limit));
      if (params?.offset != null) qs.set("offset", String(params.offset));
      const query = qs.toString();
      const raw = await apiFetch<{
        events: Array<{
          event_id: string;
          title: string;
          region?: string;
          description?: string;
          active_from: string;
          confidence?: number;
        }>;
        total?: number;
      }>(`/v1/fundamentals/economic-calendar${query ? `?${query}` : ""}`, { token: t });

      // Parse "Actual: X, Previous: Y, Forecast: Z" from S7 description text
      const parseDesc = (desc?: string) => {
        const m = (label: string) => {
          const match = desc?.match(new RegExp(`${label}:\\s*([\\-\\d.]+)`));
          return match ? parseFloat(match[1]) : null;
        };
        return { actual: m("Actual"), previous: m("Previous"), forecast: m("Forecast") };
      };

      // Derive EconomicImpact from S7 confidence score (no impact enum in S7)
      const toImpact = (c?: number): import("@/types/api").EconomicImpact =>
        (c ?? 0.5) >= 0.8 ? "HIGH" : (c ?? 0.5) >= 0.5 ? "MEDIUM" : "LOW";

      const events = (raw.events ?? []).map((ev) => {
        const { actual, previous, forecast } = parseDesc(ev.description);
        return {
          event_id: ev.event_id,
          title: ev.title,
          country: ev.region ?? "US",
          currency: null as string | null,
          event_date: ev.active_from, // S7 uses active_from; remap to expected field
          actual,
          previous,
          forecast,
          impact: toImpact(ev.confidence),
          unit: null as string | null,
        };
      });

      // WHY pass through `total`: lets the EconomicCalendar widget render a
      // "Load more" button when more events exist beyond the current page.
      return { events, total: raw.total };
    },

    /**
     * getEarningsCalendar — upcoming company earnings events (consumer 13D-9)
     *
     * WHY separate from getEconomicCalendar: earnings events are corporate
     * (event_type=corporate in S7 temporal_events) while economic events are
     * macro (event_type=macro). S9 enforces this split — the proxy injects
     * event_type=corporate and strips any caller-supplied override (BP-340).
     *
     * WHY optional date params: the EarningsCalendarWidget uses the S7 default
     * window (today + 7 days) when no params are supplied; callers can supply
     * from_date/to_date to scope a custom range (e.g. the full earnings season
     * view in a future page).
     *
     * DATA SOURCE: S9 GET /v1/fundamentals/earnings-calendar. PLAN-0068 Wave A-2.
     */
    getEarningsCalendar(params?: {
      from_date?: string;
      to_date?: string;
      limit?: number;
      offset?: number;
    }): Promise<EarningsCalendarResponse> {
      // Build query string from optional params — only include keys with values
      // so we never send ?from_date=undefined which confuses some FastAPI validators.
      const qs = new URLSearchParams();
      if (params?.from_date) qs.set("from_date", params.from_date);
      if (params?.to_date) qs.set("to_date", params.to_date);
      if (params?.limit != null) qs.set("limit", String(params.limit));
      // WHY include offset: backend supports paginating through the earnings
      // window via `offset`; the widget uses it to drive a "Load more" button.
      if (params?.offset != null) qs.set("offset", String(params.offset));
      const query = qs.toString();
      return apiFetch<EarningsCalendarResponse>(
        `/v1/fundamentals/earnings-calendar${query ? `?${query}` : ""}`,
        { token: t },
      );
    },

    /**
     * getMorningBrief — AI-generated morning brief (24h Valkey cache)
     */
    getMorningBrief(): Promise<BriefingResponse> {
      return apiFetch<BriefingResponse>("/v1/briefings/morning", { token: t });
    },

    /**
     * getInstrumentBrief — per-instrument AI brief
     */
    getInstrumentBrief(entityId: string): Promise<BriefingResponse> {
      return apiFetch<BriefingResponse>(
        `/v1/briefings/instrument/${encodeURIComponent(entityId)}`,
        { token: t },
      );
    },

    /**
     * getAiSignals — NEWS MOMENTUM feed for the dashboard "AI SIGNALS" widget.
     *
     * 2026-06-12 Wave-4 pivot: this endpoint no longer returns extraction-
     * confidence "signals" (internal pipeline state). It now returns the most
     * relevant RECENT NEWS in a time window — real, clickable articles with an
     * honest ``relevance`` score and a ``sentiment`` direction. See
     * services/api-gateway routes/signals.py for the full rationale + payload.
     *
     * @param limit  max rows to return (default 8).
     * @param hours  look-back window — one of 24 | 72 | 168. Optional and
     *               additive so legacy callers (getAiSignals(8)) keep working;
     *               the server snaps any out-of-set value to its 72h default.
     */
    getAiSignals(limit = 8, hours?: number): Promise<AiSignalsResponse> {
      // Only append &hours= when the caller passed one — keeps the URL (and the
      // server-side cache key) identical to the legacy call when it's omitted.
      const hoursParam = hours != null ? `&hours=${hours}` : "";
      return apiFetch<AiSignalsResponse>(`/v1/signals/ai?limit=${limit}${hoursParam}`, {
        token: t,
      });
    },

    /**
     * getDashboardSnapshot — fetch all dashboard initial data in one request.
     *
     * WHY: collapses 6+ individual useQuery hooks on the dashboard cold-start
     * into a single bundle request. S9 fans out to 6 upstream services
     * concurrently (asyncio.gather) and returns the results in one response.
     *
     * Per-leg null means that upstream call failed — the frontend renders "—"
     * or a skeleton for null legs. _meta.partial=true when any leg is null.
     *
     * PLAN-0070 C-2 / T-C-2-03.
     */
    getDashboardSnapshot(): Promise<DashboardSnapshotResponse> {
      return apiFetch<DashboardSnapshotResponse>(`/v1/dashboard/snapshot`, {
        token: t,
      });
    },

    /**
     * getDashboardBundle — F-2 single composite endpoint for the dashboard page.
     *
     * WHY a SECOND dashboard composite: see DashboardBundleResponse JSDoc.
     * The page calls this ONCE at the top and hydrates per-widget TanStack
     * caches from the legs via queryClient.setQueryData, eliminating
     * per-widget wave-serialized initial fetches on cold start.
     *
     * Endpoint: GET /v1/dashboard/bundle.
     */
    getDashboardBundle(): Promise<DashboardBundleResponse> {
      return apiFetch<DashboardBundleResponse>(`/v1/dashboard/bundle`, {
        token: t,
      });
    },
  };
}
