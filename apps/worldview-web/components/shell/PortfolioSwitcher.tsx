/**
 * components/shell/PortfolioSwitcher.tsx — Always-visible TopBar chip + dropdown.
 *
 * WHY THIS EXISTS: PRD-0089 DISCUSS-1 locked the "ROOT default" model — the
 *   aggregated household view ("All Portfolios") is always selectable, even
 *   when the user has a single portfolio (per FU-1.1 — switcher is ALWAYS
 *   visible). Without this chip the user has no surface to flip between an
 *   aggregated NAV and a single-account NAV, and demo portfolios cannot be
 *   visually distinguished from real ones (no DemoBadge anchor).
 *
 * WHO USES IT: components/shell/TopBar.tsx (single slot between GlobalSearch
 *   and IndexStrip).
 *
 * DATA SOURCE:
 *   - `getPortfolios()` once per 5 min (PRD §5 cadence). Cached via the
 *     existing `qk.portfolios.list()` key so other consumers share the fetch.
 *
 * DESIGN REFERENCE: PRD-0089 W1 plan §4.2.
 *   - Chip label: "All Portfolios ▾" when ROOT active; portfolio name otherwise.
 *   - 240px dropdown popover, Tier-2 animation (≤200ms opacity+scale).
 *   - ROOT pinned to top, hairline separator below, 28px rows.
 *   - Hotkey Alt+P toggles the dropdown.
 *   - `<DemoBadge />` rendered immediately right of the chip when the
 *     active portfolio's `kind === "demo"`.
 *
 * NOTE ON DEMO KIND: the current Portfolio.kind union is "manual" | "brokerage"
 *   | "root". The DemoBadge gating below uses a forward-compatible string
 *   comparison so when "demo" is introduced as a fourth kind it lights up
 *   automatically — no further code change required here.
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only), local React state for
// the popover, useEffect to register the Alt+P chord, and direct DOM event
// listeners for click-outside. None of these are SSR-safe.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { useActivePortfolio } from "@/contexts/ActivePortfolioContext";
import { DemoBadge } from "@/components/primitives/DemoBadge";
import { cn } from "@/lib/utils";
import type { Portfolio } from "@/types/api";

// ── Constants ──────────────────────────────────────────────────────────────

/** Sentinel value for the ROOT (All Portfolios) selection. The context stores
 *  this as `null`; we map to/from this sentinel inside the component so the
 *  existing UI logic (== ROOT_SENTINEL → "All Portfolios" label) stays clean.
 */
const ROOT_SENTINEL = "__root__";

// ── Component ──────────────────────────────────────────────────────────────

