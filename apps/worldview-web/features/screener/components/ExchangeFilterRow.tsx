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
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <label className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-20 shrink-0">
        Exchange
      </label>
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
