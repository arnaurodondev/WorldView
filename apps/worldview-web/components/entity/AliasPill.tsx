/**
 * AliasPill — render a single (alias_type, value) pair as a compact pill.
 *
 * PLAN-0057 Wave F-2 / F-MAJOR-09 downstream surface (QA N-4 polish: now
 * carries a copy-to-clipboard button — analysts copy CUSIP/ISIN/FIGI values
 * into Bloomberg / FactSet / Excel constantly so a one-click copy saves a
 * non-trivial amount of friction).
 *
 * Used wherever an entity's identifier list is shown — entity-detail header,
 * watchlist hover-card, search-result preview.  Each alias_type carries a
 * subtly-different colour so analysts can distinguish CUSIP from FIGI from
 * ISIN at a glance without the page turning into a colour wheel.
 *
 * Accessibility: the type label is rendered before the value with `:`
 * separator so screen-readers announce "ISIN: US0378331005" rather than
 * two disconnected tokens.  Long values overflow with ellipsis but the
 * full value is in the `title` attribute so a hover surfaces it.  The
 * copy button is keyboard-reachable and announces "Copy ISIN value" via
 * `aria-label`.
 */

"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

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
  /** When true, hides the copy button (small inline contexts). */
  hideCopy?: boolean;
}

export function AliasPill({
  aliasType,
  value,
  className,
  hideLabel = false,
  hideCopy = false,
}: AliasPillProps) {
  const token = aliasTypeToken(aliasType);
  const [copied, setCopied] = React.useState(false);

  const handleCopy = React.useCallback(
    async (e: React.MouseEvent | React.KeyboardEvent) => {
      e.stopPropagation();
      // navigator.clipboard is unavailable in test/SSR contexts — gracefully
      // no-op there so the unit tests don't need a polyfill.
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          // Reset the icon after 1.5 s — long enough for the analyst to see
          // the confirmation, short enough to not litter the UI.
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access denied (HTTP context, locked-down browsers).
          // We could fall back to a textarea trick, but the analyst can
          // still triple-click the value text and Cmd+C — no UX disaster.
        }
      }
    },
    [value],
  );

  return (
    <span
      title={`${token.label}: ${value}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-[2px] border px-1.5 py-0.5",
        // tabular-nums + monospace digits keep CUSIP / ISIN columns aligned
        // when stacked vertically.
        "font-mono text-[11px] tabular-nums",
        "max-w-[16rem]",
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
      {!hideCopy && (
        <button
          type="button"
          onClick={handleCopy}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") handleCopy(e);
          }}
          aria-label={`Copy ${token.label} value`}
          className={cn(
            "ml-0.5 inline-flex h-3 w-3 items-center justify-center rounded-[1px]",
            "opacity-50 transition-opacity hover:opacity-100 focus:opacity-100",
            "focus:outline-none focus:ring-1 focus:ring-current",
          )}
        >
          {copied ? (
            <Check aria-hidden="true" className="h-2.5 w-2.5" />
          ) : (
            <Copy aria-hidden="true" className="h-2.5 w-2.5" />
          )}
        </button>
      )}
    </span>
  );
}
