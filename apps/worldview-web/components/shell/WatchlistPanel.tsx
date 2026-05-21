/**
 * components/shell/WatchlistPanel.tsx — Sidebar watchlist with live prices,
 * trend-tinted sparklines, and per-row freshness dots.
 *
 * WHY THIS EXISTS: Institutional traders glance at their watchlist constantly
 *   during market hours. Embedding it in the sidebar means it's always visible
 *   without leaving the current page — Bloomberg's persistent monitor panel.
 *   PRD-0089 W1 adds the sparkline column (trend signal beyond the chg% number)
 *   and a server-driven freshness dot so stale prices don't lie.
 *
 * WHO USES IT: components/shell/CollapsibleSidebar.tsx (expanded state only).
 *
 * DATA SOURCE:
 *   - `getWatchlists()` (cached 30 s) — member list
 *   - `getBatchQuotes(ids)` every 30 s — price / chg% / `freshness_status`
 *   - `getBatchOhlcvBars({ tickers, timeframe: "5m", limit: 78 })` every 60 s —
 *     1-day intraday closes for the sparkline column. 78 bars = 6.5h × 12/h.
 *
 * DESIGN REFERENCE: PRD-0089 W1 plan §4.5 + design §6 (sidebar watchlist row).
 *   Row layout: Ticker 44px / Price flex-1 / Chg% 44px / FreshnessDot / Sparkline 40×16.
 *   Click → /instruments/{ticker} (NOT entity_id — F2 lock C-08).
 *   "+N more →" → /watchlists (NOT /portfolio?tab=watchlists — C-09).
 *   `mod+shift+w` → open add-flow (FU-4.4) — stubbed as toast in W1.
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only), router push for
// navigation, hotkey-registry for mod+shift+w, refs for click-outside and
// for the dropdown's fixed-position math.

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { qk } from "@/lib/query/keys";
import { Sparkline } from "@/components/primitives/Sparkline";
import { FreshnessDot } from "@/components/primitives/FreshnessDot";
import { priceChangeClass, formatPercentDirect, cn } from "@/lib/utils";
import type { Quote, WatchlistMember } from "@/types/api";

// ── Constants ──────────────────────────────────────────────────────────────

/** Max symbols shown in the sidebar — surplus shows "+N more →". */
const MAX_ROWS = 10;

/**
 * Map the server-driven Quote.freshness_status enum onto the FreshnessDot
 * primitive's narrower 4-value vocabulary. Without this mapping the dot would
 * misrender "delayed" or "unavailable" rows.
 */
type FreshnessDotStatus = "live" | "stale" | "closed" | "after-hours";
function quoteFreshnessToDot(
  status: Quote["freshness_status"] | undefined,
): FreshnessDotStatus {
  switch (status) {
    case "live":
    case "recent":
      return "live";
    case "delayed":
    case "stale":
      return "stale";
    case "unavailable":
      return "closed";
    default:
      // No `freshness_status` populated → safest default is "closed" (grey).
      return "closed";
  }
}

// ── Component ──────────────────────────────────────────────────────────────

