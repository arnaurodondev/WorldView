/**
 * features/screener/lib/apply-client-filters.ts — Client-side screener filters
 *
 * WHY SEPARATE FILE: this is the only screener filter that runs in the browser
 * rather than the backend (the backend does not support full-text search on
 * ticker/name). Keeping it isolated from the page component lets us unit-test
 * the filter logic without setting up all the Next.js / TanStack Query context.
 *
 * TODO(server): once S3 exposes full-text search, move the `search` filter to
 * buildScreenerFilters and delete this file.
 */

import type { ScreenerResult } from "@/types/api";
import type { FilterState } from "./filter-state";

/**
 * applyClientFilters — filters that the backend cannot apply yet.
 *
 * For each technical / news control set in FilterState, drop rows that do not
 * satisfy the constraint. When the data field is missing on the row (most
 * common case today), we keep the row so partial-data instruments are not
 * accidentally hidden. Conservative behaviour matches Bloomberg's "soft" filters
 * where missing data means "uncertain" rather than "exclude".
 */
export function applyClientFilters(
  rows: ScreenerResult[],
  f: FilterState,
): ScreenerResult[] {
  let out = rows;

  // Free-text search on ticker / name — NOT supported by backend.
  // WHY null-safe: ScreenerResult.ticker and .name are nullable in the API
  // type (some instruments have no name yet). Without the ?? "" guard, a null
  // ticker would make .toLowerCase() throw and silently drop the filter result.
  if (f.search.trim()) {
    const q = f.search.trim().toLowerCase();
    out = out.filter((r) => {
      const t = (r.ticker ?? "").toLowerCase();
      const n = (r.name ?? "").toLowerCase();
      return t.includes(q) || n.includes(q);
    });
  }

  // Above 50d MA — TODO server: requires `current_price` and `ma_50` on response.
  // Today neither is consistently populated; we skip this filter when data missing.

  // RSI band — TODO server. No `rsi_14` field on response yet.

  // Volume vs 30d average — TODO server. Requires daily volume + avg_volume_30d.

  // Distance from 52W high / low — TODO server. Requires high_52w / low_52w.

  // News & signals — all TODO server (S6/S7). Inputs are accepted but not applied.

  return out;
}
