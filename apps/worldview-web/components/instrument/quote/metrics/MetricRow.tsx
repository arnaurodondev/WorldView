/**
 * components/instrument/quote/metrics/MetricRow.tsx — single 22px row in MetricsTable
 *
 * WHY: PRD-0088 §6.7.2 specifies a vertical stack of single-line rows
 * (label left, value right) in the right-rail Statistics table. Centralising
 * this row primitive guarantees consistent 22px height, padding, and
 * MetricLabel/MetricValue pairing across all 26 metric rows so the table
 * reads like a tightly-packed Bloomberg statistics panel.
 *
 * WHY h-[22px]: PRD-0088 §0.1 data density tier — the whole instrument page
 * is on a 22px row rhythm; hardcoding here prevents drift in MetricsTable.
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
    // WHY justify-between: pushes label left, value right within px-3 gutter.
    <div className={`flex items-center justify-between h-[22px] px-3 ${className}`}>
      <MetricLabel>{label}</MetricLabel>
      {/* WHY value ?? null (not ?? "—"): MetricValue is the single source of
          truth for the muted em-dash on null/undefined children. */}
      <MetricValue color={color}>{value ?? null}</MetricValue>
    </div>
  );
}
