/**
 * app/(app)/instruments/page.tsx — Instruments browse / landing page
 *
 * WHY THIS EXISTS: The sidebar nav links to "/instruments". Users clicking it
 * expect to see a list of instruments they can search and browse — not a redirect
 * to a different page. This page IS the instrument browser: a search-first table
 * showing all instruments with click-through to each instrument's detail page.
 *
 * WHY DISTINCT FROM /screener: The Screener page (/screener) is a power-user tool
 * with an advanced multi-field filter bar (sector, cap tier, operators). This page
 * is the instrument BROWSER — a simple search box + table, focused on lookup and
 * navigation rather than complex multi-criteria filtering. Bloomberg analogy:
 * SECF (Security Finder) vs. EQUITY SCREEN.
 *
 * WHY REUSE ScreenerTable + ScreenerFilterBar: Both components already implement
 * the correct terminal-quality rendering (virtual scroll, 12-col layout, heat
 * cells, sort). Re-implementing would duplicate ~400 lines for no user benefit.
 * We pass simpler state management (search-only) rather than the full filter set.
 *
 * WHY NO SERVER COMPONENT: useQuery and useAuth require client rendering. The
 * screener POST request also requires the user's access token.
 *
 * WHO USES IT: Sidebar "Instruments" nav link click, direct /instruments URL access
 * DATA SOURCE: POST /v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REFERENCE: PRD-0031 §6.3 Navigation, PRD-0028 §6.3
 */

"use client";
// WHY "use client": useQuery, useAuth, useState, and useCallback require browser context.

