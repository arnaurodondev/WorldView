/**
 * sidebar/TargetsByAnalystPanel.tsx — Per-firm analyst targets panel (STUB)
 *
 * WHY THIS EXISTS (T-20): Per-firm analyst targets (GS: $210 BUY, MS: $198 HOLD)
 * give context that the aggregated consensus target obscures — knowing which
 * institutions are the bulls vs bears matters for institutional flow analysis.
 * This panel is a stub: a per-firm target API is not yet available in EODHD's
 * free/standard tier. The stub reserves the visual slot for future work.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: Pending — no per-firm target data source identified. Will be
 *   added when a suitable provider is integrated.
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

export function TargetsByAnalystPanel() {
  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
        TARGETS BY ANALYST
      </span>

      <p className="text-[9px] text-muted-foreground/40">
        Per-firm targets pending data source.
      </p>
    </div>
  );
}
