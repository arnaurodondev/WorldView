/**
 * components/instrument/quote/metrics/MetricGrid4Col.tsx
 * — Generic 4-column × N-row metric grid (W5-T-14)
 *
 * WHY THIS EXISTS:
 *   MetricsTable's original design stacked MetricRows in a single column
 *   (1 metric × 22px = 28 rows × 22px = 616px). At 1080p that's 57% of the
 *   viewport just for statistics. MetricGrid4Col halves that to 7 rows × 20px
 *   per block = 140px, matching Bloomberg/Finviz density (Δ37, Δ42).
 *
 * DESIGN DECISIONS:
 *   - `<div data-table-grid>` parent → 20px `--row-h` for MetricCell children.
 *   - 4 equal-width columns: `grid-cols-4`. Each cell is a `MetricCell`.
 *   - `text-[10px]` labels (F1 floor, Δ2). `text-[11px] font-mono tabular-nums` values.
 *   - No `rounded-*` (Δ3, F1 rounded=0).
 *   - Cell width = (rail − 16px padding) / 4 = 364 / 4 = 91px at xl (Δ34).
 *   - Optional `title` prop renders a 9px section-tag above the grid.
 *
 * WHO USES IT: MetricsTable.tsx (T-15) for VALUATION / MARGINS / LEV+YIELD blocks.
 *
 * LINE LIMIT: ≤ 90 LOC (plan).
 */

// WHY no "use client": pure display — props only, no browser APIs.

import { MetricCell } from "@/components/primitives/MetricCell";
import type { MetricValueColor } from "./MetricRow";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MetricGridCell {
  /** Short uppercase label (e.g. "MKT CAP"). ≤ 10 chars fits 4 cols. */
  label: string;
  /** Pre-formatted value string. null → MetricCell renders "—". */
  value: string | null | undefined;
  /** Optional semantic color for the value. */
  color?: MetricValueColor;
}

interface MetricGrid4ColProps {
  /** Optional section tag rendered in 9px above the grid. */
  title?: string;
  /** Flat list of cells. Length should be a multiple of 4 for even rows. */
  cells: MetricGridCell[];
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MetricGrid4Col({ title, cells }: MetricGrid4ColProps) {
  return (
    // WHY data-table-grid: F1 §16.3 opt-in — sets --row-h=20px for children.
    // Outer border-t is the Δ6 hairline group divider between right-rail blocks.
    <div data-table-grid className="border-t border-[hsl(var(--border-subtle))]">
      {/* Section tag: 9px uppercase label — the one place 9px is allowed (Δ2
          carve-out for section identifiers, not metric body labels). */}
      {title && (
        <div className="flex items-center h-[var(--row-h,20px)] px-3 border-b border-[hsl(var(--border-subtle))]">
          <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
            {title}
          </span>
        </div>
      )}

      {/* WHY grid-cols-4 (not flex): ensures all cells share exactly 25% width
          regardless of label + value length, preventing per-row width jitter. */}
      <div className="grid grid-cols-4">
        {cells.map((cell, idx) => (
          // WHY role="cell" (F1 §16.3): MetricCell itself also sets role="cell"
          // internally. The wrapping div adds the [role="row"] boundary every
          // 4 cells so F1 inner-border rules fire correctly. We set role on the
          // wrapping div and let MetricCell manage its own inner role.
          <div
            key={`${cell.label}-${idx}`}
            role="cell"
            className="min-w-0"
          >
            <MetricCell
              label={cell.label}
              value={cell.value ?? null}
              color={cell.color === "amber" ? "warning" : (cell.color ?? "default")}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
