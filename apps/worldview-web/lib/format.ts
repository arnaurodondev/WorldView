/**
 * lib/format.ts — Canonical financial formatters
 *
 * WHY THIS EXISTS: Before this module, four parallel implementations of
 * "compact $X.YB / X.YM" lived in:
 *   - lib/utils.ts (`formatPriceCompact`, `formatVolume`, `formatMarketCap`)
 *   - components/screener/ScreenerTable.tsx (`formatCap`)
 *   - components/instrument/InstrumentAskAiButton.tsx (inline ternary)
 *   - components/instrument/OwnershipSnapshotPanel.tsx (local helper)
 *
 * They disagreed on:
 *   - decimal places (1 vs 2 vs `toPrecision(3)`)
 *   - rounding behaviour for negative values (some used `>= 1e9`, ignoring negatives)
 *   - whether to prefix `$`
 *   - whether to handle `null` / `undefined` / `NaN`
 *
 * This module is the single source of truth. Callers pick a function by INTENT
 * (price vs market cap vs volume) and the formatter handles edge cases.
 *
 * MULTI-CURRENCY: `formatCompactCurrency(value, "EUR")` renders `€2.4B` not
 * `$2.4B`. The default is "USD" for backward compatibility with the old
 * `formatPriceCompact` callers.
 *
 * BASIS POINTS: `formatBasisPoints(0.0023)` → `"+23 bps"`. Used in fixed-income
 * spreads, fee disclosures, and yield-curve deltas.
 *
 * MIGRATION: lib/utils.ts now re-exports the canonical names so existing call
 * sites keep working. New code should import from `@/lib/format`.
 */

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * pickCompactStep — decide which SI suffix and divisor to apply.
 *
 * WHY a shared helper: every variant of the compact formatter (volume, price,
 * market cap, revenue) walked the same magnitude ladder. Centralising it
 * guarantees they all classify a given number identically — so a $1.2B market
 * cap and 1.2B volume use the same divisor and the same B-suffix.
 */
type CompactStep = { divisor: number; suffix: "T" | "B" | "M" | "K" | "" };

function pickCompactStep(absValue: number): CompactStep {
  if (absValue >= 1e12) return { divisor: 1e12, suffix: "T" };
  if (absValue >= 1e9) return { divisor: 1e9, suffix: "B" };
  if (absValue >= 1e6) return { divisor: 1e6, suffix: "M" };
  if (absValue >= 1e3) return { divisor: 1e3, suffix: "K" };
  return { divisor: 1, suffix: "" };
}

/**
 * adaptiveDecimals — Bloomberg-style decimal-place rule for compact numbers.
 *
 * WHY OPT-IN (not the default): the legacy formatters (formatVolume,
 * formatMarketCap) used a flat 2 decimals for every magnitude — many tests
 * and visual snapshots assume that. New surfaces that want denser numbers
 * pass `{ adaptive: true }`:
 *   - scaled value < 10  → 2 decimals (e.g. 2.34B)
 *   - scaled value < 100 → 1 decimal (e.g. 23.4B)
 *   - scaled value ≥ 100 → 0 decimals (e.g. 456B)
 *
 * FX-friendly for JPY/KRW pairs whose scaled values land in the hundreds
 * (¥123T = 123 trillion yen) — adaptive mode drops decimal noise.
 */
function adaptiveDecimals(scaledAbs: number, maxDecimals = 2): number {
  if (scaledAbs >= 100) return 0;
  if (scaledAbs >= 10) return Math.min(1, maxDecimals);
  return maxDecimals;
}

// ── Currency symbol map ──────────────────────────────────────────────────────

// WHY a small inline map (not Intl.NumberFormat for symbol lookup):
// Intl.NumberFormat would return localised symbols ("US$", "CA$") in some
// locales which Bloomberg-style tables don't use. We pick the unambiguous
// symbol for institutional finance UIs.
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CHF: "CHF ",
  CAD: "C$",
  AUD: "A$",
  CNY: "¥",
  HKD: "HK$",
  KRW: "₩",
  // Crypto — uppercase ticker with trailing space, e.g. "BTC 0.034".
  BTC: "₿",
  ETH: "Ξ",
};

