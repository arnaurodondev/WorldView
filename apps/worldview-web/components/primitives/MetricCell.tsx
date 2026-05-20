/**
 * components/primitives/MetricCell.tsx — single label+value pair inside a row
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — every metric cell (price, volume,
 * %, AUM, …) renders the same way: small uppercase label on top, mono
 * tabular-nums value below, optional semantic color. Centralising prevents
 * each page reinventing the typography pair.
 * WHO USES IT: Dashboard top-stats strip, Quote tab MetricRow, Portfolio
 * holdings rows, Watchlist, Screener compact columns.
 * DATA SOURCE: Pure presentational primitive. Caller passes pre-formatted
 *   strings via formatPrice / formatPercent / formatCompactCurrency.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (MetricCell row).
 */

import type { ReactNode } from "react";

type MetricColor = "positive" | "negative" | "warning" | "muted" | "default";

interface MetricCellProps {
  /** Uppercase label (e.g. "MARKET CAP"). Truncates if too long. */
  readonly label: string;
  /** Formatted value string. null/undefined renders the em-dash placeholder. */
  readonly value: ReactNode;
  /** Semantic color intent for the value. */
  readonly color?: MetricColor;
  /** Cell content alignment — finance convention: numbers right, text left. */
  readonly align?: "left" | "right";
  /** Use IBM Plex Mono + tabular-nums on the value. Defaults to true. */
  readonly mono?: boolean;
}

// One audit point for color choices: positive=gain, negative=loss,
// warning=caution amber, muted=de-emphasised, default=body text.
const COLOR_CLASS: Record<MetricColor, string> = {
  positive: "text-positive",
  negative: "text-negative",
  warning: "text-warning",
  muted: "text-muted-foreground",
  default: "text-foreground",
};

export function MetricCell({
  label,
  value,
  color = "default",
  align = "right",
  mono = true,
}: MetricCellProps): ReactNode {
  const alignClass = align === "right" ? "items-end text-right" : "items-start text-left";
  const monoClass = mono ? "font-mono tabular-nums" : "";
  // Finance UX convention: "—" for absent data (not loading). Muted-foreground
  // at 50% alpha keeps the dash from drawing the eye away from real values.
  const isEmpty = value === null || value === undefined;
  return (
    <div role="cell" className={`flex flex-col justify-center px-[var(--cell-px,8px)] ${alignClass}`}>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground truncate">{label}</span>
      {isEmpty ? (
        <span className={`text-[11px] ${monoClass} text-muted-foreground/50`}>—</span>
      ) : (
        <span className={`text-[11px] ${monoClass} ${COLOR_CLASS[color]}`}>{value}</span>
      )}
    </div>
  );
}
