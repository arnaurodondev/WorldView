/**
 * components/shell/GlobalSearch.tsx — Instrument search in TopBar
 *
 * WHY THIS EXISTS: Traders need to navigate to any instrument quickly.
 * The search box (⌘K shortcut) lets users type a ticker or company name
 * and jump directly to the Instrument Detail page.
 *
 * WHY debounce (not instant): Typing "AAPL" fires 4 keystrokes.
 * Without debounce, that's 4 S9 calls. Debouncing to 300ms means 1-2 calls.
 * Users don't notice 300ms latency while typing — they see results when they pause.
 *
 * WHY cmdk (Command): Bloomberg and Refinitiv both use keyboard-navigable search.
 * Our target users know ↑/↓ arrow keys and Enter for selection.
 * cmdk provides this interaction model out of the box.
 *
 * WHY click-outside ref (not onBlur+setTimeout): The original onBlur+setTimeout
 * pattern was fragile — some browsers fire blur before the pointerup event that
 * cmdk uses to trigger onSelect, so clicking a result closed the dropdown before
 * navigation fired. A mousedown click-outside detector is more reliable: it only
 * closes the dropdown when the click target is genuinely outside the search widget
 * (SEARCH-001 fix, 2026-04-24).
 *
 * WHY onClick AND onSelect on CommandItem: cmdk's onSelect fires for keyboard
 * Enter selection; onClick fires for mouse clicks. Some cmdk versions only trigger
 * one or the other depending on whether the item is keyboard-highlighted. Using
 * both handlers ensures navigation works regardless of interaction mode.
 *
 * WHO USES IT: components/shell/TopBar.tsx
 * DATA SOURCE: S9 GET /api/v1/search/instruments?q=<query>
 * DESIGN REFERENCE: PRD-0028 §6.5 GlobalSearch
 */

"use client";
// WHY "use client": Uses useState for input state, useQuery for search results,
// useRouter for navigation, useRef for click-outside detection — all browser-side.

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
// WHY no Search icon import here: CommandInput from shadcn/ui already renders its own Search icon
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useDebounce } from "@/hooks/useDebounce";
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command";

// ── Recent instruments localStorage helpers ───────────────────────────────────
// WHY store recent instruments: Bloomberg-style search remembers the last 5
// instruments you navigated to and shows them when the search input is focused
// but empty. This reduces clicks for traders who repeatedly check the same tickers.
const RECENT_KEY = "worldview-recent-instruments";
const RECENT_MAX = 5;

/** Read the recent instruments list from localStorage (falls back to []) */
function readRecent(): Array<{ entityId: string; ticker: string; name: string }> {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as Array<{ entityId: string; ticker: string; name: string }>) : [];
  } catch {
    return [];
  }
}

/** Prepend a new instrument to the recent list, keeping at most RECENT_MAX entries */
function saveRecent(entityId: string, ticker: string, name: string): void {
  try {
    const current = readRecent().filter((r) => r.entityId !== entityId);
    const updated = [{ entityId, ticker, name }, ...current].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(updated));
  } catch {
    // localStorage may be blocked in some browsers — silently ignore
  }
}

