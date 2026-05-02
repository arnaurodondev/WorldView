/**
 * lib/api/screener.ts — Fundamentals screener (fields catalog + query execution).
 */

import type {
  ScreenerField,
  ScreenerRequest,
  ScreenerResponse,
  ScreenerResult,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createScreenerApi(t: string | undefined) {
  return {
    /**
     * getScreenerFields — available filter fields for the screener UI
     * Cached by S9/S3 for 6h — infrequently changes
     */
    getScreenerFields(): Promise<ScreenerField[]> {
      return apiFetch<ScreenerField[]>("/v1/fundamentals/screen/fields");
    },

    /**
     * runScreener — execute a screener query
     * Used by Screener page filter form
     *
     * PLAN-0052 platform-QA round 4 (2026-05-01): the backend response
     * is `{instrument_id, ticker, name, exchange, sector, metrics: {…}}`
     * but the frontend `ScreenerResult` type expects flat fields
     * (`gics_sector`, `current_price`, `market_cap`, `pe_ratio`, etc.).
     * Without a transformer every metric column rendered "—" and
     * row-clicks tried to navigate to `/instruments/undefined` because
     * `entity_id` was missing too. We flatten the metrics dict and map
     * `sector → gics_sector` here in the gateway client so the UI types
     * line up. `entity_id` is computed as a Worldview-conventional
     * `entity-{ticker-lc}` slug when the backend doesn't provide one
     * (matches the IndexTicker / GlobalSearch fallback convention) so
     * row-click navigation lands on the correct entity page.
     */
    async runScreener(request: ScreenerRequest): Promise<ScreenerResponse> {
      const raw = await apiFetch<
        {
          results?: Array<Record<string, unknown>>;
          items?: Array<Record<string, unknown>>;
          total?: number;
          count?: number;
        } & Record<string, unknown>
      >("/v1/fundamentals/screen", {
        method: "POST",
        body: request,
        token: t,
      });
      // Backend response uses either `results` or `items`; tolerate both.
      const rawRows = (raw.results ?? raw.items ?? []) as Array<Record<string, unknown>>;
      const flattened: ScreenerResult[] = rawRows.map((row) => {
        const metrics = (row["metrics"] as Record<string, unknown> | undefined) ?? {};
        const ticker = String(row["ticker"] ?? "");
        // Pull every known metric out of the nested dict; coerce to number
        // so the formatters don't choke on numeric strings the backend
        // sometimes returns.
        const num = (v: unknown): number | null => {
          if (v === null || v === undefined || v === "") return null;
          const n = typeof v === "number" ? v : Number(v);
          return Number.isFinite(n) ? n : null;
        };
        return {
          instrument_id: String(row["instrument_id"] ?? ""),
          // PLAN-0052: synthesize entity_id from ticker when the backend
          // doesn't provide one. ADR-F-12 says entity_id is the canonical
          // navigation key for /instruments/[entityId]; the GlobalSearch
          // + IndexTicker chips already use this `entity-{ticker-lc}`
          // convention, so the screener row click now lands on a real
          // page instead of /instruments/undefined.
          entity_id:
            (row["entity_id"] as string | undefined) ??
            `entity-${ticker.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
          ticker,
          name: String(row["name"] ?? ""),
          exchange: (row["exchange"] as string | undefined) ?? null,
          // Sector key rename: backend `sector` → frontend `gics_sector`.
          gics_sector:
            (row["gics_sector"] as string | undefined) ??
            (row["sector"] as string | undefined) ??
            null,
          current_price: num(row["current_price"] ?? metrics["current_price"]),
          market_cap: num(
            row["market_cap"] ?? metrics["market_cap"] ?? metrics["market_capitalization"],
          ),
          pe_ratio: num(row["pe_ratio"] ?? metrics["pe_ratio"]),
          daily_return: num(row["daily_return"] ?? metrics["daily_return"]),
          revenue: num(row["revenue"] ?? metrics["revenue"]),
          beta: num(row["beta"] ?? metrics["beta"]),
          market_impact_score: num(
            row["market_impact_score"] ?? metrics["market_impact_score"],
          ),
        } as unknown as ScreenerResult;
      });
      return {
        results: flattened,
        total: (raw.total as number | undefined) ?? flattened.length,
        // ScreenerResponse requires `offset`/`limit` per the type — pass
        // through the request's pagination so the UI can render
        // pagination chrome correctly. Fall back to 0/length if absent.
        offset: (request as { offset?: number }).offset ?? 0,
        limit: (request as { limit?: number }).limit ?? flattened.length,
      };
    },
  };
}