function symbolFor(currency: string): string {
  return CURRENCY_SYMBOLS[currency.toUpperCase()] ?? `${currency.toUpperCase()} `;
}

// ── Public API ───────────────────────────────────────────────────────────────

const DASH = "—";

interface CompactOptions {
  /**
   * adaptive — when true, reduces decimal places as the scaled value grows.
   * See {@link adaptiveDecimals}. Default false (fixed 2 decimals) for
   * backward compatibility with the legacy formatVolume/formatMarketCap.
   */
  adaptive?: boolean;
  /** maxDecimals — upper bound on decimal places. Default 2. */
  maxDecimals?: number;
}

/**
 * formatCompact — abbreviated number with SI suffix, NO currency prefix.
 *
 * Examples (default — fixed 2 decimals, matches legacy):
 *   formatCompact(1234567)       → "1.23M"
 *   formatCompact(2_450_000_000) → "2.45B"
 *   formatCompact(-2_450_000)    → "-2.45M"
 *   formatCompact(null)          → "—"
 *   formatCompact(5432)          → "5K"      // sub-decimal rounded down
 *
 * Examples (adaptive):
 *   formatCompact(987_654_321, { adaptive: true }) → "988M"
 *   formatCompact(23_456_789,  { adaptive: true }) → "23.5M"
 */
export function formatCompact(
  value: number | null | undefined,
  options: CompactOptions = {},
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const abs = Math.abs(value);
  const { divisor, suffix } = pickCompactStep(abs);
  const scaled = value / divisor;
  const max = options.maxDecimals ?? 2;
  const decimals = options.adaptive
    ? adaptiveDecimals(Math.abs(scaled), max)
    : // Legacy compatibility: K-suffix uses 0 decimals, M/B/T use 2.
      // This matches the pre-consolidation behaviour of formatVolume.
      suffix === "K" || suffix === ""
      ? 0
      : max;
  return `${scaled.toFixed(decimals)}${suffix}`;
}

/**
 * formatCompactCurrency — compact number with a currency symbol.
 *
 * Examples:
 *   formatCompactCurrency(2_450_000_000)         → "$2.45B"
 *   formatCompactCurrency(2_450_000_000, "EUR")  → "€2.45B"
 *   formatCompactCurrency(123_000_000, "JPY")    → "¥123.00M"  // legacy fixed-decimals
 *   formatCompactCurrency(0.0234, "BTC")         → "₿0.0234"   // small → no suffix
 *
 * Below 1000 → renders as a regular currency price using locale grouping
 * (e.g. "$4,892.11"). Matches the legacy formatPriceCompact contract.
 */
export function formatCompactCurrency(
  value: number | null | undefined,
  currency = "USD",
  options: CompactOptions = {},
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const symbol = symbolFor(currency);
  const abs = Math.abs(value);

  // Sub-1 → high-precision rendering (BTC/ETH amounts). 4 decimals strikes a
  // balance between accuracy and column width.
  if (abs > 0 && abs < 1) {
    return `${value < 0 ? "-" : ""}${symbol}${Math.abs(value).toFixed(4)}`;
  }

  // 1 ≤ |x| < 1M → render as a full price with locale grouping. The legacy
  // formatPriceCompact only switched to compact at the M boundary; tests
  // assert "$4,892.11" for sub-million values.
  if (abs < 1_000_000) {
    return formatPrice(value, currency);
  }

  const { divisor, suffix } = pickCompactStep(abs);
  const scaled = value / divisor;
  const max = options.maxDecimals ?? 2;
  const decimals = options.adaptive
    ? adaptiveDecimals(Math.abs(scaled), max)
    : max;
  // Sign goes BEFORE the currency symbol so "-$2.45B" reads correctly.
  const sign = value < 0 ? "-" : "";
  return `${sign}${symbol}${Math.abs(scaled).toFixed(decimals)}${suffix}`;
}

