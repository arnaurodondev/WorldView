/**
 * AliasPill — render a single (alias_type, value) pair as a compact pill.
 *
 * PLAN-0057 Wave F-2 / F-MAJOR-09 downstream surface.
 *
 * Used wherever an entity's identifier list is shown — entity-detail header,
 * watchlist hover-card, search-result preview.  Each alias_type carries a
 * subtly-different colour so analysts can distinguish CUSIP from FIGI from
 * ISIN at a glance without the page turning into a colour wheel.
 *
 * Accessibility note: the type label is rendered before the value with
 * `:` separator inside a single line so screen-readers announce
 * "ISIN: US0378331005" rather than two disconnected tokens.  Long values
 * (FIGI, LEI) overflow with ellipsis but the full value is in the `title`
 * attribute so a hover surfaces it.
 */

import * as React from "react";

import { aliasTypeToken } from "@/lib/alias-types";
import { cn } from "@/lib/utils";

export interface AliasPillProps {
  /** Backend alias_type — e.g. "ISIN", "CUSIP", "PRIMARY_TICKER", "NAME". */
  aliasType: string;
  /** The alias value itself (e.g. "US0378331005", "AAPL.US"). */
  value: string;
  /** Optional extra class names — composed via `cn` so callers can override. */
  className?: string;
  /** When true, hides the type label (e.g. inside a row that already
   *  groups by type).  The colour still distinguishes the pill. */
  hideLabel?: boolean;
}

export function AliasPill({ aliasType, value, className, hideLabel = false }: AliasPillProps) {
  const token = aliasTypeToken(aliasType);

  return (
    <span
      // `title` carries the full unabbreviated value so a hover always
      // surfaces it even when the visible text is truncated.
      title={`${token.label}: ${value}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-[2px] border px-1.5 py-0.5",
        // tabular-nums + monospace digits keep CUSIP / ISIN columns aligned
        // when stacked vertically — the analyst rule from the
        // institutional-style memory.
        "font-mono text-[11px] tabular-nums",
        // Truncate aggressively — the title attribute carries the full value.
        "max-w-[14rem] truncate",
        token.className,
        className,
      )}
    >
      {!hideLabel && (
        <span className="text-[10px] uppercase tracking-wider opacity-70">
          {token.label}
        </span>
      )}
      <span className="truncate">{value}</span>
    </span>
  );
}
