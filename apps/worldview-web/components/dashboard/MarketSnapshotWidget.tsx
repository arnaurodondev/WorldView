/**
 * components/dashboard/MarketSnapshotWidget.tsx — Market snapshot placeholder
 *
 * WHY THIS EXISTS: The dashboard morning routine starts with a macro scan of
 * futures and yield curve. ES, NQ, VIX and the 2Y/10Y yield spread tell traders
 * whether risk-on/risk-off positioning is shifting before the open.
 *
 * WHY PLACEHOLDER WITH —: Futures data (ES, NQ) and live yields require EODHD
 * macro/indices integration that is not yet implemented in the ingestion pipeline.
 * Showing — with a footer note keeps the widget structurally present in the
 * dashboard grid while communicating to the trader that data is pending, not broken.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-4)
 * DATA SOURCE: Placeholder — EODHD macro integration pending
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

// WHY no "use client": pure presentational, no hooks or browser APIs needed.

// ── Instrument rows ───────────────────────────────────────────────────────────

/** Static instruments shown in the market snapshot widget */
const SNAPSHOT_INSTRUMENTS = [
  { label: "ES (S&P Fut)", description: "S&P 500 E-mini Futures" },
  { label: "NQ (NDX Fut)", description: "Nasdaq-100 E-mini Futures" },
  { label: "VIX", description: "CBOE Volatility Index" },
  { label: "2Y Yield", description: "US 2-Year Treasury Yield" },
  { label: "10Y Yield", description: "US 10-Year Treasury Yield" },
  { label: "2Y/10Y", description: "Yield Curve Spread (10Y – 2Y)" },
] as const;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * MarketSnapshotWidget — 6 key macro instruments with placeholder values.
 * All instruments show — until EODHD macro endpoint is wired up.
 */
export function MarketSnapshotWidget() {
  return (
    // WHY flex flex-col h-full: fills the grid cell height so the widget
    // stretches to match adjacent SectorHeatmapWidget.
    // WHY bg-card: matches panel background token, distinct from bg-background grid gaps.
    <div className="flex h-full flex-col bg-card">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY h-6 border-b: universal panel header height from §0 Terminal Quality Rules */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET SNAPSHOT
        </span>
        {/* WHY no live-time badge: data is static placeholder */}
      </div>

      {/* ── Instrument rows ───────────────────────────────────────────────── */}
      {/* WHY divide-y divide-border/30: hairline separators between rows keep
          the terminal table density without heavy borders */}
      <div className="flex-1 divide-y divide-border/30 overflow-auto">
        {SNAPSHOT_INSTRUMENTS.map((instrument) => (
          <div
            key={instrument.label}
            // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
            className="flex h-[22px] items-center justify-between px-2"
            title={instrument.description}
          >
            {/* Instrument name — left-aligned, human-readable label */}
            <span className="text-[11px] text-muted-foreground">
              {instrument.label}
            </span>

            {/* Value — em dash placeholder per spec */}
            {/* WHY font-mono tabular-nums: financial numbers must be monospaced for
                column alignment and digit width consistency */}
            <span className="font-mono text-[11px] tabular-nums text-foreground">
              —
            </span>
          </div>
        ))}
      </div>

      {/* ── Footer note ───────────────────────────────────────────────────── */}
      {/* WHY footer note: communicates clearly that data is pending integration,
          not that the service is broken. Traders need to distinguish "unavailable"
          from "not yet built". */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <span className="text-[10px] text-muted-foreground/60">
          futures data — EODHD macro integration pending
        </span>
      </div>

    </div>
  );
}