export function WatchlistPanel() {
  const { accessToken } = useAuth();
  const router = useRouter();
  const { registry } = useHotkeyScope();

  // ── Active-watchlist selection state ───────────────────────────────────
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // ── Refs for the dropdown's fixed positioning + click-outside detection ─
  const dropdownRef = useRef<HTMLDivElement>(null);
  const dropdownListRef = useRef<HTMLDivElement>(null);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; right: number } | null>(null);

  const handleClickOutside = useCallback((e: MouseEvent) => {
    const target = e.target as Node;
    const insideTrigger = dropdownRef.current?.contains(target) ?? false;
    const insideList = dropdownListRef.current?.contains(target) ?? false;
    if (!insideTrigger && !insideList) setDropdownOpen(false);
  }, []);

  useEffect(() => {
    if (!dropdownOpen) return;
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [dropdownOpen, handleClickOutside]);

  // Compute fixed position when the dropdown opens — escapes overflow-hidden
  // sidebar ancestors so the list does not get clipped.
  const openDropdown = useCallback(() => {
    if (dropdownRef.current) {
      const rect = dropdownRef.current.getBoundingClientRect();
      setDropdownPos({
        top: rect.bottom + 2,
        right: window.innerWidth - rect.right,
      });
    }
    setDropdownOpen(true);
  }, []);

  // ── mod+shift+w → open add-flow ────────────────────────────────────────
  // Add-flow modal UX is deferred to a later wave (Watchlists page). For W1
  // the chord is wired so muscle memory works; it surfaces a "coming soon"
  // toast and routes to the new /watchlists stub where the user can manage.
  useEffect(() => {
    return registry.register({
      id: "shell.watchlist.add",
      chord: "mod+shift+w",
      scope: "global",
      group: "Action",
      label: "Add to watchlist",
      handler: () => {
        toast("Add-to-watchlist modal coming soon", {
          description: "Use /watchlists to manage members for now.",
        });
        router.push("/watchlists");
      },
    });
  }, [registry, router]);

  // ── Watchlist list (cached 30 s) ───────────────────────────────────────
  // NOTE: the S1 list endpoint deliberately omits members for performance
  // (per `lib/api/watchlists.ts` doc). `activeWatchlist.members` is ALWAYS
  // an empty array here — we resolve real members via the dependent query
  // below. Without that second call the sidebar shows the empty state even
  // when the watchlist has stocks (BP-W1-001 / QA F-003 in
  // `docs/audits/2026-05-21-qa-w1-visual-regressions-report.md`).
  const { data: watchlistsData } = useQuery({
    queryKey: qk.watchlists.sidebar(),
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // Resolve active watchlist (metadata only — members come from the next query).
  const activeWatchlist =
    watchlistsData?.find((wl) => wl.watchlist_id === selectedWatchlistId) ??
    watchlistsData?.[0];
  const activeWatchlistId = activeWatchlist?.watchlist_id;

  // ── Active-watchlist members (dependent on activeWatchlistId) ────────
  // Reuses the existing `qk.watchlists.members(id)` key so other consumers
  // (the future /watchlists hub member panel, etc.) hit the same cache.
  // 60s staleTime — watchlist membership rarely changes mid-session.
  const { data: activeMembers } = useQuery({
    queryKey: qk.watchlists.members(activeWatchlistId ?? ""),
    queryFn: () => createGateway(accessToken).getWatchlistMembers(activeWatchlistId!),
    enabled: !!accessToken && !!activeWatchlistId,
    staleTime: 60_000,
  });

  const members: WatchlistMember[] = activeMembers ?? [];
  const memberIds = members.map((m) => m.entity_id);
  const memberTickers = members.map((m) => m.ticker).filter((t): t is string => !!t);

  // ── Batch quotes (30 s refetch) ────────────────────────────────────────
  const { data: quotesData } = useQuery({
    queryKey: qk.watchlists.quotes(memberIds),
    queryFn: () => createGateway(accessToken).getBatchQuotes(memberIds),
    enabled: memberIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });
  const quotes = quotesData?.quotes ?? {};

  // ── Sparkline OHLCV batch (60 s refetch) ───────────────────────────────
  // 5-min bars × 78 = full US trading day (6.5h × 12). The batch endpoint is
  // capped at ~100 instruments per call (PLAN-0049) — we never approach that
  // limit in the sidebar (MAX_ROWS = 10) so a single call always suffices.
  const { data: sparkData } = useQuery({
    queryKey: qk.instruments.ohlcvBatch(memberTickers, "5m", 78),
    queryFn: () =>
      createGateway(accessToken).getBatchOhlcvBars({
        instrument_ids: memberIds,
        timeframe: "5m",
        limit: 78,
      }),
    enabled: memberIds.length > 0 && !!accessToken,
    refetchInterval: 60_000,
    staleTime: 60_000,
  });
  // Build instrument-id → close-prices[] lookup so per-row sparkline render
  // is O(1).
  const sparklineByEntityId: Record<string, number[]> = {};
  for (const r of sparkData?.results ?? []) {
    sparklineByEntityId[r.instrument_id] = r.bars.map((b) => b.close);
  }

  const displayMembers = members.slice(0, MAX_ROWS);
  const extraCount = Math.max(0, members.length - MAX_ROWS);
  const isLoading = !watchlistsData;

  return (
    <div className="flex flex-col overflow-hidden">
      {/* ── Section header ────────────────────────────────────────────── */}
      {/*
        W1.1 G-002 — single-line header fix. Pre-fix at narrow sidebar
        widths the WATCHLIST label + watchlist name wrapped to two
        lines (e.g. "Tech Watchlist ▾" pushed below "WATCHLIST"). The
        fix forces the row to one line:
          • `gap-2` between label and button so they always sit side-by-side
          • The label is `shrink-0` (never compressed)
          • The button wrapper is `min-w-0 flex-1` so its inner text can
            actually shrink and the inner span gets `truncate` + a max
            ch-width — names longer than the slot render as "Tech Wat…".
        The chevron stays outside the truncating span so it never gets
        clipped along with the name.
      */}
      <div className="flex h-6 shrink-0 items-center justify-between gap-2 border-b border-border border-t border-t-border px-2">
        <span className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          WATCHLIST
        </span>
        {/* Watchlist dropdown switcher — clicking the header opens a 200px
            popover listing all watchlists + "+ New" CTA (plan §4.5). */}
        {activeWatchlist && (
          <div className="relative min-w-0 flex-1" ref={dropdownRef}>
            <button
              onClick={() => (dropdownOpen ? setDropdownOpen(false) : openDropdown())}
              className="flex w-full items-center justify-end gap-1 whitespace-nowrap font-mono text-[10px] text-muted-foreground transition-colors duration-0 hover:text-foreground"
              aria-label={`Switch watchlist (current: ${activeWatchlist.name})`}
              aria-expanded={dropdownOpen}
              title={activeWatchlist.name}
            >
              <span className="min-w-0 truncate">{activeWatchlist.name}</span>
              <span aria-hidden className="shrink-0">▾</span>
            </button>

            {dropdownOpen && watchlistsData && watchlistsData.length > 0 && dropdownPos && (
              <div
                ref={dropdownListRef}
                style={{
                  position: "fixed",
                  top: dropdownPos.top,
                  right: dropdownPos.right,
                  zIndex: 9999,
                }}
                // 200px wide per plan §4.5 (was 160px — bumped to fit longer
                // watchlist names without truncation in the popover).
                className="max-h-[240px] w-[200px] overflow-y-auto border border-border bg-card"
              >
                {watchlistsData.map((wl) => (
                  <button
                    key={wl.watchlist_id}
                    onClick={() => {
                      setSelectedWatchlistId(wl.watchlist_id);
                      setDropdownOpen(false);
                    }}
                    className={cn(
                      "w-full px-2 py-1 text-left text-[11px] transition-colors duration-0 hover:bg-muted/40",
                      activeWatchlist.watchlist_id === wl.watchlist_id
                        ? "font-medium text-primary"
                        : "text-foreground",
                    )}
                  >
                    {wl.name}
                  </button>
                ))}
                {/* "+ New watchlist" CTA — modal UX deferred; routes to the
                    new /watchlists stub for now. */}
                <button
                  onClick={() => {
                    setDropdownOpen(false);
                    router.push("/watchlists");
                  }}
                  className="w-full border-t border-border px-2 py-1 text-left text-[10px] text-muted-foreground transition-colors duration-0 hover:text-foreground"
                >
                  + New watchlist
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Column header (W1.1 H-002 / user feedback Image #6) ─────────
          A 14 px label row immediately under the section header. Without
          it the numeric columns are unlabelled and the user has to
          remember which column is price vs change. Uses the same column
          widths as the data rows below so the labels line up exactly
          above their values. Uppercase 9 px mono mirrors the rest of the
          terminal's data-table headers (matches the convention in
          `components/portfolio/TransactionsTable.tsx`). */}
      <div className="flex h-[14px] shrink-0 items-center gap-1 border-b border-border/30 px-2 text-[9px] uppercase tracking-wide text-muted-foreground/70">
        <span className="w-[44px] shrink-0">Tkr</span>
        <span className="flex-1 text-right">Price</span>
        <span className="w-[44px] shrink-0 text-right">%Chg</span>
        {/* Spacer cells aligned with the FreshnessDot + Sparkline columns
            in the data rows so the label row reserves the same total
            width and the section header doesn't expand or shift. */}
        <span aria-hidden className="inline-block h-[6px] w-[6px]" />
        <span aria-hidden className="inline-block" style={{ width: 40 }} />
      </div>

      {/* ── Symbol rows ───────────────────────────────────────────────── */}
      {/*
        WHY data-table-grid: the F1 design-system grid sets `--row-h: 20px`
        on this attribute so descendant rows inherit the dense row height
        without extra Tailwind classes (per plan C-01).
      */}
      <div data-table-grid className="divide-y divide-border/30 overflow-y-auto">
        {isLoading ? (
          // 5 skeleton rows at 20px so the sidebar height doesn't jump.
          Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="flex h-[20px] items-center px-2"
              aria-hidden
              data-testid="watchlist-skeleton-row"
            >
              <span className="h-2 w-full bg-muted/30" />
            </div>
          ))
        ) : displayMembers.length === 0 ? (
          <p className="px-2 py-1 text-[11px] text-muted-foreground">
            Add symbols in{" "}
            <button
              onClick={() => router.push("/watchlists")}
              className="text-primary hover:underline"
            >
              Watchlists
            </button>
          </p>
        ) : (
          displayMembers.map((member) => {
            const quote = quotes[member.entity_id];
            const sparkData = sparklineByEntityId[member.entity_id] ?? [];
            // PRD-0089 W1 §4.5 / C-08 — ticker URL form, NOT entity_id.
            // Fall back to instrument_id then UUID only when ticker is null
            // (the middleware then resolves alias → canonical).
            const href = `/instruments/${member.ticker || member.instrument_id || member.entity_id}`;
            return (
              <div
                key={member.entity_id}
                className="flex h-[20px] cursor-pointer items-center gap-1 px-2 hover:bg-muted/40"
                onClick={() => router.push(href)}
                aria-label={`${member.ticker ?? member.entity_id} — view instrument detail`}
              >
                {/* Ticker — 44px fixed-width mono */}
                <span className="w-[44px] shrink-0 truncate font-mono text-[11px] tabular-nums text-foreground">
                  {member.ticker ?? member.entity_id.slice(0, 6)}
                </span>
                {/* Price — right-aligned mono, "—" until quote resolves */}
                <span className="flex-1 text-right font-mono text-[11px] tabular-nums text-foreground">
                  {quote != null ? quote.price.toFixed(2) : "—"}
                </span>
                {/* Chg% — colored by sign per F1 token */}
                <span
                  className={`w-[44px] shrink-0 text-right font-mono text-[11px] tabular-nums ${
                    quote != null
                      ? priceChangeClass(quote.change_pct)
                      : "text-muted-foreground"
                  }`}
                >
                  {quote != null ? formatPercentDirect(quote.change_pct) : "—"}
                </span>
                {/* Freshness dot — server-driven per FU-4.1. The mapper
                    collapses the 5-value Quote enum onto the 4-value
                    FreshnessDot vocabulary so the primitive contract stays
                    narrow. */}
                <FreshnessDot status={quoteFreshnessToDot(quote?.freshness_status)} />
                {/* Sparkline — 40×16, trend-tinted ("auto" delegates trend
                    direction to the primitive's ±0.1% threshold per FU-5.6). */}
                <Sparkline data={sparkData} trend="auto" width={40} height={16} />
              </div>
            );
          })
        )}

        {/* ── "+N more →" link (plan §4.5 / C-09) ──────────────────── */}
        {extraCount > 0 && (
          <button
            onClick={() => router.push("/watchlists")}
            className="w-full px-2 py-0.5 text-left text-[10px] text-muted-foreground transition-colors duration-0 hover:text-foreground"
          >
            +{extraCount} more →
          </button>
        )}
      </div>
    </div>
  );
}