/**
 * formatPrice — full-precision price with locale-style thousands grouping.
 *
 * Always 2 decimals for non-crypto. Examples:
 *   formatPrice(182.34)  → "$182.34"
 *   formatPrice(4892.11) → "$4,892.11"
 *   formatPrice(-25.5)   → "-$25.50"
 *
 * WHY Intl.NumberFormat for non-Intl-symbol currencies: For ISO codes that
 * Intl recognises ("USD", "EUR", ...) we let Intl.NumberFormat handle
 * grouping AND the symbol — it produces canonical output ("$4,892.11",
 * "€4.892,11" depending on locale). For codes Intl doesn't render the way
 * we want (BTC, ETH, the made-up "C$"/"A$" we encode), we fall back to
 * symbol + grouped digits assembled by hand.
 */
export function formatPrice(
  value: number | null | undefined,
  currency = "USD",
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const code = currency.toUpperCase();

  // Try Intl first for ISO-recognised codes (USD/EUR/GBP/JPY/CHF/CAD/AUD/CNY/HKD/KRW).
  if (CURRENCY_SYMBOLS[code] && code !== "BTC" && code !== "ETH") {
    try {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: code,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
    } catch {
      // Some test environments / Node versions reject unusual codes — fall through.
    }
  }

  // Fallback: hand-assembled grouped digits with our symbol map.
  const grouped = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  return `${value < 0 ? "-" : ""}${symbolFor(code)}${grouped}`;
}

/**
 * formatPercent — directional percentage with sign prefix.
 *
 * Examples:
 *   formatPercent(0.0234)  → "+2.34%"
 *   formatPercent(-0.0112) → "-1.12%"
 *
 * WHY sign prefix: traders scan rows by sign before color. Even with
 * red/green coding, the explicit "+" / "-" makes the row keyboard-readable
 * for screen readers.
 */
export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const sign = value >= 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(decimals)}%`;
}

/**
 * formatPercentUnsigned — non-directional percentage (allocation, weight).
 *
 * For values where a leading "+" would be a category error (a 100% allocation
 * is not a "+100% gain").
 */
export function formatPercentUnsigned(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * formatBasisPoints — render a fractional change as basis points.
 *
 * 1 basis point = 0.01%. Used in fixed-income spreads, yield-curve deltas,
 * and fee disclosures where percentages are too coarse.
 *
 * Examples:
 *   formatBasisPoints(0.0023)  → "+23 bps"
 *   formatBasisPoints(-0.0012) → "-12 bps"
 *   formatBasisPoints(0.00005) → "+0.5 bps"  // sub-bp shown to 1 decimal
 */
export function formatBasisPoints(
  value: number | null | undefined,
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const bps = value * 10_000;
  const sign = bps >= 0 ? "+" : "";
  // Sub-bp values get one decimal so a 0.5 bps spread is visible.
  const decimals = Math.abs(bps) < 10 ? 1 : 0;
  // Round whole-bps to integers (avoid "+23.0 bps").
  const formatted = bps.toFixed(decimals);
  return `${sign}${formatted} bps`;
}

/**
 * formatRatio — multiplier (PE, P/B, P/S).
 */
export function formatRatio(
  value: number | null | undefined,
  suffix = "x",
): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  return `${value.toFixed(2)}${suffix}`;
}

// ── Backwards-compatible re-export aliases ────────────────────────────────────
//
// WHY: lib/utils.ts had `formatVolume` (no $ prefix) and `formatMarketCap`
// ($ prefix). Both reduce to formatCompact / formatCompactCurrency. Re-exports
// keep the migration mechanical: lib/utils.ts forwards to these.

export const formatVolume = (v: number | null | undefined): string =>
  formatCompact(v);

export const formatMarketCap = (v: number | null | undefined): string =>
  formatCompactCurrency(v, "USD");

export const formatPriceCompact = (v: number | null | undefined): string =>
  formatCompactCurrency(v, "USD");
