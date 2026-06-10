/**
 * components/shell/CommandPalette.tsx — Global ⌘K command palette.
 *
 * WHY THIS EXISTS: Terminal users navigate by keyboard. Bloomberg has <GO>,
 * Linear/Raycast have ⌘K — one chord that reaches every route, instrument and
 * conversation without touching the mouse. Before this component, ⌘K only
 * toggled the inline TopBar search dropdown (instruments only, anchored to a
 * 224px box). The palette generalises it into a centred modal with three groups:
 *
 *   1. Navigate              — every main app route, with its registry chord hint
 *   2. Instruments           — debounced type-ahead against S9 /v1/search/instruments
 *   3. Recent Conversations  — newest rag-chat threads via S9 /v1/threads
 *
 * OWNERSHIP OF ⌘K: This component registers the `mod+k` chord in
 * lib/hotkey-registry (id `shell.command.palette`) — it no longer owns a raw
 * document-level listener. GlobalSearch's old listener was REMOVED earlier
 * (two listeners on one chord would open both surfaces at once).
 *
 * WHY the registry (Round-3 polish, 2026-06-10): the original rationale for a
 * raw listener was "useChordHotkeys suspends chords while an <input> has
 * focus, but ⌘K must work everywhere — including while typing in the chat
 * composer". That rationale was WRONG: useChordHotkeys only suspends
 * modifier-LESS chords inside text inputs (`isTextInputActive() && !hasModifier`);
 * modifier-bearing chords like mod+k always pass through (pinned by the
 * "does NOT suspend modifier chords inside inputs" test in
 * __tests__/use-chord-hotkeys.test.tsx). Going through the registry buys us:
 *   1. The `?` cheat sheet (HotkeyCheatSheet) lists ⌘K automatically —
 *      single source of truth, no hardcoded duplicate hint anywhere.
 *   2. The no-lying invariant extends to ⌘K: the hint shown in the TopBar
 *      chip / cheat sheet IS the registered chord.
 *   3. Exactly one document keydown listener dispatches every chord.
 *
 * DECOUPLED OPEN TRIGGER: The TopBar's "⌘K" hint button dispatches the
 * `worldview:open-command-palette` CustomEvent instead of prop-drilling an
 * opener through layout → TopBar. This mirrors the established shell pattern
 * (`worldview:open-ai-panel`, `worldview:open-feedback`).
 *
 * RANKING: pure functions in lib/command-palette.ts (unit-tested separately) —
 * exact ticker match → ticker prefix → server order, with recently-visited
 * instruments floated within each tier.
 *
 * WHO USES IT: mounted ONCE in app/(app)/layout.tsx (available on every
 * authenticated route).
 * DATA SOURCES: S9 GET /v1/search/instruments (public), GET /v1/threads (auth).
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §6.15 Command Palette.
 */

"use client";
// WHY "use client": document keydown listeners, useState/useQuery/useRouter —
// all browser-only. The palette renders nothing on the server.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  BarChart3,
  Bell,
  Briefcase,
  CandlestickChart,
  Coins,
  Landmark,
  LayoutDashboard,
  LayoutGrid,
  MessageSquare,
  Newspaper,
  ScanSearch,
  Settings,
  Star,
  type LucideIcon,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useAuth } from "@/hooks/useAuth";
import { useDebounce } from "@/hooks/useDebounce";
// Round-3 polish: ⌘K is registered in the central hotkey registry (via the
// provider's contextual registry) instead of a raw document listener — see
// the "OWNERSHIP OF ⌘K" header block for the full rationale.
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { formatChordForDisplay } from "@/lib/hotkey-registry";
import { readRecentInstruments, saveRecentInstrument } from "@/lib/recent-instruments";
import {
  filterRecentThreads,
  matchesNavEntry,
  rankInstrumentResults,
  UNTITLED_THREAD_LABEL,
  type PaletteNavEntry,
} from "@/lib/command-palette";

// ── Open-event contract ────────────────────────────────────────────────────────

/**
 * CustomEvent name other shell components (TopBar ⌘K hint) dispatch to open the
 * palette. Exported so dispatchers reference the constant — a typo'd string
 * would silently do nothing.
 */
