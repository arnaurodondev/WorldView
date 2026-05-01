/**
 * components/workspace/TickerPicker.tsx — Per-panel inline symbol picker
 *
 * WHY THIS EXISTS: Symbol-aware panels (chart, fundamentals, graph) need a way to
 * change their linked ticker without leaving the workspace. The static "[AAPL]"
 * label was read-only. TickerPicker turns that label into a clickable command-palette
 * popover so traders can swap symbols in one keyboard stroke.
 *
 * UX CONTRACT:
 *   - Click (or press Enter when focused) → opens a small popover with a search input
 *   - Typing → debounced S9 search, results appear in 300 ms
 *   - No input → shows the last 5 recently-viewed instruments from localStorage
 *   - Select → calls setActiveSymbol(panelId, ticker, instrumentId), closes popover,
 *              saves to recents list
 *   - "[—]" shows when no symbol is set yet (invites the user to search)
 *   - Escape → closes without change
 *
 * WHY POPOVER + COMMAND (not a full modal): a panel header is only 24px — a full
 * modal would be disproportionate. Popover anchors to the badge, Command (cmdk)
 * provides the keyboard-accessible filtered list that traders already know from
 * GlobalSearch.
 *
 * WHY setActiveSymbol (not a local prop): the TickerPicker must broadcast the new
 * symbol to all panels in the same link-color group — only setActiveSymbol from
 * SymbolLinkingContext does that. Prop-drilling a callback would bypass the broadcast.
 *
 * DATA FLOW:
 *   1. On open: render recent instruments (localStorage, no network)
 *   2. On keystroke: debounced searchInstruments via gateway
 *   3. On select: setActiveSymbol + saveRecentInstrument + close
 *
 * DEPENDENCIES: TanStack Query, gateway lib, SymbolLinkingContext, cmdk, Popover
 * WHO USES IT: components/workspace/WorkspacePanelContainer.tsx (symbol indicator slot)
 * DESIGN REFERENCE: Handoff 2026-05-01 Tier-3 #8 — Per-widget TickerPicker
 */

"use client";
// WHY "use client": uses state, context, localStorage (browser APIs), and Radix Popover.

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useSymbolLinking } from "@/contexts/SymbolLinkingContext";
import { readRecentInstruments, saveRecentInstrument } from "@/lib/recent-instruments";

interface TickerPickerProps {
  /** The panel this picker controls — used to broadcast via setActiveSymbol */
  panelId: string;
  /** Current active symbol (null if none set yet) */
  symbol: string | null;
}

/**
 * TickerPicker — clickable "[AAPL]" badge that opens an instrument search popover.
 * Broadcasts the selected symbol to all panels in the same link-color group.
 */
export function TickerPicker({ panelId, symbol }: TickerPickerProps) {
  const { accessToken } = useAuth();
  const { setActiveSymbol } = useSymbolLinking();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounce(query, 300);

  // ── Search query ────────────────────────────────────────────────────────────
  // WHY only fire when query is non-empty: empty-string search returns the full
  // catalog — too slow and too noisy. We show recents instead when query = "".
  const { data: searchData } = useQuery({
    queryKey: ["ticker-picker-search", debouncedQuery],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.searchInstruments(debouncedQuery, 8);
    },
    enabled: !!accessToken && debouncedQuery.length >= 1,
    staleTime: 30_000,
  });

  // ── Select handler ──────────────────────────────────────────────────────────
  const handleSelect = useCallback(
    (entityId: string, ticker: string, name: string, instrumentId: string) => {
      // Broadcast to all panels in the same color group
      setActiveSymbol(panelId, ticker, instrumentId);
      // Persist to recents so the picker remembers it next time
      saveRecentInstrument(entityId, ticker, name);
      // Reset and close
      setQuery("");
      setOpen(false);
    },
    [panelId, setActiveSymbol]
  );

  // ── Derive the list to show ─────────────────────────────────────────────────
  // WHY compute inside render (not useMemo): readRecentInstruments() is a
  // synchronous localStorage read (~1 µs) — memoisation would be micro-optimising
  // a non-bottleneck and would require localStorage event subscriptions to stay fresh.
  const searchResults = searchData?.results ?? [];
  const recentItems = readRecentInstruments();
  const showRecents = debouncedQuery.length === 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/*
       * WHY asChild: the button is already styled below; asChild prevents Popover
       * from wrapping it in an extra <button> (double-button nesting is invalid HTML).
       */}
      <PopoverTrigger asChild>
        {/*
         * WHY font-mono + text-[11px]: matches the existing static symbol indicator
         * style so the badge reads as part of the panel header chrome, not a foreign UI.
         * WHY hover:bg-muted/30: subtle interaction affordance — visible on hover but
         * not distracting in the dense 24px header.
         */}
        <button
          className="ml-1 rounded px-0.5 font-mono text-[11px] text-foreground hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          aria-label={symbol ? `Change symbol, currently ${symbol}` : "Pick a symbol"}
        >
          [{symbol ?? "—"}]
        </button>
      </PopoverTrigger>

      {/*
       * WHY w-56 (224px): wide enough for "BERKSHIRE HATHAWAY B" truncated at 11px
       * without overflowing a 320px panel. align="start" anchors the left edge of the
       * popover to the left edge of the trigger badge.
       * WHY p-0: Command handles its own internal padding.
       */}
      <PopoverContent className="w-56 p-0" align="start" side="bottom">
        <Command shouldFilter={false}>
          {/*
           * WHY placeholder "Symbol or name": communicates both input modes — a trader
           * can type "AAPL" (ticker) or "apple" (company name) and get results.
           */}
          <CommandInput
            placeholder="Symbol or name…"
            value={query}
            onValueChange={setQuery}
            className="text-[11px]"
          />

          <CommandList>
            {/* ── No results state ── */}
            <CommandEmpty className="py-2 text-center text-[11px] text-muted-foreground">
              No instruments found.
            </CommandEmpty>

            {/* ── Recent instruments (shown when input is empty) ── */}
            {showRecents && recentItems.length > 0 && (
              <CommandGroup
                heading="Recent"
                className="[&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-muted-foreground"
              >
                {recentItems.map((r) => (
                  <CommandItem
                    key={r.entityId}
                    value={r.ticker}
                    onSelect={() =>
                      handleSelect(r.entityId, r.ticker, r.name, `ins-${r.ticker.toLowerCase()}`)
                    }
                    className="cursor-pointer"
                  >
                    {/* WHY font-mono for ticker: tabular-nums alignment in list */}
                    <span className="font-mono text-[11px] text-foreground">{r.ticker}</span>
                    <span className="ml-2 truncate text-[10px] text-muted-foreground">{r.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {/* ── Search results (shown when query is non-empty) ── */}
            {!showRecents && searchResults.length > 0 && (
              <CommandGroup
                heading="Results"
                className="[&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-muted-foreground"
              >
                {searchResults.map((r) => (
                  <CommandItem
                    key={r.instrument_id}
                    value={r.ticker}
                    onSelect={() =>
                      handleSelect(r.entity_id, r.ticker, r.name, r.instrument_id)
                    }
                    className="cursor-pointer"
                  >
                    <span className="font-mono text-[11px] text-foreground">{r.ticker}</span>
                    <span className="ml-2 truncate text-[10px] text-muted-foreground">{r.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
