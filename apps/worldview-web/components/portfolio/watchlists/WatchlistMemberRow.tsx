/**
 * components/portfolio/watchlists/WatchlistMemberRow.tsx — Single instrument row in a watchlist table
 *
 * WHY EXTRACTED: WatchlistMemberRow was an inner function inside WatchlistsTabPanel.tsx.
 * Moving it to its own file keeps each file under 400 lines and makes the row
 * independently testable without importing the full panel.
 *
 * WHY delete button on hover only: showing a delete button on every row adds visual
 * noise. Revealing it on hover follows the Bloomberg convention: destructive actions
 * are discoverable but not prominent during the primary read workflow.
 *
 * WHO USES IT: WatchlistTable (via WatchlistsTabPanel) — never directly by pages.
 */

"use client";
// WHY "use client": uses useState + useEffect for the pending-resolution timeout badge.

import { useState, useEffect } from "react";
import { ExternalLink, Loader2, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
// R3 polish: shared signed-dollar formatter (R1 convention — "+" only for
// strictly-positive values; zero stays unsigned). Replaces the local
// `change >= 0 ? "+" : ""` which wrongly rendered "+$0.00" on a flat day.
import { signedPrice } from "@/components/portfolio/PortfolioKPIStrip";
// 2026-06-10 density pass: shared 40×16 sparkline primitive (one rendering
// for watchlist/holdings/screener rows — PRD-0089 F1 §3.2).
import { Sparkline } from "@/components/primitives/Sparkline";
import type { WatchlistMember } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WatchlistMemberRowProps {
  member: WatchlistMember;
  /** Live quote — volume optional (nullable on the dev feed → "—"). */
  quote?: { price: number; change: number; change_pct: number; volume?: number | null };
  /** 5-day closes for the SPARK cell. undefined → dotted no-data line. */
  sparkline?: number[];
  onRowClick: (entityId: string) => void;
  onDelete: (entityId: string) => void;
  isDeleting: boolean;
}

// ── Volume formatter ──────────────────────────────────────────────────────────
// WHY compact notation ("1.2M", "847K"): raw share counts overflow an 11px
// cell and the magnitude is what a trader scans for, not the exact figure.
// WHY local (not lib/utils): formatPriceCompact is currency-specific; volume
// is a bare count. Kept here until a second consumer needs it.
const VOLUME_FMT = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
function formatVolume(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return VOLUME_FMT.format(v);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistMemberRow({
  member,
  quote,
  sparkline,
  onRowClick,
  onDelete,
  isDeleting,
}: WatchlistMemberRowProps) {
  // F-P-027 (PLAN-0051 W6): resolution badge timeout.
  // When SnapTrade reports an instrument we haven't yet ingested, the
  // backend marks the watchlist member with ``resolution=pending`` and
  // a background worker resolves it on the next sync (~30s). If the
  // resolver stalls (worker down, source 404) the badge would otherwise
  // stay "resolving…" forever and the user has no idea they need to
  // re-add the symbol. After 60s of pending state we flip the badge to
  // "Resolution timeout" + a Retry CTA.
  // WHY 60s: a typical resolve completes in 5-15s; 60s is a comfortable
  // 4x safety margin while still catching genuine stalls quickly.
  // WHY useState + useEffect (not Date.now() at render): the user
  // shouldn't have to remount or re-render to flip the state — we set
  // a local timer so the row updates itself.
  const [pendingTooLong, setPendingTooLong] = useState(false);
  useEffect(() => {
    if (member.resolution !== "pending") {
      // Reset if the row resolves successfully — otherwise the timeout
      // banner could persist if the same row was previously stuck.
      setPendingTooLong(false);
      return;
    }
    const timer = setTimeout(() => setPendingTooLong(true), 60_000);
    return () => clearTimeout(timer);
  }, [member.resolution]);

  return (
    // WHY group/row: enables the delete button to be hidden by default and revealed
    // only on row hover, keeping the table uncluttered during the primary read flow.
    <tr
      // R3 polish: the row is keyboard-focusable (tabIndex=0 below) but had
      // no visible focus affordance — keyboard users couldn't see which row
      // Enter/Space would open. focus-visible ring-inset keeps the ring
      // inside the 22px row so adjacent rows don't clip it; bg-muted/40
      // mirrors the hover tint for hover/focus parity.
      className="h-[22px] hover:bg-muted/40 cursor-pointer transition-colors group/row focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring focus-visible:bg-muted/40"
      onClick={() => onRowClick(member.instrument_id ?? member.entity_id)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onRowClick(member.instrument_id ?? member.entity_id);
        }
      }}
    >
      {/* Ticker — F-010 (QA 2026-04-28): when the local instrument cache
          had no match at add-time the backend reports resolution=pending.
          We show the dash placeholder PLUS a small "resolving…" badge so
          the user understands the row will auto-fill once the instrument
          syncs. WHY badge inline (not separate cell): keeps the table
          density tight; the badge sits in the otherwise-empty ticker
          column. */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
        {member.ticker ?? (
          <span className="inline-flex items-center gap-1">
            <span className="text-muted-foreground">—</span>
            {/* F-P-027: badge has two visual states — pending (yellow,
                "resolving…") for the first 60s, then escalates to a red
                "timeout" badge with a Retry CTA when the worker has
                clearly stalled. The Retry is purposely a small inline
                button (not a row-spanning banner) because the row is
                still useful — the user can delete the row outright via
                the existing trash button if they prefer. */}
            {member.resolution === "pending" && !pendingTooLong && (
              <span
                className="rounded-[2px] border border-warning/60 bg-warning/10 px-1 py-px text-[8px] uppercase tracking-[0.06em] text-warning"
                aria-label="Resolving instrument metadata"
              >
                resolving…
              </span>
            )}
            {member.resolution === "pending" && pendingTooLong && (
              <span
                className="inline-flex items-center gap-1 rounded-[2px] border border-negative/60 bg-negative/10 px-1 py-px text-[8px] uppercase tracking-[0.06em] text-negative"
                aria-label="Resolution timed out — try removing and re-adding this row"
                role="status"
              >
                {/* WHY just text + role=status: a screen-reader user gets the
                    full timeout message via aria-label; sighted users see the
                    visually-distinct red badge. The Retry path is the existing
                    Delete button on the row (then re-add through the search
                    bar) — we keep the badge text terse to fit the dense table
                    row. */}
                timeout — re-add
              </span>
            )}
          </span>
        )}
      </td>

      {/* Name — 2026-06-10 truncation fix: the max-w-[180px] hard cap is
          gone (it clipped names even when the row had free width at 1440px+).
          The cell is the table's flex column now; max-w-0 + w-full forces the
          table-cell to respect available width so truncate engages only at
          the REAL boundary, with the full name in the native tooltip. */}
      <td
        className="w-full max-w-0 truncate px-2 text-[11px] text-foreground"
        title={member.name}
      >
        {member.name}
      </td>

      {/* Price */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
        {quote ? formatPrice(quote.price) : "—"}
      </td>

      {/* Change% — colored */}
      <td
        className={cn(
          "px-2 font-mono text-[11px] tabular-nums text-right",
          quote ? priceChangeClass(quote.change_pct) : "text-muted-foreground",
        )}
      >
        {quote ? formatPercent(quote.change_pct / 100) : "—"}
      </td>

      {/* Change$ */}
      <td
        className={cn(
          "px-2 font-mono text-[11px] tabular-nums text-right",
          quote ? priceChangeClass(quote.change) : "text-muted-foreground",
        )}
      >
        {quote ? signedPrice(quote.change) : "—"}
      </td>

      {/* SPARK — 5-day close mini-trend (2026-06-10 density pass).
          The Sparkline primitive renders a dotted line for <2 points (never
          a blank cell) and color-codes trend from the data itself. */}
      <td className="px-2 text-center">
        <span className="inline-flex items-center align-middle">
          <Sparkline
            data={sparkline ?? []}
            label={`${member.ticker ?? member.name} 5-day trend`}
          />
        </span>
      </td>

      {/* VOL — latest session volume (compact). The dev quote feed returns
          volume=null → "—"; we never fabricate a count. */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
        {formatVolume(quote?.volume)}
      </td>

      {/* Actions — open-instrument affordance + delete, both hover-revealed.
          WHY stopPropagation on both: prevent the click from also firing the
          row's navigate handler (double navigation / navigate-then-delete). */}
      <td className="w-14 px-1 text-right whitespace-nowrap">
        {/* Open instrument — explicit ↗ affordance (the whole row navigates,
            but an invisible affordance is undiscoverable; the icon names it).
            Reuses onRowClick so the navigation path is identical to a row
            click — one routing rule, no drift. */}
        <button
          aria-label={`Open ${member.ticker ?? member.name} instrument page`}
          onClick={(e) => {
            e.stopPropagation();
            onRowClick(member.instrument_id ?? member.entity_id);
          }}
          title="Open instrument page"
          className={cn(
            "opacity-30 group-hover/row:opacity-100 transition-opacity",
            "h-5 w-5 inline-flex items-center justify-center rounded-[2px]",
            "text-muted-foreground hover:text-primary hover:bg-primary/10",
            "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          )}
        >
          <ExternalLink className="h-3 w-3" />
        </button>
        <button
          aria-label={`Remove ${member.ticker ?? member.name} from watchlist`}
          disabled={isDeleting}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(member.entity_id);
          }}
          title="Remove from watchlist"
          className={cn(
            // PLAN-0053 T-A-1-05: button was opacity-0 by default; users couldn't
            // discover it without random hovering. Surface at low opacity so it's
            // visible but not visually loud; raise to full on row hover.
            "opacity-30 group-hover/row:opacity-100 transition-opacity",
            "h-5 w-5 inline-flex items-center justify-center rounded-[2px]",
            "text-muted-foreground hover:text-negative hover:bg-negative/10",
            // R3 polish: keyboard parity with the hover reveal — when the
            // button itself is focused it must surface to full opacity and
            // show a ring, otherwise a Tab-navigating user is pressing an
            // invisible destructive button.
            "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            isDeleting && "opacity-50 cursor-not-allowed",
          )}
        >
          {isDeleting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Trash2 className="h-3 w-3" />
          )}
        </button>
      </td>
    </tr>
  );
}
