/**
 * lib/api/screener.ts — Fundamentals screener (fields catalog + query execution).
 */

import type {
  ScreenerField,
  ScreenerFilter,
  ScreenerRequest,
  ScreenerResponse,
  ScreenerResult,
} from "@/types/api";
import { apiFetch } from "./_client";

/**
 * ScreenerRowEnriched — Wave-2 (2026-06-10) additive fields on top of the
 * shared ScreenerResult type.
 *
 * WHY a local extension type (not new fields on types/api.ts ScreenerResult):
 * types/api.ts is a SHARED file owned by no single surface; this sprint runs
 * several surface agents concurrently and the screener surface must stay
 * self-contained (same precedent as SnapshotVolumeFields in
 * features/screener/lib/build-filters.ts). ScreenerResult already carries an
 * `[key: string]: unknown` index signature, so these keys are type-legal on
 * the object — this interface just gives the screener's own renderers a
 * typed view of them.
 *
 * FIELD PROVENANCE (Wave-1 backend, POST /v1/fundamentals/screen):
 *   volume    — latest 1-day OHLCV bar volume (NOT the 30d average; that is
 *               the separate avg_volume_30d snapshot column). Used by the
 *               VOLUME column, with brightness derived from volume /
 *               avg_volume_30d.
 *   high_52w  — absolute 52-week high price (USD). Replaces the old
 *               tooltip derivation `price / (1 + dist_high)` which needed a
 *               live quote (sparse: ~40/596 instruments have one).
 *   low_52w   — absolute 52-week low price (USD). Same rationale.
 */
export interface ScreenerRowEnriched extends ScreenerResult {
  volume?: number | null;
  high_52w?: number | null;
  low_52w?: number | null;
}

