/**
 * lib/api/dashboard.ts — Dashboard composed endpoints (heatmap, top movers,
 * economic calendar, AI briefings, AI signals).
 */

import type {
  EconomicCalendarResponse,
  MarketHeatmapResponse,
  TopMoversResponse,
  AiSignalsResponse,
  BriefingResponse,
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
          change_pct: (r.metrics?.daily_return ?? 0) * 100,
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
     */
    getEconomicCalendar(): Promise<EconomicCalendarResponse> {
      return apiFetch<EconomicCalendarResponse>("/v1/fundamentals/economic-calendar", {
        token: t,
      });
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
     * getAiSignals — S6 price-impact signal scores (PRD-0020)
     */
    getAiSignals(limit = 8): Promise<AiSignalsResponse> {
      return apiFetch<AiSignalsResponse>(`/v1/signals/ai?limit=${limit}`, {
        token: t,
      });
    },
  };
}