export function PortfolioSwitcher() {
  const router = useRouter();
  const { accessToken, isAuthenticated } = useAuth();
  const { registry } = useHotkeyScope();
  // W1.1 F-002 — selection now lives in ActivePortfolioContext so the
  // chip's pick is readable by usePortfolioMetrics and any future
  // portfolio-scoped widget. Context fallback (noop) keeps this component
  // testable outside the provider.
  const { activePortfolioId, setActivePortfolio } = useActivePortfolio();
  const activeId = activePortfolioId ?? ROOT_SENTINEL;
  const [open, setOpen] = useState(false);

  // ── Portfolio list (cached via the existing qk.portfolios.list namespace) ─
  // 5 min staleTime per PRD §5: portfolio membership rarely changes.
  const { data: portfolios } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken && isAuthenticated,
    staleTime: 5 * 60_000,
  });

  // Find the ROOT portfolio (if present). PLAN-0046 auto-provisions a ROOT
  // portfolio per user but old/test fixtures may not have one — when missing
  // we surface a synthetic ROOT row that simply selects "no specific id".
  const rootPortfolio = useMemo(
    () => portfolios?.find((p) => p.kind === "root") ?? null,
    [portfolios],
  );

  // Non-ROOT portfolios — these are the entries below the hairline separator.
  const ownedPortfolios = useMemo(
    () => (portfolios ?? []).filter((p) => p.kind !== "root"),
    [portfolios],
  );

  // The Portfolio currently identified by `activeId` (null when ROOT).
  // WHY active resolution: chip label / DemoBadge gating both need it.
  const activePortfolio: Portfolio | null = useMemo(() => {
    if (activeId === ROOT_SENTINEL) return rootPortfolio;
    return ownedPortfolios.find((p) => p.portfolio_id === activeId) ?? null;
  }, [activeId, ownedPortfolios, rootPortfolio]);

  // Chip label — "All Portfolios ▾" for ROOT, the portfolio name otherwise.
  // Falls back to "All Portfolios ▾" while data is loading so the chip width
  // does not jump on hydrate.
  const chipLabel = activeId === ROOT_SENTINEL ? "All Portfolios" : activePortfolio?.name ?? "All Portfolios";

  // Demo gating — forward-compat string compare so the future "demo" kind
  // lights up the badge without a code change here.
  const isDemo = (activePortfolio?.kind as string | undefined) === "demo";

  // ── Selection handler ────────────────────────────────────────────────────
  // Writes through the context; the context handles localStorage persistence.
  const select = useCallback(
    (id: string) => {
      setOpen(false);
      setActivePortfolio(id === ROOT_SENTINEL ? null : id);
    },
    [setActivePortfolio],
  );

  // ── Alt+P hotkey ─────────────────────────────────────────────────────────
  // Register on mount, unregister on unmount via the returned cleanup. Uses
  // the chord registry (not a raw window listener) so the chord is discoverable
  // via the `?` cheat-sheet and respects scope precedence (modal > global).
  useEffect(() => {
    return registry.register({
      id: "shell.portfolio.switcher.toggle",
      chord: "alt+p",
      scope: "global",
      group: "View",
      label: "Toggle portfolio switcher",
      handler: () => setOpen((prev) => !prev),
    });
  }, [registry]);

  // ── Click-outside-to-close ───────────────────────────────────────────────
  const wrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div ref={wrapperRef} className="relative flex h-full items-center gap-1.5">
      {/*
        Chip — always visible per FU-1.1 (even with a single portfolio).
        h-6 (24px) keeps it inside the 32px TopBar with breathing room.
        No border-radius: F1 lockdown (DISCUSS-3 / plan C-15).
      */}
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch active portfolio"
        className="flex h-6 items-center gap-1 border border-border bg-muted/20 px-2 font-mono text-[11px] text-foreground hover:bg-muted/40"
        data-testid="portfolio-switcher-chip"
      >
        <span className="max-w-[140px] truncate">{chipLabel}</span>
        <span aria-hidden className="text-[10px] text-muted-foreground">▾</span>
      </button>

      {/* DemoBadge anchored immediately right of the chip per FU-1.5. */}
      {isDemo && <DemoBadge />}

      {/*
        Dropdown popover — 240px wide (plan §4.2). Tier-2 animation budget
        (≤200ms) via Tailwind's `transition-opacity duration-150 ease-out`.
        z-50 keeps it above sidebar drag handle (z-40) but below FlashOverlay
        (z-50 + manual ordering).
      */}
      {open && (
        <div
          role="listbox"
          aria-label="Portfolio list"
          className="absolute left-0 top-full z-50 mt-1 w-[240px] border border-border bg-card shadow-none transition-opacity duration-150 ease-out"
          data-testid="portfolio-switcher-popover"
        >
          {/* Section header per design — uppercase 10px tracking-wide. */}
          <div className="px-2 py-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Portfolios
          </div>

          {/*
            ROOT row pinned to the top with a hairline separator below it.
            Rendered even when no actual root entity exists in the DB so the
            "All Portfolios" semantics is always reachable — selecting it
            simply tells consumers "do not scope to one portfolio".
          */}
          <button
            type="button"
            role="option"
            aria-selected={activeId === ROOT_SENTINEL}
            onClick={() => select(ROOT_SENTINEL)}
            className={cn(
              "flex h-7 w-full items-center justify-between px-2 text-left font-mono text-[11px] hover:bg-muted/40",
              activeId === ROOT_SENTINEL && "text-primary",
            )}
            data-testid="portfolio-switcher-root-row"
          >
            <span>All Portfolios</span>
            {activeId === ROOT_SENTINEL && <span aria-hidden>✓</span>}
          </button>

          {/* Hairline below the ROOT row (per plan §4.2). */}
          <div className="border-t border-border-subtle" aria-hidden />

          {/* Individual portfolios. Empty list → instructional copy. */}
          {ownedPortfolios.length === 0 ? (
            <div className="px-2 py-2 text-[11px] text-muted-foreground">
              No portfolios yet —
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  router.push("/portfolio");
                }}
                className="ml-1 text-primary hover:underline"
              >
                connect a brokerage →
              </button>
            </div>
          ) : (
            ownedPortfolios.map((p) => (
              <button
                key={p.portfolio_id}
                type="button"
                role="option"
                aria-selected={activeId === p.portfolio_id}
                onClick={() => select(p.portfolio_id)}
                className={cn(
                  "flex h-7 w-full items-center justify-between px-2 text-left font-mono text-[11px] hover:bg-muted/40",
                  activeId === p.portfolio_id && "text-primary",
                )}
              >
                <span className="truncate">{p.name}</span>
                {activeId === p.portfolio_id && <span aria-hidden>✓</span>}
              </button>
            ))
          )}

          {/*
            Footer CTA: "+ New portfolio" — modal UX deferred to v1.1, so we
            simply route to the portfolio page where the user can add one via
            the existing flow. Keeps the chip useful day-one.
          */}
          <div className="border-t border-border-subtle" aria-hidden />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              router.push("/portfolio");
            }}
            className="flex h-7 w-full items-center px-2 text-left font-mono text-[11px] text-muted-foreground hover:text-foreground"
          >
            + New portfolio
          </button>
        </div>
      )}
    </div>
  );
}