export function createScreenerApi(t: string | undefined) {
  return {
    /**
     * getScreenerFields — available filter fields for the screener UI
     * Cached by S9/S3 for 6h — infrequently changes
     *
     * WHY a transform (PLAN-0113 QA, 2026-06-20): the live S3 endpoint returns
     * a WRAPPED envelope `{ "fields": [...] }`, and each field carries
     * `"type": "numeric"` (not `"number"`) plus no `operators` array. The
     * frontend `ScreenerField` contract (and the sole consumer, the alert
     * wizard's `MetricPicker`) expects a FLAT `ScreenerField[]` whose numeric
     * fields are `type === "number"`. Returning the raw object made
     * `(data ?? []).filter(...)` operate on a dict — the MetricPicker dropdown
     * silently rendered ZERO metrics, so FUNDAMENTAL_CROSS alert rules could
     * never be created. We unwrap + normalise here so every caller sees the
     * documented array shape regardless of the backend envelope.
     */
    async getScreenerFields(): Promise<ScreenerField[]> {
      // Tolerate BOTH the wrapped `{fields:[...]}` envelope (live S3) and a
      // bare array (older/mocked shape) so this never regresses if the backend
      // is changed to return a flat list.
      const raw = await apiFetch<
        { fields?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>
      >("/v1/fundamentals/screen/fields");
      const rows: Array<Record<string, unknown>> = Array.isArray(raw)
        ? raw
        : (raw.fields ?? []);
      return rows.map((f) => {
        // Map the backend's "numeric" type onto the frontend's "number"; pass
        // "string" / "select" through unchanged.
        const rawType = String(f["type"] ?? "");
        const type: ScreenerField["type"] =
          rawType === "numeric" || rawType === "number"
            ? "number"
            : rawType === "select"
              ? "select"
              : "string";
        return {
          name: String(f["name"] ?? ""),
          label: String(f["label"] ?? f["name"] ?? ""),
          type,
          // The live endpoint omits `operators`; default to an empty list so
          // the typed contract holds. (MetricPicker does not read operators.)
          operators: Array.isArray(f["operators"]) ? (f["operators"] as string[]) : [],
          options: (f["options"] as ScreenerField["options"]) ?? undefined,
          description: (f["description"] as string | null | undefined) ?? null,
        } satisfies ScreenerField;
      });
    },

    /**
     * runScreener — execute a screener query
     * Used by Screener page filter form
     *
     * PLAN-0052 platform-QA round 4 (2026-05-01): the backend response
     * used to be `{instrument_id, ticker, name, exchange, sector, metrics: {…}}`
     * but the frontend `ScreenerResult` type expects flat fields
     * (`gics_sector`, `current_price`, `market_cap`, `pe_ratio`, etc.).
     * Wave-2 update (2026-06-10): the Wave-1 backend now emits FLAT rows
     * (no nested `metrics` dict) — the `row[...] ?? metrics[...]` fallback
     * chains below handle both shapes, so this transformer is agnostic to
     * which one is in flight.
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
      // ── Wave-2 (2026-06-10): ALWAYS POST — the GET route is GONE ──────────
      // The gateway removed `GET /v1/fundamentals/screen` in Wave 1: the path
      // now falls through to `GET /v1/fundamentals/{instrument_id}` where
      // "screen" fails UUID parsing with a 422 (live-verified 2026-06-10).
      // The old GET branch existed because the POST path used to INNER JOIN on
      // each filter metric and only echo the FILTERED metrics — every other
      // column blanked to "—" the moment a filter applied. Wave 1 fixed that
      // backend-side: POST now returns the FULL key-metrics set (market_cap,
      // pe_ratio, revenue, roe, volume, high_52w/low_52w, snapshot fields, …)
      // for BOTH the default view (`filters: []`, live total=666) and filtered
      // views (live-verified with a pe_ratio filter: 100/100 rows carried
      // market_cap, revenue, roe, etc.). So one POST path serves everything.
      const raw = await apiFetch<
        {
          results?: Array<Record<string, unknown>>;
          items?: Array<Record<string, unknown>>;
          total?: number;
          count?: number;
        } & Record<string, unknown>
      >("/v1/fundamentals/screen", { method: "POST", body: request, token: t });
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
          // ── Core quote / price fields ────────────────────────────────────────
          // current_price is emitted as metrics["current_price"] (LEFT JOIN on
          // instrument_quotes in the backend). AAPL shows price because its quote
          // row exists; most others don't have a quote row yet → null → "—".
          current_price: num(row["current_price"] ?? metrics["current_price"]),
          // ── Core fundamental metrics ─────────────────────────────────────────
          // These come from the `metrics` dict keyed by fundamental_metrics.metric
          // names. Backend key → frontend field mapping documented per-field.
          market_cap: num(
            row["market_cap"] ?? metrics["market_cap"] ?? metrics["market_capitalization"],
          ),
          pe_ratio: num(row["pe_ratio"] ?? metrics["pe_ratio"]),
          daily_return: num(row["daily_return"] ?? metrics["daily_return"]),
          // BP-331: backend emits revenue as `revenue_ttm` (the corrected metric name
          // used since the PRD-0099 fix) inside the metrics dict. `revenue_usd` was
          // the old key that was never populated; fall through to generic `revenue`.
          revenue: num(
            metrics["revenue_ttm"] ?? metrics["revenue_usd"] ?? metrics["revenue"] ?? row["revenue"],
          ),
          beta: num(row["beta"] ?? metrics["beta"]),
          // market_impact_score has NO backend data source (confirmed Wave-2,
          // 2026-06-10: the field is absent from every live row — default AND
          // filtered). Kept in the flattened shape because the SCORE column
          // definition survives as an opt-in (hidden by default, see
          // ag-screener-columns.tsx) and the export accessor reads it.
          market_impact_score: num(
            row["market_impact_score"] ?? metrics["market_impact_score"],
          ),
          avg_volume_30d: num(metrics["avg_volume_30d"] ?? row["avg_volume_30d"]),
          // ── Wave-2 (2026-06-10): new flat fields from the Wave-1 backend ────
          // The backend now emits these top-level on every row (default AND
          // filtered views). The metrics-dict fallbacks are kept for
          // back-compat with any older payload shape still in flight.
          //
          // volume — latest 1-day bar volume. Distinct from avg_volume_30d:
          // the VOLUME column renders `volume` and uses the volume /
          // avg_volume_30d ratio to set cell brightness (above-average volume
          // renders at full opacity, below-average dims).
          volume: num(row["volume"] ?? metrics["volume"]),
          // high_52w / low_52w — absolute 52-week high/low prices (USD).
          // The 52W RANGE tooltip previously DERIVED these from current_price
          // + the dist_from_52w_*_pct fractions, which silently dropped the
          // dollar range for the ~93% of instruments with no live quote.
          // Real values ship on every row now (200/200 live coverage).
          high_52w: num(row["high_52w"] ?? metrics["high_52w"]),
          low_52w: num(row["low_52w"] ?? metrics["low_52w"]),
          // ── PRD-0099 Wave I: new fundamental columns ─────────────────────────
          // Backend stores these metrics with suffixed names in fundamental_metrics
          // table (e.g. roe_ttm), but the frontend ScreenerResult type uses shorter
          // names (roe). Map here to avoid "—" on all rows in the new columns.
          //
          // WHY suffix normalization here (not in the column renderer): the AG Grid
          // `field` accessor (e.g. field: "roe") reads directly from the flat row
          // object — if the key is missing entirely, AG Grid passes undefined to the
          // renderer, which shows "—". Normalizing in this single place keeps all
          // renderers and column definitions using the clean short name.
          forward_pe: num(metrics["forward_pe"] ?? row["forward_pe"]),
          dividend_yield: num(metrics["dividend_yield"] ?? row["dividend_yield"]),
          // Backend key: roe_ttm → frontend key: roe
          roe: num(metrics["roe"] ?? metrics["roe_ttm"] ?? row["roe"]),
          // Backend key: operating_margin_ttm → frontend key: operating_margin
          operating_margin: num(
            metrics["operating_margin"] ?? metrics["operating_margin_ttm"] ?? row["operating_margin"],
          ),
          // Backend key: quarterly_revenue_growth_yoy → frontend key: revenue_growth_yoy
          revenue_growth_yoy: num(
            metrics["revenue_growth_yoy"] ??
            metrics["quarterly_revenue_growth_yoy"] ??
            row["revenue_growth_yoy"],
          ),
          // ── IB-L3: computed OHLCV-derived returns (period_type=SNAPSHOT) ─────
          // Wave-2 (2026-06-10): the Wave-1 backend now projects the two 52W
          // distance fields in the key-metrics set on EVERY view (default +
          // filtered; live coverage 195/200), so the 52W RANGE column renders
          // without an explicit filter. The return_1m/3m/6m/ytd/1y/3y fields
          // are still NOT in key_metrics — they only appear on a row when an
          // explicit filter references that metric (live-verified: a
          // return_1m filter surfaces return_1m and nothing else). The
          // opt-in RTN columns therefore show "—" on unfiltered views —
          // truthful, and documented as a remaining backend gap.
          dist_from_52w_high_pct: num(
            metrics["dist_from_52w_high_pct"] ?? row["dist_from_52w_high_pct"],
          ),
          dist_from_52w_low_pct: num(
            metrics["dist_from_52w_low_pct"] ?? row["dist_from_52w_low_pct"],
          ),
          return_1m: num(metrics["return_1m"] ?? row["return_1m"]),
          return_3m: num(metrics["return_3m"] ?? row["return_3m"]),
          return_6m: num(metrics["return_6m"] ?? row["return_6m"]),
          return_ytd: num(metrics["return_ytd"] ?? row["return_ytd"]),
          return_1y: num(metrics["return_1y"] ?? row["return_1y"]),
          return_3y: num(metrics["return_3y"] ?? row["return_3y"]),
          // ── IB-L4: snapshot fields (LEFT JOINed on instrument_fundamentals_snapshot) ──
          // These come from the snap_fields_available projection in the backend.
          // They land in the metrics dict as e.g. metrics["analyst_target_price"],
          // metrics["institutional_ownership_pct"], etc. — no key rename needed.
          analyst_target_price: num(
            metrics["analyst_target_price"] ?? row["analyst_target_price"],
          ),
          analyst_consensus_rating: num(
            metrics["analyst_consensus_rating"] ?? row["analyst_consensus_rating"],
          ),
          insider_net_buy_90d: num(
            metrics["insider_net_buy_90d"] ?? row["insider_net_buy_90d"],
          ),
          institutional_ownership_pct: num(
            metrics["institutional_ownership_pct"] ?? row["institutional_ownership_pct"],
          ),
          short_percent: num(metrics["short_percent"] ?? row["short_percent"]),
          // ── IB-L5: intelligence rollup (L-5b worker, nightly 04:00 UTC) ──────
          // Integer / float / bool fields from instrument_fundamentals_snapshot.
          // WHY num() for booleans: has_active_alert / has_ai_brief are booleans
          // in DB but the ScreenerResult type is typed as boolean | null. We keep
          // num() for consistency — the column renderers don't use these directly,
          // they are filter-only fields per the design spec (IB-L5 §5).
          news_count_7d: num(metrics["news_count_7d"] ?? row["news_count_7d"]),
          llm_relevance_7d_max: num(
            metrics["llm_relevance_7d_max"] ?? row["llm_relevance_7d_max"],
          ),
          display_relevance_7d_weighted: num(
            metrics["display_relevance_7d_weighted"] ?? row["display_relevance_7d_weighted"],
          ),
          recent_contradiction_count: num(
            metrics["recent_contradiction_count"] ?? row["recent_contradiction_count"],
          ),
          // ── IB-L5 stale-data indicator (T-IB5-04) ───────────────────────────
          // WHY propagated even though no renderer reads it: the screener page
          // reads `intelligence_rollup_synced_at` off the first row to drive the
          // IntelligenceFilterGroup "N h stale" pill. Without forwarding it here
          // the field would be dropped by the flatten step (the spread does NOT
          // include unmapped keys), so the pill could never fire. Defensive:
          // resolves to a string when the backend (sibling agent's work) ships
          // it, otherwise stays undefined and the pill no-ops.
          intelligence_rollup_synced_at:
            (row["intelligence_rollup_synced_at"] as string | undefined) ??
            (metrics["intelligence_rollup_synced_at"] as string | undefined) ??
            null,
          // WHY ScreenerRowEnriched (not plain ScreenerResult): the three
          // Wave-2 fields above (volume, high_52w, low_52w) are typed on the
          // local extension interface — the cast documents that every
          // flattened row carries them (possibly null).
        } as unknown as ScreenerRowEnriched;
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

    /**
     * nlTranslate — natural-language → screener filters (PLAN-0091).
     *
     * WHY THIS EXISTS: the backend POST /v1/screener/nl-translate is shipped but
     * was under-surfaced. It turns a plain-English prompt ("large cap tech with
     * P/E under 20 and a dividend") into structured ScreenerFilter[] the existing
     * screen endpoint already understands. This is a genuine EQS-beating
     * affordance — Bloomberg has no NL screen builder.
     *
     * WHY a DEFENSIVE response parse (not a strict typed contract): the exact
     * response envelope is owned by the backend agent and may evolve. We tolerate
     * the two plausible shapes — a top-level `filters` array, or one nested under
     * `result` — and surface the raw `ScreenerFilter[]` for the caller to apply.
     * `explanation` (if present) lets the UI echo back how it interpreted the
     * query. Anything unparseable yields an empty filter list (the caller treats
     * that as "no constraints understood" rather than crashing).
     */
    async nlTranslate(
      query: string,
    ): Promise<{ filters: ScreenerFilter[]; explanation?: string }> {
      const raw = await apiFetch<
        {
          filters?: ScreenerFilter[];
          result?: { filters?: ScreenerFilter[] };
          explanation?: string;
        } & Record<string, unknown>
      >("/v1/screener/nl-translate", {
        method: "POST",
        body: { query },
        token: t,
      });
      const filters = raw.filters ?? raw.result?.filters ?? [];
      const explanation =
        typeof raw.explanation === "string" ? raw.explanation : undefined;
      return { filters, explanation };
    },
  };
}
