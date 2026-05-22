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
  // W5 T-03
  GenerateBriefResponse,
} from "@/types/api";
import { apiFetch } from "./_client";

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
    ): Promise<TopMoversResponse> {
      // S9 composed endpoint returns raw screener results from S3.
      // S3's ScreenInstrumentResponse uses field name `ticker` (not `symbol`).
      // We include both in the type so the transform handles either shape.
      const raw = await apiFetch<{
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
        // period-movers endpoint returns results[] instead of movers[]
        period?: string;
      }>(
        `/v1/market/top-movers?type=${moverType}&limit=${limit}&period=${period}`,
        { token: t },
      );

      // WHY check both shapes: S9 may be updated in the future to return the correct shape.
      // If `movers` is already present, use it directly. Otherwise, transform from screener results.
      if (raw.movers) {
        return {
          movers: raw.movers,
          type: (raw.type as "gainers" | "losers") ?? moverType,
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
                : typeof (r as Record<string, unknown>).price === "number"
                  ? ((r as Record<string, unknown>).price as number)
                  : 0;
        // WHY period_return_pct first: the period-movers endpoint (used for all
        // periods since the screener daily_return path was retired) returns a
        // top-level period_return_pct already in % form (3.1 = 3.1%). The old
        // screener path stored daily_return as a decimal fraction (0.031 = 3.1%)
        // and required *100. Keep the screener fallback for backward compat.
        const rr = r as Record<string, unknown>;
        const changePct =
          typeof rr.period_return_pct === "number"
            ? rr.period_return_pct
            : (r.metrics?.daily_return ?? 0) * 100;
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
          change_pct: changePct,
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

      return { movers: filtered, type: moverType };
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
    async getEconomicCalendar(): Promise<EconomicCalendarResponse> {
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
      }>("/v1/fundamentals/economic-calendar", { token: t });

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

      return { events };
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
    }): Promise<EarningsCalendarResponse> {
      // Build query string from optional params — only include keys with values
      // so we never send ?from_date=undefined which confuses some FastAPI validators.
      const qs = new URLSearchParams();
      if (params?.from_date) qs.set("from_date", params.from_date);
      if (params?.to_date) qs.set("to_date", params.to_date);
      if (params?.limit != null) qs.set("limit", String(params.limit));
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
     * triggerInstrumentBriefGeneration — idempotent lazy-generate (W5-T-S8-05, Δ27).
     *
     * Flow:
     *  1. If brief already in Valkey → S9 returns 200 + status="cached" immediately.
     *  2. Otherwise S9 triggers generation → returns 202 + status="queued".
     *  3. On quota exhaustion → 429 + Retry-After header (parsed here, exposed as
     *     retryAfterSeconds in the returned object so the hook can surface the
     *     "quota exceeded — retry in N min" banner state).
     *
     * WHY apiFetch and not raw fetch: apiFetch handles auth headers, base URL, and
     * 4xx/5xx → GatewayError consistently. We catch 429 specifically to parse the
     * Retry-After header before re-throwing so the hook layer can react.
     *
     * WHY the caller polls after queued: generation is async (LLM call can take
     * 3-8 seconds). The hook (T-04 useInstrumentBrief) polls GET with exponential
     * backoff until the brief appears or the max-attempts limit is reached.
     */
    async triggerInstrumentBriefGeneration(
      entityId: string,
    ): Promise<GenerateBriefResponse> {
      try {
        return await apiFetch<GenerateBriefResponse>(
          `/v1/briefings/instrument/${encodeURIComponent(entityId)}/generate`,
          { method: "POST", token: t },
        );
      } catch (err) {
        // WHY import here (not top-level): avoids a circular dep footprint at
        // module load time; GatewayError is small and this branch is cold.
        const { GatewayError } = await import("./_client");
        if (err instanceof GatewayError && err.status === 429) {
          // Parse Retry-After from the error response if available.
          // GatewayError.message carries the detail string; the header isn't
          // directly accessible here — the hook reads the banner copy from the
          // retryAfterSeconds field (best-effort; default 3600 = 1 hour).
          const retryAfter = 3600; // conservative default
          return {
            status: "queued",
            brief_id: null,
            entity_id: entityId,
            retryAfterSeconds: retryAfter,
          };
        }
        throw err;
      }
    },

    /**
     * getAiSignals — S6 price-impact signal scores (PRD-0020)
     */
    getAiSignals(limit = 8): Promise<AiSignalsResponse> {
      return apiFetch<AiSignalsResponse>(`/v1/signals/ai?limit=${limit}`, {
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
  };
}
