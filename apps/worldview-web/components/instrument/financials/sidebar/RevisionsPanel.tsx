/**
 * sidebar/RevisionsPanel.tsx — EPS revision history panel (STUB)
 *
 * WHY THIS EXISTS (T-19): Estimate revisions are a leading indicator — a wave
 * of upward estimate revisions before earnings signals momentum; downward
 * revisions warn of multiple compression. This panel is a stub: the data
 * source (EODHD analyst revisions section) exists but was not scoped for W3.
 * The stub reserves the visual slot and exposes the panel to QA.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: Pending — will use EODHD analyst-consensus revisions in a
 *   future wave. No props needed for the stub.
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

export function RevisionsPanel() {
  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border">
      {/* Round-3 item 2: label-level accent bar (border-l-2 border-l-primary)
          — the Round-1 section-start marker, applied uniformly. Label-level
          (not a full bg band) because these padded sidebar panels have no
          dedicated header row to tint. */}
      <span className="border-l-2 border-l-primary pl-1.5 text-[9px] uppercase tracking-widest text-muted-foreground/70">
        ESTIMATE REVISIONS
      </span>

      {/* Placeholder rows — 3 rows matching the future layout density. */}
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[20px] flex items-center gap-2"
        >
          <span className="text-[10px] text-muted-foreground/30 font-mono">—</span>
          <span className="text-[10px] text-muted-foreground/30">—</span>
        </div>
      ))}

      <p className="text-[9px] text-muted-foreground/40 pt-1">
        Revisions history pending data source.
      </p>
    </div>
  );
}