export function GlobalSearch() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  // WHY recentKey: incrementing this causes recentInstruments to re-read from
  // localStorage after a navigation, ensuring the list is always fresh.
  const [recentKey, setRecentKey] = useState(0);

  // WHY containerRef: used by the click-outside mousedown listener to determine
  // whether the click target is inside the search widget. If outside → close.
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Recent instruments (shown when query is empty) ────────────────────────
  // WHY useMemo keyed to recentKey: re-reads localStorage when the key increments
  // (after each navigation) without requiring a useEffect + setState.
  const recentInstruments = useMemo(() => readRecent(), [recentKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // PLAN-0050 T-F-6-14 (closes F-I-026): debounce dropped from 300ms to 250ms.
  // Audit: at 300ms the user types a 4-letter ticker and finishes before the
  // first request fires — feels laggy on fast typists. 250ms is the inflection
  // where one suggestion request fires for an average 3-5 char ticker, still
  // cheap enough to avoid per-keystroke spam.
  const debouncedQuery = useDebounce(query, 250);

  const { data } = useQuery({
    queryKey: ["instrument-search", debouncedQuery],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.searchInstruments(debouncedQuery, 10);
    },
    // WHY enabled check: only search when there's a non-trivial query AND user is authed
    enabled: debouncedQuery.length >= 1 && !!accessToken,
    // WHY staleTime 30s: search results don't change often; cache avoids re-fetching
    // the same query on re-focus
    staleTime: 30_000,
  });

  // ── Click-outside detection ───────────────────────────────────────────────
  // WHY mousedown (not click): mousedown fires before blur, so we can determine
  // whether the user is clicking inside the widget before the input loses focus.
  // If clicking outside → close. If clicking inside (on a result) → do nothing
  // here; the result's onClick/onSelect will handle navigation.
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleMouseDown);
    }
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [open]);

  // ── ⌘K shortcut ──────────────────────────────────────────────────────────
  // WHY ⌘K handler: Bloomberg-like keyboard shortcut for search.
  // Experienced traders use keyboard more than mouse.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault(); // WHY: browser uses Ctrl+K for location bar on some browsers
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // ── Navigation handler (shared by onSelect and onClick) ──────────────────
  // WHY useCallback: stable reference so it can be used safely in both handlers
  // without triggering re-renders.
  const navigateTo = useCallback((entityId: string, ticker: string, name: string) => {
    // ADR-F-12: entity_id ≠ instrument_id — always use entity_id for URL routing.
    // WHY saveRecent before push: localStorage write is sync; if we wrote after
    // push, the re-read triggered by recentKey increment might race with navigation.
    saveRecent(entityId, ticker, name);
    setRecentKey((k) => k + 1); // trigger re-read of recent list
    router.push(`/instruments/${entityId}`);
    setQuery("");
    setOpen(false);
  }, [router]);

  const results = data?.results ?? [];

  // WHY showRecent: show recent instruments when query is empty (Bloomberg-style).
  // When the user has typed something, show search results instead.
  const showRecent = debouncedQuery.length === 0;

  return (
    // WHY ref on container div: needed for click-outside detection to distinguish
    // clicks inside the search widget from clicks on the rest of the page.
    // WHY w-56 (224px, was 256px): narrower search bar balances better against the
    // TopBar's 36px height — a 256px box was disproportionately wide for a 36px bar.
    <div ref={containerRef} className="relative w-56">
      {/* WHY Command (not a plain input): gives us keyboard navigation and selection
          semantics that users expect from a Bloomberg-like interface.
          WHY border-border/50 (was border-border): full-opacity border in a 36px
          nav bar creates a "box-inside-a-bar" effect. 50% opacity integrates the
          search box into the TopBar chrome without losing affordance. */}
      <Command className="rounded-[2px] border border-border/50 bg-muted/20 shadow-none" shouldFilter={false}>
        <CommandInput
          placeholder="Search instruments… ⌘K"
          value={query}
          onValueChange={(val) => {
            setQuery(val);
            // WHY always open: when val is empty, open shows recent instruments.
            // When val has text, open shows search results. Always show the dropdown
            // when the user is actively typing.
            setOpen(true);
          }}
          // WHY onFocus opens the dropdown: traders expect recent instruments to
          // appear when they click the search box (Bloomberg-style). Without this,
          // the recent list would only appear after typing a character.
          onFocus={() => setOpen(true)}
          // WHY no onBlur here: close is handled by the click-outside mousedown
          // listener above. An onBlur+setTimeout can race against the item's
          // onClick and cause navigation to never fire (SEARCH-001).
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              setQuery("");
            }
          }}
          className="h-7 text-[11px]"
        />

        {/* Dropdown — shown on focus or when typing */}
        {open && (
          <div
            // WHY rounded-[2px] (was rounded-md): terminal 2px radius rule
            // WHY no onMouseDown preventDefault here: the original e.preventDefault()
            // was meant to prevent input blur on result click. In WebKit/Safari, calling
            // preventDefault on a parent's mousedown suppresses the click event on
            // children entirely — so clicking a result never fires cmdk's internal
            // onClick → onSelect. The click-outside mousedown listener on document is
            // the PRIMARY close guard (it only closes when clicking OUTSIDE the container),
            // so this belt-and-suspenders is unnecessary and harmful. Removed.
            className="absolute left-0 top-full z-50 mt-1 w-full rounded-[2px] border border-border bg-popover"
          >
            <CommandList>
              {/* ── Recent instruments (shown when query is empty) ────────── */}
              {showRecent && recentInstruments.length > 0 && (
                <CommandGroup heading="Recent">
                  {recentInstruments.map((recent) => (
                    <CommandItem
                      key={recent.entityId}
                      value={recent.entityId}
                      onSelect={() => navigateTo(recent.entityId, recent.ticker, recent.name)}
                      onClick={() => navigateTo(recent.entityId, recent.ticker, recent.name)}
                      className="cursor-pointer"
                    >
                      <div className="flex w-full items-center gap-2">
                        <span className="shrink-0 font-mono text-sm font-medium tabular-nums text-foreground">
                          {recent.ticker}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                          {recent.name}
                        </span>
                        {/* WHY clock icon text: subtle "recent" signal without a bulky icon */}
                        <span className="shrink-0 text-[10px] text-muted-foreground/60">↩</span>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {/* ── Empty state when no recents and no query ──────────────── */}
              {showRecent && recentInstruments.length === 0 && (
                <CommandEmpty className="py-3 text-xs">
                  Type to search instruments…
                </CommandEmpty>
              )}

              {/* ── Search results ───────���───────────────────────────────── */}
              {!showRecent && (
                <>
                  <CommandEmpty className="py-3 text-xs">
                    No instruments found.
                  </CommandEmpty>

                  {results.length > 0 && (
                    <CommandGroup>
                      {results.map((result) => (
                        <CommandItem
                          key={result.entity_id}
                          // WHY value={result.entity_id}: cmdk uses the `value` prop for
                          // keyboard selection matching. Without it, cmdk tries to match
                          // against the text content of the item — which is a concatenation
                          // of ticker + name + exchange. Setting value explicitly ensures
                          // the correct item is highlighted when navigating with arrow keys.
                          value={result.entity_id}
                          // WHY onSelect: fires on keyboard Enter when the item is highlighted.
                          onSelect={() => navigateTo(result.entity_id, result.ticker, result.name)}
                          // WHY onClick: fires on mouse click. cmdk's onSelect does not always
                          // fire on click if the item isn't keyboard-highlighted — adding onClick
                          // makes navigation work regardless of interaction mode (SEARCH-001).
                          onClick={() => navigateTo(result.entity_id, result.ticker, result.name)}
                          className="cursor-pointer"
                        >
                          <div className="flex w-full items-center justify-between gap-2">
                            {/* Ticker — monospace for alignment */}
                            <span className="shrink-0 font-mono text-sm font-medium tabular-nums text-foreground">
                              {result.ticker}
                            </span>
                            {/* Company name — truncated to fit */}
                            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                              {result.name}
                            </span>
                            {/* Exchange badge */}
                            {result.exchange && (
                              <span className="shrink-0 text-xs text-muted-foreground">
                                {result.exchange}
                              </span>
                            )}
                          </div>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  )}
                </>
              )}
            </CommandList>

            {/* ── Keyboard hint strip ────────���─────────────────────────────── */}
            {/* WHY keyboard hints: Bloomberg-style search always shows keyboard
                shortcuts in the dropdown footer. Traders use keyboard more than mouse;
                showing ↑↓/↵/⎋ reduces learning curve for new users. */}
            <div className="flex items-center justify-end gap-3 border-t border-border/40 px-2 py-1">
              <span className="text-[9px] text-muted-foreground/60">
                <kbd className="font-mono">↑↓</kbd> Navigate
              </span>
              <span className="text-[9px] text-muted-foreground/60">
                <kbd className="font-mono">↵</kbd> Open
              </span>
              <span className="text-[9px] text-muted-foreground/60">
                <kbd className="font-mono">⎋</kbd> Close
              </span>
            </div>
          </div>
        )}
      </Command>
    </div>
  );
}