export const OPEN_COMMAND_PALETTE_EVENT = "worldview:open-command-palette";

// ── Navigate group data ────────────────────────────────────────────────────────

/**
 * Static route list — enumerated from app/(app)/ (2026-06-10). Chords mirror
 * GlobalHotkeyBindings registrations EXACTLY (no-lying invariant: the hint the
 * palette shows must be the chord the registry actually fires).
 *
 * WHY icon lives here (not in lib/command-palette.ts): lucide icons are React
 * components; the lib module stays React-free so its ranking functions can be
 * tested without a DOM.
 *
 * Intentionally excluded: /dev-tools (internal), /screen (legacy redirect of
 * /screener), /search (document search — reachable via News), dynamic detail
 * routes (covered by the Instruments group).
 */
interface NavItem extends PaletteNavEntry {
  readonly icon: LucideIcon;
}

const NAV_ITEMS: readonly NavItem[] = [
  { label: "Dashboard", path: "/dashboard", chord: "g d", icon: LayoutDashboard, keywords: ["home", "overview", "brief"] },
  { label: "Screener", path: "/screener", chord: "g s", icon: ScanSearch, keywords: ["filter", "scan", "stocks"] },
  { label: "Instruments", path: "/instruments", chord: "g i", icon: CandlestickChart, keywords: ["tickers", "symbols", "quotes"] },
  { label: "Portfolio", path: "/portfolio", chord: "g p", icon: Briefcase, keywords: ["holdings", "positions", "pnl"] },
  { label: "Portfolio › Transactions", path: "/portfolio/transactions", icon: ArrowLeftRight, keywords: ["trades", "orders", "history"] },
  { label: "Portfolio › Analytics", path: "/portfolio/analytics", icon: BarChart3, keywords: ["performance", "attribution", "risk"] },
  { label: "Portfolio › Brokerage", path: "/portfolio/brokerage", icon: Landmark, keywords: ["broker", "sync", "connections", "tastytrade", "snaptrade"] },
  { label: "Chat", path: "/chat", chord: "g c", icon: MessageSquare, keywords: ["ai", "assistant", "analyst", "ask"] },
  { label: "News", path: "/news", chord: "g n", icon: Newspaper, keywords: ["articles", "headlines", "feed"] },
  { label: "Alerts", path: "/alerts", chord: "g a", icon: Bell, keywords: ["notifications", "triggers"] },
  { label: "Watchlists", path: "/watchlists", icon: Star, keywords: ["favorites", "lists", "tracked"] },
  { label: "Workspace", path: "/workspace", chord: "g w", icon: LayoutGrid, keywords: ["panels", "terminal", "layout"] },
  { label: "Prediction Markets", path: "/prediction-markets", icon: Coins, keywords: ["polymarket", "odds", "probability"] },
  { label: "Settings", path: "/settings", chord: "g ,", icon: Settings, keywords: ["preferences", "profile", "account"] },
];

// ── Shared row styling (Terminal Dark density) ────────────────────────────────
// WHY centralised constants: the three groups must render at identical density.
// 11px primary text + 10px secondary matches the TopBar/StatusBar chrome scale
// (DESIGN_SYSTEM.md §3.1 — text-sm reads as consumer-app at terminal density).
const ITEM_CLASS = "cursor-pointer gap-2 px-2 py-1.5";
const PRIMARY_TEXT = "text-[11px] text-foreground";
const SECONDARY_TEXT = "min-w-0 flex-1 truncate text-[10px] text-muted-foreground";
const HINT_TEXT = "ml-auto shrink-0 font-mono text-[10px] text-muted-foreground/60";

// ── Component ──────────────────────────────────────────────────────────────────

