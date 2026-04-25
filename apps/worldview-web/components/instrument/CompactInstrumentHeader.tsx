/**
 * components/instrument/CompactInstrumentHeader.tsx — 56px 2-row instrument header
 *
 * WHY THIS EXISTS: Replaces the old padded header + separate back-nav divs with a
 * compact 2-row (28px each) terminal-style header. Bloomberg terminals show ticker,
 * price, key stats, and description in a single horizontal band — never a tall card
 * with large whitespace. This header reclaims vertical space for the chart below.
 *
 * WHY 2 ROWS (not 1): Row 1 is identity + live price (what is it, what's the price).
 * Row 2 is contextual stats + description (why does it matter). Separating them
 * creates visual hierarchy without extra padding.
 *
 * WHY EXPANDABLE DESCRIPTION (row 3): Full descriptions can be 500+ chars. The
 * two-row header shows a truncated preview; analysts who need context click "Read more".
 * grid-template-rows animation is GPU-composited (no layout thrash vs max-height).
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (replaces old header divs)
 * DATA SOURCE: Props from CompanyOverview composite fetch (no independent fetch)
 * DESIGN REFERENCE: PRD-0031 §9 CompactInstrumentHeader, Terminal UI v3 Wave 5
 */

"use client";
// WHY "use client": uses useState for description expand/collapse toggle.

