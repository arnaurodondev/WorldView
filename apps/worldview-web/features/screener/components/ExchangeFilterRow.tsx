"use client";

/**
 * features/screener/components/ExchangeFilterRow.tsx — Exchange filter row
 * (PRD-0089 Wave I-B Block IB-L1 · T-IB-02).
 *
 * WHY: mirror image of CountryFilterRow without the regional presets —
 * exchanges don't cluster in a way most analysts use ("US exchanges" is
 * really "country: USA"). A flat multi-select is enough.
 *
 * Wave L-1 backend (commit 3541ad86) added `exchange` to ScreenFilter
 * and seeded `screen_field_metadata` (field_type="text"). The static
 * option list lives in `@/lib/screener/exchanges` — see file header for
 * the rationale (allowlist hook not wired; plan §6.1 allows the fallback).
 *
 * NO BackendPendingBadge — backend is live.
 */

import { MultiCombobox, type MultiComboboxItem } from "@/components/ui/multi-combobox";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { COMMON_EXCHANGES } from "@/lib/screener/exchanges";

export interface ExchangeFilterRowProps {
  /** Current selection — exchange codes. Empty = no filter. */
  value: readonly string[];
  /** Called with the new selection (exchange codes). */
  onChange: (exchanges: string[]) => void;
}

// Pre-compute the option list once at module load — see CountryFilterRow
// header for why we don't useMemo.
const EXCHANGE_OPTIONS: MultiComboboxItem[] = COMMON_EXCHANGES.map((code) => ({
  id: code,
  label: code,
}));

export function ExchangeFilterRow({ value, onChange }: ExchangeFilterRowProps) {
  // WHY truncation disclosure: mirrors CountryFilterRow — see that file for
  // the full rationale. Wave L-1 backend takes only the FIRST element of the
  // `exchanges` array per ScreenFilterRequest (see
  // features/screener/lib/build-filters.ts §"Categorical / coverage"). Without
  // this badge, selecting {NYSE,NASDAQ} silently filters on NYSE only. Wave
  // L-2 will add IN(...) support and remove this badge.
  const isTruncated = value.length > 1;
  const truncationCopy =
    "Wave L-1 backend currently filters on the first selected exchange only. Wave L-2 will add IN-list support.";

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <label className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-20 shrink-0">
        Exchange
      </label>
      {/* Backend-truncation badge — see CountryFilterRow for design rationale. */}
      {isTruncated ? (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                role="status"
                aria-label={truncationCopy}
                className="text-warning bg-warning/10 text-[9px] font-mono px-1.5 rounded-[2px] cursor-help"
              >
                {`backend: 1 of ${value.length}`}
              </span>
            </TooltipTrigger>
            <TooltipContent side="top">{truncationCopy}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : null}
      <MultiCombobox
        items={EXCHANGE_OPTIONS}
        selectedIds={[...value]}
        onChange={onChange}
        placeholder="All exchanges"
        emptyMessage="No matching exchange codes."
        className="h-7 w-44"
      />
    </div>
  );
}