export function CommandPalette() {
  const router = useRouter();
  const { accessToken } = useAuth();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  // WHY 250ms (matching GlobalSearch, PLAN-0050 T-F-6-14): the inflection point
  // where a 3-5 char ticker burst produces exactly one request without the
  // results feeling laggy. Nav-item filtering below uses the RAW query — it's
  // an in-memory filter over 14 rows, so debouncing it would only add lag.
  const debouncedQuery = useDebounce(query, 250);

  // ── CustomEvent open trigger (TopBar ⌘K hint button) ─────────────────────
  useEffect(() => {
    function onOpenEvent() {
      setOpen(true);
    }
    window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpenEvent);
    return () => window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpenEvent);
  }, []);

  // WHY reset query on close: reopening a palette with last session's stale
  // query pre-filtering everything is disorienting — Raycast/Linear both reset.
  // Radix calls onOpenChange(false) for Escape AND overlay click, so this is
  // the single close path.
  const handleOpenChange = useCallback((next: boolean) => {
    setOpen(next);
    if (!next) setQuery("");
  }, []);

  // ── ⌘K / Ctrl+K chord — registered in the central hotkey registry ─────────
  // WHY registry (not a raw document listener): see the "OWNERSHIP OF ⌘K"
  // header block. The registry's chord listener (useChordHotkeys, mounted by
  // GlobalHotkeyBindings in the same layout) lets modifier-bearing chords fire
  // even while a text input has focus, calls preventDefault on match (stops
  // Ctrl+K from focusing the browser location bar on Firefox/Chrome-Linux),
  // and feeds the `?` cheat sheet so ⌘K is listed without a hardcoded hint.
  //
  // WHY `open` in deps: register() is last-wins by id, so re-registering on
  // every open/close flip is cheap and keeps the handler's `!open` toggle
  // fresh. Routing the toggle through handleOpenChange (not bare setOpen)
  // guarantees the close path ALWAYS resets the query — same contract as
  // Escape/overlay-click (Radix onOpenChange).
  const { registry } = useHotkeyScope();
  useEffect(() => {
    return registry.register({
      id: "shell.command.palette",
      chord: "mod+k",
      scope: "global",
      // "Symbol" — the cheat-sheet group for search/symbol-lookup surfaces
      // (the HotkeyGroup taxonomy comment has reserved ⌘K here since W1).
      group: "Symbol",
      label: "Open command palette",
      handler: () => handleOpenChange(!open),
    });
  }, [registry, open, handleOpenChange]);

  // ── Instruments: debounced S9 search ─────────────────────────────────────
  // WHY the same queryKey as GlobalSearch ("instrument-search"): both surfaces
  // hit the same endpoint with the same params — sharing the key means a query
  // typed in the TopBar then retyped in the palette is a cache hit, not a
  // second network call.
  const trimmedQuery = debouncedQuery.trim();
  const { data: searchData, isFetching: isSearching } = useQuery({
    queryKey: ["instrument-search", trimmedQuery],
    queryFn: () => createGateway(accessToken).searchInstruments(trimmedQuery, 10),
    // WHY open && length>=1: never search while closed (palette may be mounted
    // for the whole session) and never fire the unfiltered ILIKE '%%' scan.
    enabled: open && trimmedQuery.length >= 1 && !!accessToken,
    staleTime: 30_000,
  });

  // ── Recent conversations: rag-chat threads via S9 ────────────────────────
  // WHY qk.chat.threads() (the chat page's own key): the palette is a READ-ONLY
  // consumer of the same thread list — sharing the key means opening the palette
  // right after visiting /chat costs zero network calls, and a thread renamed in
  // the chat sidebar shows its new title here immediately.
  const { data: threads } = useQuery({
    queryKey: qk.chat.threads(),
    queryFn: () => createGateway(accessToken).getThreads(),
    enabled: open && !!accessToken,
    staleTime: 60_000,
  });

  // ── Derived result sets ───────────────────────────────────────────────────
  // Recent instruments from localStorage — re-read each time the palette opens
  // (the list changes whenever the user navigates to an instrument).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const recentInstruments = useMemo(() => readRecentInstruments(), [open]);

  const navMatches = useMemo(
    () => NAV_ITEMS.filter((item) => matchesNavEntry(item, query)),
    [query],
  );

  // Ranked instrument results: tiers (exact → prefix → rest), recency-boosted.
  const instrumentResults = useMemo(
    () =>
      rankInstrumentResults(
        searchData?.results ?? [],
        trimmedQuery,
        recentInstruments.map((r) => r.entityId),
      ),
    [searchData, trimmedQuery, recentInstruments],
  );

  const conversationMatches = useMemo(
    () => filterRecentThreads(threads ?? [], query, 5),
    [threads, query],
  );

  // WHY hasTypedQuery gates the Instruments group on the RAW query: while the
  // 250ms debounce is pending, debouncedQuery is still empty but the user is
  // already typing — showing the (stale) recent-instruments rows during that
  // window makes results appear to "flash". Raw query flips the group to
  // search-mode instantly; rows appear when the debounced fetch lands.
  const hasTypedQuery = query.trim().length > 0;

  // ── Selection handlers ────────────────────────────────────────────────────
  // WHY close BEFORE push: router.push is async; closing first guarantees the
  // dialog never lingers over the destination page during the transition.
  const runAndClose = useCallback(
    (action: () => void) => {
      handleOpenChange(false);
      action();
    },
    [handleOpenChange],
  );

  const goToInstrument = useCallback(
    (entityId: string, ticker: string, name: string, instrumentId?: string) =>
      runAndClose(() => {
        // Persist to the shared recents stack (same store GlobalSearch and
        // TickerPicker use) so all three surfaces agree on "recent".
        saveRecentInstrument(entityId, ticker, name, instrumentId);
        // ADR-F-12: always route by entity_id (instrument_id ≠ entity_id).
        router.push(`/instruments/${entityId}`);
      }),
    [router, runAndClose],
  );

  const goToThread = useCallback(
    (threadId: string) =>
      runAndClose(() => {
        // NOTE (Round-1 contract): /chat does not yet read ?thread= — the chat
        // surface owns that page and wires the param in its own round. Until
        // then this lands on /chat with the thread list visible; the param is
        // forward-compatible and harmless.
        router.push(`/chat?thread=${encodeURIComponent(threadId)}`);
      }),
    [router, runAndClose],
  );

  return (
    <CommandDialog
      open={open}
      onOpenChange={handleOpenChange}
      title="Command palette"
      description="Search pages, instruments and recent conversations"
      // WHY shouldFilter={false}: every rendered item already passed OUR
      // filtering (matchesNavEntry / server search / filterRecentThreads).
      // cmdk's built-in fuzzy filter would re-match against the namespaced
      // item values ("inst:<uuid>") and hide everything as soon as the user
      // types. Same rule as GlobalSearch.
      shouldFilter={false}
      // WHY top-anchored + translate-y-0: command palettes pin near the top of
      // the viewport so the list grows DOWNWARD as results stream in — a
      // vertically-centred dialog would jump up/down on every keystroke.
      // WHY [&>button]:hidden: DialogContent ships an absolute X close button
      // that would overlap the input row; Escape/overlay-click are the palette's
      // close affordances (Linear/Raycast convention).
      // WHY rounded-[2px]: Terminal Dark 2px-radius rule (DESIGN_SYSTEM.md §4).
      contentClassName="top-[20%] max-w-xl translate-y-0 rounded-[2px] border-border p-0 [&>button]:hidden"
      // Override CommandDialog's consumer-scale defaults down to terminal
      // density: 32px input @ 12px text, compact 1.5/3.5 icon rows.
      commandClassName="[&_[cmdk-input]]:h-9 [&_[cmdk-input]]:text-[12px] [&_[cmdk-item]]:py-1.5 [&_[cmdk-item]_svg]:h-3.5 [&_[cmdk-item]_svg]:w-3.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em]"
    >
      <CommandInput
        placeholder="Type a page, ticker or conversation…"
        value={query}
        onValueChange={setQuery}
        aria-label="Command palette search"
      />

      {/* sr-only live region: announce instrument result count to screen
          readers as results stream in (same WCAG pattern as GlobalSearch). */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {hasTypedQuery && instrumentResults.length > 0
          ? `${instrumentResults.length} instrument${instrumentResults.length === 1 ? "" : "s"} found`
          : ""}
      </span>

      {/* WHY max-h-[420px] (default is 300px): three groups need more vertical
          room; 420px keeps the footer hint strip on screen at 768px-tall laptops. */}
      <CommandList className="max-h-[420px]">
        {/* WHY conditional CommandEmpty: with shouldFilter left ON cmdk would
            show Empty automatically, but we filter ourselves (shouldFilter is
            irrelevant since every rendered item already matched). cmdk's Empty
            renders whenever zero items exist — which is exactly what we want,
            but the message differs while a search is in flight. */}
        <CommandEmpty className="py-4 text-[11px]">
          {isSearching ? "Searching…" : "No results. Try a ticker like AAPL."}
        </CommandEmpty>

        {/* ── 1. Navigate ─────────────────────────────────────────────────── */}
        {navMatches.length > 0 && (
          <CommandGroup heading="Navigate">
            {navMatches.map((item) => (
              <CommandItem
                key={item.path}
                // WHY value prefix "nav:": cmdk requires unique values across
                // ALL groups; a route path could theoretically collide with an
                // entity id, so each group namespaces its values.
                value={`nav:${item.path}`}
                // WHY BOTH onSelect and onClick: cmdk's onSelect fires on
                // keyboard Enter; mouse clicks only fire onSelect when the item
                // is the highlighted one. The dual-handler pattern is this
                // repo's proven fix (SEARCH-001, see GlobalSearch.tsx header).
                onSelect={() => runAndClose(() => router.push(item.path))}
                onClick={() => runAndClose(() => router.push(item.path))}
                className={ITEM_CLASS}
              >
                <item.icon strokeWidth={1.5} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className={PRIMARY_TEXT}>{item.label}</span>
                {/* Chord hint — teaches the faster two-key shortcut passively.
                    formatChordForDisplay renders "G D" / "⌘B" per platform. */}
                {item.chord && <span className={HINT_TEXT}>{formatChordForDisplay(item.chord)}</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {/* ── 2. Instruments ──────────────────────────────────────────────── */}
        {/* Empty query → recent instruments from localStorage (Bloomberg-style
            "last 5 you visited"); typed query → ranked live search results. */}
        {!hasTypedQuery && recentInstruments.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Recent Instruments">
              {recentInstruments.map((recent) => (
                <CommandItem
                  key={`recent:${recent.entityId}`}
                  value={`recent:${recent.entityId}`}
                  onSelect={() => goToInstrument(recent.entityId, recent.ticker, recent.name, recent.instrumentId)}
                  onClick={() => goToInstrument(recent.entityId, recent.ticker, recent.name, recent.instrumentId)}
                  className={ITEM_CLASS}
                >
                  {/* WHY font-mono tabular-nums for tickers: fixed-width glyphs
                      keep the ticker column visually aligned across rows. */}
                  <span className="shrink-0 font-mono text-[11px] font-medium tabular-nums text-foreground">
                    {recent.ticker}
                  </span>
                  <span className={SECONDARY_TEXT}>{recent.name}</span>
                  <span className={HINT_TEXT}>recent</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {hasTypedQuery && instrumentResults.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Instruments">
              {instrumentResults.map((result) => (
                <CommandItem
                  key={`inst:${result.entity_id}`}
                  value={`inst:${result.entity_id}`}
                  onSelect={() => goToInstrument(result.entity_id, result.ticker, result.name, result.instrument_id)}
                  onClick={() => goToInstrument(result.entity_id, result.ticker, result.name, result.instrument_id)}
                  className={ITEM_CLASS}
                >
                  <span className="shrink-0 font-mono text-[11px] font-medium tabular-nums text-foreground">
                    {result.ticker}
                  </span>
                  <span className={SECONDARY_TEXT}>{result.name}</span>
                  {result.exchange && <span className={HINT_TEXT}>{result.exchange}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {/* ── 3. Recent Conversations ─────────────────────────────────────── */}
        {conversationMatches.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Recent Conversations">
              {conversationMatches.map((thread) => (
                <CommandItem
                  key={`thread:${thread.thread_id}`}
                  value={`thread:${thread.thread_id}`}
                  onSelect={() => goToThread(thread.thread_id)}
                  onClick={() => goToThread(thread.thread_id)}
                  className={ITEM_CLASS}
                >
                  <MessageSquare strokeWidth={1.5} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className={`${PRIMARY_TEXT} min-w-0 truncate`}>
                    {thread.title ?? UNTITLED_THREAD_LABEL}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>

      {/* ── Footer hint strip ─────────────────────────────────────────────── */}
      {/* Same keyboard-hint footer as GlobalSearch's dropdown — terminal users
          expect the legend; new users learn the keys from it. */}
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
    </CommandDialog>
  );
}
