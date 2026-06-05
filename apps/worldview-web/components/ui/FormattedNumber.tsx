/**
 * components/ui/FormattedNumber.tsx — Universal numeric display primitive.
 *
 * WHY THIS EXISTS (DS-006, FR-10.6):
 * ADR-F-15 requires ALL numeric values to use `font-mono tabular-nums`.
 * Before this component, 20+ inline renders forgot to apply those classes,
 * causing mixed sans/mono numerals inside the same column — a typography
 * error visible at the institutional density we target.
 *
 * USAGE:
 *   <FormattedNumber value={price} format="currency" />
 *   <FormattedNumber value={change} format="percent" color="positive" />
 *   <FormattedNumber value={null} format="volume" />  → renders "—"
 *
 * WHY import from lib/format (not inline Intl):
 * lib/format.ts is the canonical formatter that handles edge cases
 * (null/NaN, negative compact, sub-$1 crypto, etc.). Inlining even a
 * subset of that logic here would create divergence. Single source of truth.
 */

import type { ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";
import {
  formatCompactCurrency,
  formatPercent,
  formatPrice,
  formatRatio,
  formatVolume,
} from "@/lib/format";

// ── Prop types ────────────────────────────────────────────────────────────────

type FormatKind = "currency" | "percent" | "ratio" | "volume" | "compact" | "integer";

type ColorVariant = "positive" | "negative" | "amber" | "muted" | "default";

export interface FormattedNumberProps extends ComponentPropsWithoutRef<"span"> {
  /** Numeric value to render. null/undefined renders an em-dash placeholder. */
  value: number | null | undefined;
  /**
   * How to format the number:
   *   currency  — $1,234.56 (uses formatPrice / formatCompactCurrency for large values)
   *   percent   — +2.34% (directional sign prefix)
   *   ratio     — 12.34x (P/E, P/B multiples)
   *   volume    — 1.23M (abbreviated, no currency symbol)
   *   compact   — 1.23B (abbreviated, no currency symbol, alias for volume)
   *   integer   — 1,234 (locale-grouped whole number, no decimals)
   */
  format: FormatKind;
  /**
   * Optional decimal override passed to formatPercent/formatRatio.
   * Not applicable for currency/volume/compact (those have fixed logic).
   */
  decimals?: number;
  /**
   * Semantic color variant. Default inherits from parent context.
   * positive  → text-positive  (institutional green, ADR-F-15)
   * negative  → text-negative  (institutional red)
   * amber     → text-warning (warning / caution)
   * muted     → text-muted-foreground (secondary label)
   * default   → inherit (no color override)
   */
  color?: ColorVariant;
}

// ── Color class map ───────────────────────────────────────────────────────────

const COLOR_CLASSES: Record<ColorVariant, string> = {
  positive: "text-positive",
  negative: "text-negative",
  amber: "text-warning",
  muted: "text-muted-foreground",
  default: "",
};

// ── Formatter dispatch ────────────────────────────────────────────────────────

function applyFormat(value: number, format: FormatKind, decimals?: number): string {
  switch (format) {
    case "currency":
      // Large values (≥ 1M) use compact; smaller values use full price.
      // formatPrice handles the boundary internally for values < 1M.
      return Math.abs(value) >= 1_000_000
        ? formatCompactCurrency(value, "USD")
        : formatPrice(value, "USD");
    case "percent":
      return formatPercent(value, decimals ?? 2);
    case "ratio":
      return formatRatio(value, "x");
    case "volume":
    case "compact":
      return formatVolume(value);
    case "integer":
      // Locale-grouped integer (no decimal places). Use en-US for consistency
      // with the rest of the codebase (formatPrice etc. all use en-US).
      return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(value);
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * FormattedNumber — renders a financial number with mandatory mono font.
 *
 * Always applies: font-mono tabular-nums slashed-zero (ADR-F-15).
 * Null/undefined renders "—" in text-muted-foreground/50 so missing values
 * are visually distinct from zero without breaking column alignment.
 */
export function FormattedNumber({
  value,
  format,
  decimals,
  color = "default",
  className,
  ...rest
}: FormattedNumberProps) {
  // Null/undefined: render an em-dash placeholder at reduced opacity so the
  // column keeps its spacing without implying the data is zero.
  if (value == null || !Number.isFinite(value)) {
    return (
      <span
        className={cn(
          "font-mono tabular-nums slashed-zero text-muted-foreground/50",
          className,
        )}
        aria-label="no data"
        {...rest}
      >
        —
      </span>
    );
  }

  const formatted = applyFormat(value, format, decimals);

  return (
    <span
      className={cn(
        // ADR-F-15: mandatory mono + tabular-nums on ALL numeric renders.
        // slashed-zero: IBM Plex Mono OpenType feature (disambiguates 0 / O).
        "font-mono tabular-nums slashed-zero",
        COLOR_CLASSES[color],
        className,
      )}
      {...rest}
    >
      {formatted}
    </span>
  );
}
