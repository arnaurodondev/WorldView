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
 * WHO USES IT: components/shell/TopBar.tsx
 * DATA SOURCE: S9 GET /api/v1/search/instruments?q=<query>
 * DESIGN REFERENCE: PRD-0028 §6.5 GlobalSearch
 */

"use client";
// WHY "use client": Uses useState for input state, useQuery for search results,
// useRouter for navigation — all browser-side operations.

import { useState, useEffect } from "react";
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

export function GlobalSearch() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  // WHY debounce 300ms: don't fire S9 search on every keystroke — wait for pause
  const debouncedQuery = useDebounce(query, 300);

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

  const results = data?.results ?? [];

  return (
    <div className="relative w-64">
      {/* WHY Command (not a plain input): gives us keyboard navigation and selection
          semantics that users expect from a Bloomberg-like interface */}
      <Command className="rounded-md border border-border bg-background shadow-none" shouldFilter={false}>
        <CommandInput
          placeholder="Search instruments… ⌘K"
          value={query}
          onValueChange={(val) => {
            setQuery(val);
            setOpen(val.length > 0);
          }}
          onBlur={() => {
            // Delay close to allow click on result item to register
            setTimeout(() => setOpen(false), 150);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          className="h-8 text-sm"
        />

        {/* Dropdown results — only shown when query is non-empty */}
        {open && (
          // WHY onMouseDown preventDefault: clicking a result fires "blur" on the input
          // before the "click" on the CommandItem registers. Calling preventDefault() on
          // the container's mousedown stops the input from losing focus (and closing the
          // dropdown) before the click handler on CommandItem can execute. Without this,
          // clicking a result on some browsers/OSes would close the dropdown and navigate
          // to nothing.
          <div
            className="absolute left-0 top-full z-50 mt-1 w-full rounded-md border border-border bg-popover shadow-lg"
            onMouseDown={(e) => e.preventDefault()}
          >
            <CommandList>
              <CommandEmpty className="py-3 text-xs">
                {debouncedQuery.length >= 1 ? "No instruments found." : "Type to search…"}
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
                      onSelect={() => {
                        // Navigate to instrument detail using entity_id (ADR-F-12:
                        // entity_id ≠ instrument_id — use entity_id for URL routing)
                        router.push(`/instruments/${result.entity_id}`);
                        setQuery("");
                        setOpen(false);
                      }}
                      className="cursor-pointer"
                    >
                      <div className="flex w-full items-center justify-between">
                        {/* Ticker — monospace for alignment */}
                        <span className="font-mono text-sm font-medium tabular-nums text-foreground">
                          {result.ticker}
                        </span>
                        {/* Company name — truncated to fit */}
                        <span className="ml-2 truncate text-xs text-muted-foreground">
                          {result.name}
                        </span>
                        {/* Exchange badge */}
                        {result.exchange && (
                          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                            {result.exchange}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </div>
        )}
      </Command>
    </div>
  );
}
