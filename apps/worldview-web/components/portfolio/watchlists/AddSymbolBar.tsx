/**
 * components/portfolio/watchlists/AddSymbolBar.tsx — Inline instrument search + add bar
 *
 * WHY EXTRACTED: AddSymbolBar was an inner function inside WatchlistsTabPanel.tsx.
 * Extracting it isolates the search+mutation logic (300ms debounce, GatewayError
 * differentiation) from the tab-bar orchestration so both pieces stay under 400 lines.
 *
 * WHY search-to-add: traders discover instruments in the screener or news, then
 * want to add them to a watchlist immediately. An inline search bar in the watchlist
 * eliminates the round-trip to another page.
 *
 * WHY debounced query: avoid hammering S9 on every keystroke; 300ms delay is
 * enough for fast typists to finish a 3-letter ticker (e.g., "AAP" → "AAPL").
 *
 * WHO USES IT: WatchlistsTabPanel — never directly by pages.
 */

"use client";
// WHY "use client": uses useState, useEffect, useRef, useQuery, useMutation.

import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, X, Loader2 } from "lucide-react";
import { createGateway, GatewayError } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AddSymbolBarProps {
  watchlistId: string;
  onAdded: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AddSymbolBar({ watchlistId, onAdded }: AddSymbolBarProps) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  // WHY debounced query: avoid hammering S9 on every keystroke; 300ms delay is
  // enough for fast typists to finish a 3-letter ticker (e.g., "AAP" → "AAPL").
  // F-P-024 (PLAN-0051 W6): 300ms is the canonical debounce window for
  // the watchlist search — DO NOT bump this without measuring. Lower
  // values cost more S9 round-trips per typed query; higher values feel
  // sluggish. 300ms sits in the perceptible "instant after pause" sweet
  // spot the rest of the app uses (e.g. transactions search → 200ms,
  // chat thread search → 200ms).
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  const { data: searchResults, isFetching: searchFetching } = useQuery({
    queryKey: ["watchlist-fundamentals-search", debouncedQuery],
    // WHY searchFundamentals (B-3): the watchlist endpoint needs the REAL KG
    // entity_id. searchInstruments falls back to instrument_id and the add
    // silently fails. The screener joins through S7 KG so it returns the real
    // entity_id directly — same shape, correct ID.
    queryFn: () => createGateway(accessToken).searchFundamentals(debouncedQuery, 8),
    enabled: !!accessToken && debouncedQuery.length >= 1,
    staleTime: 30_000,
  });

  // PLAN-0053 T-A-1-04: typed error message keyed off GatewayError.status.
  const [addErrorMsg, setAddErrorMsg] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: (entityId: string) =>
      createGateway(accessToken).addWatchlistMember(watchlistId, entityId),
    onSuccess: () => {
      // PLAN-0046 / T-46-2-03: invalidate the per-watchlist members query so
      // the just-added row is fetched and rendered, AND the list query so the
      // tab badge member count refreshes.
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      queryClient.invalidateQueries({
        queryKey: ["watchlist-members", watchlistId],
      });
      setSearchQuery("");
      setDebouncedQuery("");
      setShowDropdown(false);
      setAddErrorMsg(null);
      onAdded();
    },
    onError: (err) => {
      // PLAN-0053 T-A-1-04: differentiate add-flow errors so users know whether
      // the symbol already exists, isn't found, or the server is having trouble.
      // Previously a single generic message was shown for every failure mode.
      if (err instanceof GatewayError) {
        if (err.status === 409) {
          setAddErrorMsg("Already in this watchlist");
        } else if (err.status === 404) {
          setAddErrorMsg("Symbol not found — try the full ticker (e.g. AAPL)");
        } else if (err.status >= 500) {
          setAddErrorMsg("Server error — please try again");
        } else {
          setAddErrorMsg(err.message || "Failed to add");
        }
      } else {
        setAddErrorMsg("Failed to add — please try again");
      }
    },
  });

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    // PLAN-0053 T-B-2-02: with the Wave B backend fix (T-B-2-01) the S3
    // instrument search now matches the ``name`` column too — "apple" finds
    // Apple Inc. via the pg_trgm GIN index. Auto-uppercase is no longer
    // required; preserve the user's casing so the dropdown reflects their
    // intent. Empty error on every change so a fresh query starts clean.
    setSearchQuery(e.target.value);
    setShowDropdown(e.target.value.length > 0);
    setAddErrorMsg(null);
  }

  function handleClear() {
    setSearchQuery("");
    setDebouncedQuery("");
    setShowDropdown(false);
  }

  const results = searchResults?.results ?? [];
  const hasResults = results.length > 0;

  return (
    <div ref={containerRef} className="relative border-b border-border px-2 py-1.5">
      <div className="flex h-7 items-center gap-1.5 rounded-[2px] border border-border bg-background px-2">
        <Search className="h-3 w-3 shrink-0 text-muted-foreground" />

        <input
          value={searchQuery}
          onChange={handleInputChange}
          onFocus={() => {
            if (searchQuery.length > 0) setShowDropdown(true);
          }}
          placeholder="Add ticker or company name…"
          className="flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground/60"
          aria-label="Search to add instrument"
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-controls="watchlist-search-listbox"
          aria-expanded={showDropdown && hasResults}
        />

        {searchFetching && (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}

        {searchQuery && !searchFetching && (
          <button
            onClick={handleClear}
            aria-label="Clear search"
            // R3 polish: focus-visible ring — keyboard parity with hover
            // (the clear affordance was mouse-only discoverable before).
            className="shrink-0 rounded-[2px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      {showDropdown && (hasResults || (debouncedQuery.length > 0 && !searchFetching)) && (
        <div
          id="watchlist-search-listbox"
          role="listbox"
          aria-label="Search results"
          className="absolute left-2 right-2 top-full z-50 mt-0.5 overflow-hidden rounded-[2px] border border-border bg-card"
        >
          {!hasResults && debouncedQuery.length > 0 ? (
            // PLAN-0053 T-A-1-04: empty-state hint nudges users toward the
            // ticker symbol when their query (often the company name) misses.
            <div className="px-3 py-2 text-[11px] text-muted-foreground">
              No results for &quot;{debouncedQuery}&quot;.
              <br />
              <span className="text-[10px] text-muted-foreground/80">
                Try the stock ticker (e.g. AAPL for Apple).
              </span>
            </div>
          ) : (
            results.map((result) => (
              <button
                key={result.instrument_id}
                role="option"
                aria-selected={false}
                disabled={addMutation.isPending}
                onClick={() => addMutation.mutate(result.entity_id)}
                className={cn(
                  "flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors",
                  // R3 polish: focus-visible ring-inset added on top of the
                  // existing focus bg-tint so keyboard users see a crisp
                  // outline on the focused option, not just a subtle tint.
                  "hover:bg-muted/50 focus:bg-muted/50 focus:outline-none",
                  "focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
                  addMutation.isPending && "opacity-50 cursor-not-allowed",
                )}
              >
                <span className="w-[48px] shrink-0 font-mono text-[11px] font-medium text-primary">
                  {result.ticker}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">
                  {result.name}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {result.exchange}
                </span>
              </button>
            ))
          )}

          {addMutation.isError && addErrorMsg && (
            <div className="border-t border-border px-2 py-1 text-[10px] text-negative">
              {addErrorMsg}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
