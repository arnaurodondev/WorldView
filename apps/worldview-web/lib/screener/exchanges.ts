/**
 * lib/screener/exchanges.ts — Static exchange-code option list
 *
 * WHY THIS EXISTS: PRD-0089 Wave I-B Block IB-L1 T-IB-02 needs a
 * multi-select Exchange combobox. Wave L-1 (commit 3541ad86) registers
 * the column in `screen_field_metadata` with `field_type="text"` — the
 * seed does NOT enumerate values, so we ship a static fallback list per
 * plan §6.1 ("static fallback if the allowlist hook is not wired").
 *
 * WHY this set: every code corresponds to an exchange that the EODHD
 * ingestion universe touches today. Covers the major US/Europe/APAC
 * venues plus the most-traded emerging-market exchanges. The combobox
 * supports type-ahead, so a 15-entry list is plenty to start; a future
 * Wave L-x flip will replace this with a hook against the live
 * `instruments.exchange` distinct values.
 */

export const COMMON_EXCHANGES: readonly string[] = Object.freeze([
  "NYSE",
  "NASDAQ",
  "AMEX",
  "TSX",
  "TSXV",
  "LSE",
  "FRA",
  "PAR",
  "AMS",
  "SWX",
  "MIL",
  "MAD",
  "JPX",
  "HKEX",
  "SSE",
  "SZSE",
  "TWSE",
  "KRX",
  "SGX",
  "ASX",
  "NSE",
  "BSE",
  "B3",
]);
