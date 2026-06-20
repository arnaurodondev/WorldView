/**
 * components/common/InstrumentPicker.tsx — shared debounced INSTRUMENT autocomplete
 * (PLAN-0113 Wave 4, T-4-02).
 *
 * WHY A NEW COMPONENT (the plan said "reuse TickerPicker"):
 * `components/workspace/TickerPicker.tsx` is a WORKSPACE widget — on select it
 * calls `setActiveSymbol(panelId, …)` from `SymbolLinkingContext` to broadcast
 * the symbol to a panel link-group. It does NOT return the picked instrument to a
 * callback, and it requires a `panelId` + the symbol-linking provider. That
 * contract is wrong for a FORM field, which must capture an `instrument_id`
 * locally without touching workspace state. Reusing TickerPicker here would
 * couple the alert wizard to SymbolLinkingContext and silently mutate the user's
 * open panels. So we provide this form-shaped sibling instead — same look, same
 * `searchInstruments` data source, but it emits the chosen instrument via
 * `onSelect` (the documented deviation for T-4-02).
 *
 * WHY `searchInstruments` (not `searchFundamentals`):
 * PRICE_CROSS / FUNDAMENTAL_CROSS rules key on an `instrument_id` (S3), not a KG
 * `entity_id`. `searchInstruments` returns the instrument_id directly and is the
 * right source for those rule types. (Entity-keyed rules use EntityPicker.)
 *
 * DESIGN: mirrors EntityPicker (Input + Skeleton, 300ms debounce, chip + clear).
 */

"use client";
// WHY "use client": useState + debounce + TanStack Query — browser-only.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { useDebounce } from "@/hooks/useDebounce";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { SearchResult } from "@/types/api";

/** ChosenInstrument — the minimal shape kept once an instrument is picked. */
export interface ChosenInstrument {
  instrumentId: string;
  ticker: string;
  name: string;
}

export interface InstrumentPickerProps {
  label: string;
  value: ChosenInstrument | null;
  onSelect: (instrument: ChosenInstrument) => void;
  onClear: () => void;
  placeholder?: string;
}

/**
 * InstrumentPicker — debounced symbol search → results dropdown → onSelect, or a
 * chip + clear button once chosen. Emits the chosen `instrument_id`.
 */
export function InstrumentPicker({
  label,
  value,
  onSelect,
  onClear,
  placeholder = "Symbol or name…",
}: InstrumentPickerProps) {
  const gw = useApiClient();
  const [query, setQuery] = useState("");
  const debounced = useDebounce(query, 300);

  const { data, isFetching } = useQuery({
    queryKey: ["instrument-picker-search", debounced],
    queryFn: () => gw.searchInstruments(debounced, 8),
    // >=1 char: ticker prefixes are short ("V", "F"); 1-char search is useful here.
    enabled: debounced.trim().length >= 1 && value === null,
    staleTime: 60_000,
  });

  // ── Selected state ────────────────────────────────────────────────────────
  if (value) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className="flex items-center gap-2 rounded-[2px] border border-primary/40 bg-primary/10 px-2 py-1">
          <span className="flex-1 truncate text-[11px] font-mono text-primary">
            {value.ticker} · {value.name}
          </span>
          <button
            type="button"
            onClick={() => {
              onClear();
              setQuery("");
            }}
            className="text-[12px] leading-none text-muted-foreground hover:text-foreground"
            aria-label={`Clear ${label}`}
          >
            ×
          </button>
        </div>
      </div>
    );
  }

  // ── Unselected state ──────────────────────────────────────────────────────
  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        className="h-7 text-[11px]"
        aria-label={`${label} instrument search`}
      />

      {debounced.trim().length >= 1 && (
        <div className="absolute top-full z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-[2px] border border-border/60 bg-popover shadow-lg">
          {isFetching && (
            <div className="space-y-1 p-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-full" />
            </div>
          )}
          {!isFetching && (data?.results.length ?? 0) === 0 && (
            <p className="p-2 font-mono text-[10px] text-muted-foreground">
              No matching instruments
            </p>
          )}
          {!isFetching &&
            (data?.results ?? []).map((r: SearchResult) => (
              <button
                key={r.instrument_id}
                type="button"
                onClick={() =>
                  onSelect({
                    instrumentId: r.instrument_id,
                    ticker: r.ticker,
                    name: r.name,
                  })
                }
                className="block w-full px-2 py-1 text-left text-[11px] font-mono text-foreground/90 hover:bg-muted/60"
              >
                <span className="text-primary">{r.ticker}</span>
                {"  "}
                <span className="text-foreground/70">{r.name}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