import { useState, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { ScreenerTable, type SortState, type SortableKey } from "@/components/screener/ScreenerTable";
import type { ScreenerResult, ScreenerRequest } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

// WHY 100 (not 50): the instrument browser is for browsing the full universe.
// More rows = better browsability before the user needs to search. Virtual scroll
// keeps rendering fast regardless of row count.
const PAGE_SIZE = 100;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * sortResults — client-side sort on the loaded result set.
 * Mirrors the same sort logic in screener/page.tsx for consistent behavior.
 * WHY null → bottom: null values sort to the bottom in both asc and desc
 * directions. Users want data-rich rows first.
 */
function sortResults(results: ScreenerResult[], sort: SortState): ScreenerResult[] {
  if (!sort.key || !sort.dir) return results;

  const key = sort.key;
  const dir = sort.dir === "asc" ? 1 : -1;

  return [...results].sort((a, b) => {
    const av = a[key];
    const bv = b[key];

    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

// ── InstrumentsPage ───────────────────────────────────────────────────────────

export default function InstrumentsPage() {
  const { accessToken } = useAuth();

  // ── Search input state (controlled) ──────────────────────────────────────
  // WHY separate "inputValue" and "searchQuery": the query only fires on Enter
  // or after a short debounce — not on every keystroke. This prevents hammering
  // S9 while the user is still typing.
  const [inputValue, setInputValue] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // ── Debounce timer ref ────────────────────────────────────────────────────
  // WHY useRef (not state): debounce timer ID doesn't need to trigger re-renders.
  // WHY 400ms: long enough to avoid mid-word queries; short enough to feel responsive.
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Sort state ────────────────────────────────────────────────────────────
  const [sort, setSort] = useState<SortState>({ key: null, dir: null });

  // ── Column sort handler — cycle: none → asc → desc → none ─────────────────
  const handleSort = useCallback((key: SortableKey) => {
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      return { key: null, dir: null };
    });
  }, []);

  // ── Input change: update display value + debounce search query ────────────
  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    setInputValue(val);

    // Clear any existing debounce timer before setting a new one
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setSearchQuery(val.trim());
      // WHY reset sort on search change: sort state from the previous result
      // set is meaningless after a new query.
      setSort({ key: null, dir: null });
    }, 400);
  }

  // ── Enter key: commit search immediately (skip debounce wait) ─────────────
  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      setSearchQuery(inputValue.trim());
      setSort({ key: null, dir: null });
    }
  }

  // ── S9 screener query ─────────────────────────────────────────────────────
  // WHY use the screener endpoint (not search): the screener returns ScreenerResult
  // objects with entity_id, ticker, fundamentals — everything ScreenerTable needs.
  // The /v1/search/instruments endpoint returns a lightweight shape without
  // fundamentals data (no market_cap, P/E, etc.).
  const request: ScreenerRequest = {
    filters: searchQuery
      ? [{ field: "name_ticker", operator: "contains", value: searchQuery }]
      : [],  // WHY empty filters on no search: returns all instruments (full universe browse)
    limit: PAGE_SIZE,
    offset: 0,
  };

  const { data, isLoading, isFetching } = useQuery({
    // WHY searchQuery in key: search changes drive refetches; stable key for cache hits
    queryKey: ["instruments-browse", searchQuery],
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    // WHY 30s staleTime: instrument fundamentals change infrequently during a session.
    staleTime: 30_000,
  });

  const rawResults = data?.results ?? [];
  const totalResults = data?.total ?? 0;

  // WHY sort after fetch: client sort is instant for in-memory arrays
  const sortedResults = sortResults(rawResults, sort);

  return (
    // WHY h-full flex-col: page must fill the shell's main content area (flex-1
    // in layout.tsx). flex-col gives us the header + search bar + table layout.
    <div className="flex h-full min-h-0 flex-col">

      {/* ── Page heading ─────────────────────────────────────────────────── */}
      {/*
       * WHY 36px header (h-9): consistent with other terminal page headers.
       * Keeps the page chrome minimal so the table gets maximum vertical space.
       * WHY "INSTRUMENTS" label: differentiates this browse page from /screener
       * ("INSTRUMENT SCREENER"). Users navigating from the sidebar land here and
       * immediately understand they're on the browse page, not the advanced screener.
       */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Instruments
        </h1>
        {/* WHY static dot (no animate-pulse): §0.5 bans animate-pulse on status indicators */}
        {isFetching && !isLoading && (
          <span className="ml-2 h-1.5 w-1.5 rounded-full bg-primary shrink-0" aria-label="Loading" />
        )}
        {/* Result count — right-aligned, font-mono per §0 rules */}
        {!isLoading && (
          <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground/60">
            {totalResults.toLocaleString()} instruments
          </span>
        )}
      </div>

      {/* ── Search bar ────────────────────────────────────────────────────── */}
      {/*
       * WHY a simple search bar here (not the full ScreenerFilterBar):
       * ScreenerFilterBar adds sector/cap-tier dropdowns + an "Apply" button that
       * require an additional click to run the query. For instrument browsing/lookup,
       * the dominant workflow is "type ticker, press Enter, click row". The search bar
       * is deliberately simpler than the full screener to keep the interaction model
       * lightweight and familiar (Google-style search rather than SQL-style filter).
       */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3">
        {/* Search icon — decorative, left-anchored */}
        <Search className="h-[14px] w-[14px] shrink-0 text-muted-foreground/60" aria-hidden />

        <input
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="Search by ticker or name…"
          // WHY flex-1: input fills remaining width; all other row items are fixed size
          // WHY bg-transparent border-0 focus:outline-none: borderless input in the
          // header bar — the containing div already has a bottom border separator
          className="flex-1 bg-transparent text-[11px] font-mono text-foreground placeholder:text-muted-foreground/40 outline-none border-0 focus:ring-0"
          aria-label="Search instruments by ticker or name"
          // WHY autoComplete="off": prevents browser autocomplete from overlapping
          // the terminal UI's own dropdown (none exists here, but prevents layout bugs)
          autoComplete="off"
          spellCheck={false}
        />

        {/* Clear button — only visible when there is text */}
        {inputValue && (
          <button
            onClick={() => {
              setInputValue("");
              setSearchQuery("");
              setSort({ key: null, dir: null });
            }}
            className="shrink-0 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {/* ── 12-column virtualized table ───────────────────────────────────── */}
      {/*
       * WHY flex-1 min-h-0: the table fills remaining space after the header and
       * search bar. min-h-0 overrides the default flex min-height so the table
       * doesn't push outside the flex container.
       *
       * WHY ScreenerTable (not a custom table): ScreenerTable already has the
       * correct virtual-scroll implementation, 12-column layout, sort icons,
       * heat cells, and click-to-navigate to /instruments/{entity_id}. Reusing it
       * avoids duplicating ~200 lines of table rendering code.
       */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <ScreenerTable
          rows={sortedResults}
          isLoading={isLoading}
          sort={sort}
          onSort={handleSort}
        />
      </div>

    </div>
  );
}
