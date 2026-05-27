/**
 * lib/api/screener.ts — Fundamentals screener (fields catalog + query execution).
 */

import type {
  NLScreenerResponse,
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
     * (matches the IndexStrip / GlobalSearch fallback convention) so
     * row-click navigation lands on the correct entity page.
     */
    /**
     * translateNLScreenerQuery — POST /v1/screener/nl-translate
     * Converts a natural-language query ("profitable tech stocks under $50") into a
     * structured { filters, explanation } object the screener can apply directly.
     * Returns `explanation` (LLM-generated 1-sentence description) + `filters` map.
     * PLAN-0092 Wave A.
     */
    translateNLScreenerQuery(query: string): Promise<NLScreenerResponse> {
      return apiFetch<NLScreenerResponse>("/v1/screener/nl-translate", {
        method: "POST",
        body: { query },
        token: t,
      });
    },

    /**
     * getScreenerCount — debounced live-count probe.
     *
     * PRD-0089 Wave I-A · T-IA-11.
     *
     * WHY a dedicated method (not `runScreener` with `limit: 1`): callers
     * MUST only receive `{ total }` — never the row payload. Hard-coding
     * `limit: 1` here means a future `runScreener` callsite cannot
     * accidentally drop pagination and end up making a count-only query
     * that returns a single row to render. Returning a stripped object
     * keeps the TanStack Query selector tiny (just an integer).
     *
     * WHY limit=1 (not 0): the backend `POST /v1/fundamentals/screen`
     * historically interprets `limit: 0` as "all rows" on some adapters.
     * `limit: 1` is the safe minimum that guarantees a single-row scan.
     *
     * USED BY: the screener live-count hook (debounced 250 ms while the
     * user edits filters in the popover, before they click Apply).
     */
    async getScreenerCount(
      request: ScreenerRequest,
    ): Promise<{ total: number }> {
      // WHY spread + override: callers pass the full ScreenerRequest from the
      // popover; we keep their filters but force-cap `limit` to 1 so the
      // response stays a single row regardless of what the popover sent.
      const probe: ScreenerRequest = { ...request, limit: 1, offset: 0 };
      const raw = await apiFetch<{ total?: number; results?: unknown[] }>(
        "/v1/fundamentals/screen",
        { method: "POST", body: probe, token: t },
      );
      // WHY fall back to results.length: not all backend versions echo
      // `total` when the result set is < limit. The count probe must still
      // surface a number rather than NaN so the UI badge can render.
      const total =
        typeof raw.total === "number"
          ? raw.total
          : Array.isArray(raw.results)
            ? raw.results.length
            : 0;
      return { total };
    },

    async runScreener(request: ScreenerRequest): Promise<ScreenerResponse> {
      // WHY GET for no-filter case: the POST screener uses INNER JOIN on each
      // filter metric, which excludes instruments that lack that metric's data.
      // The GET /fundamentals/screen endpoint does a plain instruments scan
      // (no metric join) and returns all instruments — the intended default view.
      const isDefaultFilter =
        request.filters.length === 1 &&
        request.filters[0].metric === "market_capitalization" &&
        request.filters[0].min_value === 0 &&
        request.filters[0].max_value === undefined &&
        !request.filters[0].sector;

      const raw = await apiFetch<
        {
          results?: Array<Record<string, unknown>>;
          items?: Array<Record<string, unknown>>;
          total?: number;
          count?: number;
        } & Record<string, unknown>
      >(
        isDefaultFilter
          ? `/v1/fundamentals/screen?limit=${request.limit}&offset=${request.offset ?? 0}`
          : "/v1/fundamentals/screen",
        isDefaultFilter
          ? { method: "GET", token: t }
          : { method: "POST", body: request, token: t },
      );
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
          // + IndexStrip chips already use this `entity-{ticker-lc}`
          // convention, so the screener row click now lands on a real
          // page instead of /instruments/undefined.
          // BP-330: entity_id falls back to the raw instrument_id string so
          // row-click navigation lands on /instruments/<UUID> (the canonical
          // entity page path). The previous `entity-${ticker-lc}` slug was never
          // a real entity_id — the backend always emits a UUIDv7 for entity_id.
          entity_id: (row["entity_id"] as string | undefined) ?? String(row["instrument_id"] ?? ""),
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
          // BP-331: backend emits revenue as `revenue_usd` inside the metrics dict.
          // Try revenue_usd first, then fall back to the generic `revenue` key
          // (used by older screener API versions) and the top-level row field.
          revenue: num(metrics["revenue_usd"] ?? metrics["revenue"] ?? row["revenue"]),
          beta: num(row["beta"] ?? metrics["beta"]),
          market_impact_score: num(
            row["market_impact_score"] ?? metrics["market_impact_score"],
          ),
          // PLAN-0092 Wave C: new default + opt-in metric columns
          forward_pe: num(row["forward_pe"] ?? metrics["forward_pe"]),
          dividend_yield: num(row["dividend_yield"] ?? metrics["dividend_yield"]),
          revenue_growth_yoy: num(row["revenue_growth_yoy"] ?? metrics["revenue_growth_yoy"]),
          roe: num(row["roe"] ?? metrics["roe"] ?? metrics["return_on_equity"]),
          operating_margin_ttm: num(
            row["operating_margin_ttm"] ?? metrics["operating_margin_ttm"],
          ),
          enterprise_value_ebitda: num(
            row["enterprise_value_ebitda"] ?? metrics["enterprise_value_ebitda"],
          ),
          avg_volume_30d: num(row["avg_volume_30d"] ?? metrics["avg_volume_30d"]),
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
