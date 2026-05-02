/**
 * lib/api/search.ts — Global instrument search.
 *
 * SCOPE: bare-instrument search (S3) + entity-aware search that enriches
 * candidates with their KG entity_id via the company-overview endpoint.
 *
 * NOTE on `this`: `searchFundamentals` calls `this.searchInstruments` (same
 * domain) and `this.getCompanyOverview` (instruments domain). After the
 * gateway shim spreads this factory's return alongside the instruments
 * factory's return, both are reachable on the merged object so `this` works.
 * The minimal shape required by `this` is captured by `SearchApiThis`.
 */

import type { SearchResult, SearchResponse, CompanyOverview } from "@/types/api";
import { apiFetch } from "./_client";

// Minimal `this` contract: `searchFundamentals` needs access to
// `searchInstruments` (this same factory) AND `getCompanyOverview` (instruments
// factory). Declaring it explicitly lets TypeScript verify that the merged
// gateway shim provides everything we depend on.
type SearchApiThis = {
  searchInstruments(q: string, limit?: number): Promise<SearchResponse>;
  getCompanyOverview(instrumentId: string): Promise<CompanyOverview>;
};

export function createSearchApi(t: string | undefined) {
  // Note: t is unused by /v1/search/instruments (public endpoint) but is kept
  // in the factory signature for symmetry with other domain APIs and so that
  // future authenticated search endpoints don't change the surface.
  void t;

  return {
    /**
     * searchInstruments — global instrument search for TopBar command palette
     * Public endpoint — no token needed
     *
     * WHY transform: S9 proxies to S3's `GET /api/v1/instruments` which returns
     * `InstrumentListResponse` = `{items: [{id, security_id, symbol, exchange, is_active, flags, created_at}], total, limit, offset}`.
     * The frontend expects `SearchResponse` = `{results: SearchResult[], query: string}` where each
     * result has `instrument_id`, `entity_id`, `ticker` (not `symbol`), `name`, and `type`.
     * S3 instruments have no `name` field or `entity_id` — we synthesise from available data.
     */
    async searchInstruments(q: string, limit = 10): Promise<SearchResponse> {
      // S3 returns InstrumentListResponse with `items` array
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          security_id: string;
          symbol: string;
          exchange: string;
          is_active: boolean;
          flags: {
            has_ohlcv: boolean;
            has_quotes: boolean;
            has_fundamentals: boolean;
          };
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(`/v1/search/instruments?q=${encodeURIComponent(q)}&limit=${limit}`);

      // Transform S3 InstrumentResponse into frontend SearchResult type
      const results: SearchResult[] = (raw.items ?? []).map((inst) => ({
        instrument_id: inst.id,
        // WHY same as instrument_id: S3 does not track entity_id on instruments.
        // Entity linking happens in S7 Knowledge Graph. Using instrument_id as fallback
        // so navigation works (Instrument Detail page accepts either ID).
        entity_id: inst.id,
        ticker: inst.symbol, // S3 calls it "symbol", frontend calls it "ticker"
        // WHY synthesised name: S3's InstrumentResponse has no `name` field.
        // We create a readable name from "SYMBOL (EXCHANGE)" for display in the
        // search results dropdown. The real name comes from fundamentals data.
        name: `${inst.symbol} (${inst.exchange})`,
        exchange: inst.exchange,
        // WHY derive type from flags: S3 doesn't have an explicit instrument type field.
        // We infer "equity" as default since most instruments in the system are equities.
        // A more accurate mapping would require fundamentals data (asset_class field).
        type: "equity",
      }));

      return { results, query: q };
    },

    /**
     * searchFundamentals — entity-aware instrument search.
     *
     * WHY this exists (BUG-7 / B-3): `searchInstruments` queries S3 which has no
     * concept of `entity_id` — it falls back to `entity_id = instrument_id`. The
     * watchlist add-member endpoint requires the REAL KG entity_id from S7. Posting
     * an instrument_id silently fails or produces an orphaned member.
     *
     * Live-stack reality (verified 2026-04-28): the fundamentals screener does NOT
     * support text search (only numeric metric filters), and S3's
     * /v1/search/instruments returns no entity_id. The reliable path is:
     *  1) S3 search to find candidate instrument_ids matching the query,
     *  2) /v1/companies/{id}/overview per candidate to get the real entity_id +
     *     authoritative ticker/name from the KG-joined view.
     *
     * WHY parallelised overviews: the search returns at most `limit` candidates
     * (usually ≤8). Promise.all on a handful of GETs is cheaper than sequential.
     * WHY catch+filter: a missing overview shouldn't abort the entire dropdown —
     * we just drop that row and surface the rest.
     */
    async searchFundamentals(
      this: SearchApiThis,
      q: string,
      limit = 8,
    ): Promise<SearchResponse> {
      const trimmed = q.trim();
      if (!trimmed) return { results: [], query: q };
      // Step 1: candidate instruments from S3 search
      const candidates = await this.searchInstruments(trimmed, limit);
      if (candidates.results.length === 0) return { results: [], query: q };
      // Step 2: enrich each candidate with the real entity_id via the overview endpoint
      const enriched = await Promise.all(
        candidates.results.map(async (cand) => {
          try {
            const ov = await this.getCompanyOverview(cand.instrument_id);
            // WHY guard against missing entity_id: stale or unsynced instruments
            // may have null entity_id — those cannot be added to a watchlist.
            if (!ov.instrument?.entity_id) return null;
            return {
              instrument_id: cand.instrument_id,
              entity_id: ov.instrument.entity_id,
              ticker: ov.instrument.ticker ?? cand.ticker,
              name: ov.instrument.name ?? cand.name,
              exchange: ov.instrument.exchange ?? cand.exchange ?? "—",
              type: cand.type,
            } satisfies SearchResult;
          } catch {
            return null;
          }
        }),
      );
      const results = enriched.filter((r): r is SearchResult => r !== null);
      return { results, query: q };
    },
  };
}
