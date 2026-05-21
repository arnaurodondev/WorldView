/**
 * components/instrument/quote/metrics/MetricRow.tsx — single row in MetricsTable
 *
 * WHY: PRD-0088 §6.7.2 specifies a vertical stack of single-line rows
 * (label left, value right) in the right-rail Statistics table. Centralising
 * this row primitive guarantees consistent height, padding, and
 * MetricLabel/MetricValue pairing across all metric rows.
 *
 * W5-T-08 — Δ8 height change:
 * Previously `h-[22px]` was hardcoded here. That prevented the F1
 * `data-table-grid` design-system from controlling row height via `--row-h`.
 * Now MetricRow reads the CSS variable `--row-h` from the nearest ancestor
 * `[data-table-grid]` container; if no ancestor sets it, the fallback is
 * 22px (matching the old behaviour). This means wrapping MetricsTable in
 * `<div data-table-grid>` will shrink rows to 20px automatically per Δ4,
 * and `<div data-table-grid="dense">` gives 18px for the mini-lists.
 *
 * WHY ReactNode value: a few rows host visualisations rather than plain
 * numbers; MetricValue handles null → "—" centrally.
 *
 * WHO USES IT: MetricsTable (T-B-03). DESIGN REF: PLAN-0090 §T-B-02.
 */

// WHY no "use client": pure display — props only, no hooks or browser APIs.

// PRD-0089 F1: primitives promoted from instrument/shared/ to a top-level
// `components/primitives/` folder so cross-page agents (F2+) can reuse them.
import { MetricLabel } from "@/components/primitives/MetricLabel";
import { MetricValue } from "@/components/primitives/MetricValue";

// WHY export the colour enum here: MetricsTable threshold-colours each cell
// (e.g. "PE > 50 → red"); centralising the union keeps callers exhaustive.
export type MetricValueColor = "positive" | "negative" | "amber" | "muted" | "default";

interface MetricRowProps {
  /** Left-aligned label (rendered uppercase by MetricLabel). */
  label: string;
  /** Right-aligned value. null/undefined → MetricValue renders "—". */
  value?: React.ReactNode;
  /** Optional colour tag for the value (threshold-driven red/amber). */
  color?: MetricValueColor;
  /** Optional extra className applied to the row wrapper. */
  className?: string;
}

export function MetricRow({ label, value, color = "default", className = "" }: MetricRowProps) {
  return (
    // WHY h-[var(--row-h,22px)] (Δ8 — W5-T-08):
    //   `--row-h` is set by the nearest [data-table-grid] ancestor (20px default,
    //   18px for "dense" variant). The `22px` fallback preserves the original
    //   height when MetricRow is used outside a data-table-grid context.
    //   Using the CSS variable (not a Tailwind class) lets the design system
    //   control density from one place without prop-drilling.
    <div className={`flex items-center justify-between h-[var(--row-h,22px)] px-3 ${className}`}>
      <MetricLabel>{label}</MetricLabel>
      {/* WHY value ?? null (not ?? "—"): MetricValue is the single source of
          truth for the muted em-dash on null/undefined children. */}
      <MetricValue color={color}>{value ?? null}</MetricValue>
    </div>
  );
}