import { useState } from "react";
import { ChevronLeft } from "lucide-react";
import { LiveQuoteBadge } from "@/components/instrument/LiveQuoteBadge";
import { formatMarketCap, formatRatio } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface CompactInstrumentHeaderProps {
  ticker: string;
  name: string;
  exchange: string;
  sector: string | null;
  description: string | null;
  // Fundamentals for row 2 stats strip
  marketCap: number | null;
  peRatio: number | null;
  week52High: number | null;
  week52Low: number | null;
  // Live price (from quote via initialPrice from CompanyOverview)
  price: number | null;
  change: number | null;
  changePct: number | null;
  instrumentId: string;    // for LiveQuoteBadge
  onBack: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CompactInstrumentHeader({
  ticker,
  name,
  exchange,
  sector,
  description,
  marketCap,
  peRatio,
  week52High,
  week52Low,
  price,
  change,
  changePct,
  instrumentId,
  onBack,
}: CompactInstrumentHeaderProps) {
  // WHY useState for description expand: the "Read more" row is a smooth
  // grid-template-rows animation — needs React state to toggle the CSS variable.
  const [descExpanded, setDescExpanded] = useState(false);

  // Derived: format change for display
  const changeStr = change != null
    ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}`
    : null;
  const changePctStr = changePct != null
    ? `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`
    : null;
  const changeColorClass = (changePct ?? 0) >= 0 ? "text-positive" : "text-negative";

  return (
    // WHY border-b + bg-card + shrink-0: the header is chrome above the scrollable
    // content area. shrink-0 prevents it from being compressed by a tall chart.
    <header className="border-b border-border bg-card shrink-0">

      {/* ── Row 1: identity + live price (h-7 = 28px) ───────────────────── */}
      {/* WHY h-7 not h-8: terminal row budget — 28px is the standard "header row"
          in Bloomberg-style UIs. The data rows below are 22px (smaller). */}
      <div className="flex items-center h-7 px-2 gap-2 border-b border-border/50">

        {/* Back button — router.back() wired by parent via onBack prop */}
        <button
          onClick={onBack}
          className="shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Go back"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>

        {/* Ticker — monospace bold; Bloomberg always monospaces symbols */}
        <span className="font-mono text-[13px] font-semibold text-foreground shrink-0">
          {ticker}
        </span>

        {/* Exchange badge — subtle muted pill, no shadow, rounded-[2px] only */}
        <span className="rounded-[2px] bg-muted/40 px-1 font-mono text-[10px] text-muted-foreground shrink-0">
          {exchange}
        </span>

        {/* Sector — secondary context, fades into background */}
        {sector && (
          <span className="text-[10px] text-muted-foreground truncate min-w-0">
            {sector}
          </span>
        )}

        {/* Company name — truncates when screen is narrow */}
        <span className="text-[10px] text-muted-foreground/70 truncate min-w-0 hidden sm:block">
          {name}
        </span>

        {/* Right side: live price + change + badge */}
        {/* WHY ml-auto: pushes price to the far right, consistent with Bloomberg
            where the right side of the header is always the price block. */}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {/* Price — larger than change for visual hierarchy */}
          {price != null && (
            <span className="font-mono text-[14px] tabular-nums font-medium text-foreground">
              ${price.toFixed(2)}
            </span>
          )}

          {/* Absolute + percent change — colored green/red */}
          {changeStr && changePctStr && (
            <span className={`font-mono text-[11px] tabular-nums ${changeColorClass}`}>
              {changeStr} ({changePctStr})
            </span>
          )}

          {/* LiveQuoteBadge — shows freshness status (DELAYED/STALE badges) + polls for updates.
              WHY compact mode: in this dense header we only need the freshness badge,
              not the full price/timestamp block (price is already shown above). */}
          <LiveQuoteBadge instrumentId={instrumentId} initialPrice={price} />
        </div>
      </div>

      {/* ── Row 2: stats strip + description (h-7 = 28px) ──────────────── */}
      <div className="flex items-center h-7 px-2">

        {/* Left ~60%: key stats strip */}
        {/* WHY gap-0 (no gap between items): separators (│) provide visual space;
            Tailwind gap would add redundant spacing around the pipe chars. */}
        <div className="flex items-center gap-0 text-[10px] font-mono tabular-nums text-muted-foreground shrink-0 mr-auto">

          {/* Market Cap */}
          <span className="text-muted-foreground">MKT CAP</span>
          <span className="text-foreground ml-1">{formatMarketCap(marketCap)}</span>

          <span className="px-1.5 text-border" aria-hidden>│</span>

          {/* P/E Ratio — formatRatio adds "x" suffix */}
          <span className="text-muted-foreground">P/E</span>
          <span className="text-foreground ml-1">{formatRatio(peRatio)}</span>

          <span className="px-1.5 text-border" aria-hidden>│</span>

          {/* 52-Week Range */}
          <span className="text-muted-foreground">52W</span>
          <span className="text-foreground ml-1">
            {week52Low != null && week52High != null
              ? `${week52Low.toFixed(2)}–${week52High.toFixed(2)}`
              : "—"}
          </span>

          <span className="px-1.5 text-border" aria-hidden>│</span>

          {/* Volume — not available in props; show N/A */}
          <span className="text-muted-foreground">VOL</span>
          <span className="text-foreground ml-1">N/A</span>
        </div>

        {/* Right ~40%: truncated description + "Read more" button */}
        {description && (
          <div className="flex items-center gap-1 min-w-0 max-w-[40%]">
            <span className="text-[11px] text-muted-foreground truncate">
              {description}
            </span>
            <button
              onClick={() => setDescExpanded((v) => !v)}
              className="text-[10px] text-primary hover:underline shrink-0"
              aria-label={descExpanded ? "Collapse description" : "Read full description"}
            >
              {descExpanded ? "Close ▴" : "Read more →"}
            </button>
          </div>
        )}
      </div>

      {/* ── Row 3: expanded description (grid-rows animation) ────────────── */}
      {/* WHY grid-template-rows 0fr→1fr (not max-height):
          The grid-template-rows trick is GPU-composited — it doesn't trigger
          a layout pass on each animation frame. max-height approach requires
          a hardcoded max-height value and lays out the content at max-height. */}
      {description && (
        <div
          className="grid transition-[grid-template-rows] duration-150 ease-out"
          style={{ gridTemplateRows: descExpanded ? "1fr" : "0fr" }}
        >
          <div className="overflow-hidden">
            <div className="flex items-start justify-between px-2 pb-2 pt-1">
              <p className="text-[11px] text-muted-foreground leading-relaxed max-w-prose">
                {description}
              </p>
              <button
                onClick={() => setDescExpanded(false)}
                className="ml-4 shrink-0 text-[10px] text-muted-foreground hover:text-foreground"
              >
                ▴ Close
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
