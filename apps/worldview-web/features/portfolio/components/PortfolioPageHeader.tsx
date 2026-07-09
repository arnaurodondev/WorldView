/**
 * features/portfolio/components/PortfolioPageHeader.tsx — Portfolio page chrome.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the portfolio page held ~170 LOC
 * of header markup (portfolio selector, position-count badge, three action
 * buttons, the F-021 scope-hint sub-line). Lifting it into a stateless
 * component keeps the page focused on data orchestration, and makes the
 * header trivially testable in isolation (no TanStack provider needed).
 *
 * BEHAVIOR PARITY: every conditional rendering rule, ARIA label, and
 * tooltip from the prior inline implementation is preserved verbatim.
 *
 * WHO USES IT: only the portfolio page (`/portfolio`).
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio.
 */

"use client";
// WHY "use client": this component renders Radix DropdownMenu (which uses
// browser portals + keyboard-event listeners) and binds onClick handlers.

import { ChevronDown, Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
// PRD-0114 W5-T08: ROOT portfolio onboarding popover — renders an ℹ icon next
// to the "All Accounts" label in the selector and header, explaining what the
// aggregate view is and why it's read-only.
import { RootPortfolioPopover } from "@/components/portfolio/RootPortfolioPopover";
// PLAN-0122 W-A: the Simple|Advanced detail-level toggle lives in the header
// action row. WHY the header owns the hook (not the toggle): usePortfolioMode
// touches nuqs + localStorage; keeping it here leaves PortfolioModeToggle a pure
// presentational control that unit-tests without a router.
import { PortfolioModeToggle } from "@/components/portfolio/PortfolioModeToggle";
import { usePortfolioMode } from "@/hooks/usePortfolioMode";
import type { Portfolio } from "@/types/api";

interface PortfolioPageHeaderProps {
  /** Sorted portfolios (ROOT first) for the selector dropdown. */
  sortedPortfolios: Portfolio[] | undefined;
  /** Currently active portfolio (for the trigger label + ALL badge). */
  activePortfolio: Portfolio | undefined;
  /** Currently active portfolio id (for the menu item highlight). */
  activePortfolioId: string | null;
  /** True when the active portfolio is the kind=root aggregate. */
  activeIsRoot: boolean;
  /** Number of enriched holdings — drives the position-count badge. */
  holdingCount: number;
  /** F-021 scope hint sub-line. Null hides the entire 24px row. */
  scopeHint: string | null;

  // ── Action callbacks ───────────────────────────────────────────────────
  /** Switch the active portfolio (writes to selectedPortfolioId state). */
  onSelectPortfolio: (portfolioId: string) => void;
  /** Open the AddPositionDialog (only invoked when not root). */
  onAddPosition: () => void;
  /** Open the CreatePortfolioDialog. */
  onCreatePortfolio: () => void;
  /** Open the DeletePortfolioDialog (only invoked when not root). */
  onDeletePortfolio: () => void;
}

export function PortfolioPageHeader({
  sortedPortfolios,
  activePortfolio,
  activePortfolioId,
  activeIsRoot,
  holdingCount,
  scopeHint,
  onSelectPortfolio,
  onAddPosition,
  onCreatePortfolio,
  onDeletePortfolio,
}: PortfolioPageHeaderProps) {
  // PLAN-0122 W-A: resolve the current detail level (Simple | Advanced). The
  // header is the single call site of the hook for the page chrome; the value is
  // threaded to child surfaces as a prop from page.tsx (this instance only drives
  // the toggle's own checked state + writes on click).
  const { mode, setMode } = usePortfolioMode();

  return (
    <>
      {/* ── Page header ─────────────────────────────────────────────────── */}
      {/* WHY h-9 shrink-0: 36px header is the terminal standard. shrink-0
          prevents flexbox from compressing the header to make room for tab
          content. WHY bg-card: the page is bg-background (#09090B); the
          header needs the panel tone (#111113) to read as the chrome row
          at the top of the workspace. */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3 gap-3 bg-card">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Portfolio
        </h1>

        {/* Portfolio selector — only shown when user has multiple portfolios.
            WHY hidden for single portfolio: a dropdown with one item is just
            clutter. The active portfolio name is shown in the position-count
            badge instead. */}
        {sortedPortfolios && sortedPortfolios.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-1.5 text-[11px] font-mono text-foreground"
              >
                {/* PLAN-0046 Wave 3 / T-46-3-04 — show "ALL" badge inline next
                    to the trigger label when the active portfolio is the root.
                    Makes the aggregate view immediately recognisable without
                    opening the menu. */}
                {activePortfolio?.name ?? "Select portfolio"}
                {activeIsRoot && (
                  <span
                    className="ml-1 rounded-[2px] border border-primary/60 bg-primary/10 px-1 py-px text-[9px] font-mono uppercase tracking-[0.06em] text-primary"
                    aria-label="Aggregate portfolio"
                  >
                    ALL
                  </span>
                )}
                {/* WHY strokeWidth={1.5}: Lucide default 2 reads as too heavy in terminal chrome */}
                <ChevronDown className="h-3 w-3 opacity-60" strokeWidth={1.5} />
                {/* PRD-0114 W5-T08: ℹ popover shown inline in the trigger when
                    active portfolio is root. Stop propagation so clicking ℹ
                    opens the Popover without also toggling the dropdown. */}
                {activeIsRoot && (
                  <span
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex"
                  >
                    <RootPortfolioPopover portfolioKind="root" />
                  </span>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {sortedPortfolios.map((p) => (
                <DropdownMenuItem
                  key={p.portfolio_id}
                  onClick={() => onSelectPortfolio(p.portfolio_id)}
                  className={cn(
                    // WHY text-[11px]: terminal data row density — text-xs (12px) is
                    // Bloomberg-inappropriate for dropdown menu items in the portfolio selector.
                    "font-mono text-[11px] flex items-center gap-1.5",
                    p.portfolio_id === activePortfolioId &&
                      "text-primary font-medium",
                  )}
                >
                  {p.name}
                  {/* Per-row ALL badge: keeps the root recognisable inside the
                      menu even when another portfolio is currently active. */}
                  {p.kind === "root" && (
                    <>
                      <span
                        className="rounded-[2px] border border-primary/60 bg-primary/10 px-1 py-px text-[9px] font-mono uppercase tracking-[0.06em] text-primary"
                        aria-label="Aggregate portfolio — All Accounts"
                      >
                        ALL
                      </span>
                      {/* PRD-0114 W5-T08: ℹ per-row in dropdown for root entries */}
                      <span
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex"
                      >
                        <RootPortfolioPopover portfolioKind="root" />
                      </span>
                    </>
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Position count — quick glance at book size. */}
        {holdingCount > 0 && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {holdingCount} positions
          </span>
        )}

        {/* WHY ml-auto: push the action buttons to the right side, matching
            Bloomberg convention of left=labels, right=actions. */}
        <div className="ml-auto flex items-center gap-2">
          {/* PLAN-0122 W-A: detail-level toggle, positioned at the LEFT of the
              action cluster (before Add Position) per PRD §6.1. WHY here and not
              in the empty-portfolio early-return: that branch shows no data, so a
              Simple/Advanced switch would have nothing to gate. */}
          <PortfolioModeToggle mode={mode} onModeChange={setMode} />

          {/* "Add Position" — only useful when there's an active portfolio.
              PLAN-0046 Wave 3 / T-46-3-04: also disabled when active is ROOT
              (S1 rejects POST /v1/transactions on root portfolios with HTTP
              400 CANNOT_RECORD_TRANSACTION_ON_ROOT). */}
          {activePortfolioId && (
            <button
              aria-label={
                activeIsRoot
                  ? "Cannot add positions directly to the aggregate portfolio"
                  : "Add a new position to this portfolio"
              }
              title={
                activeIsRoot
                  ? "Switch to a specific portfolio to add a position. The aggregate view is read-only."
                  : undefined
              }
              onClick={() => {
                if (!activeIsRoot) onAddPosition();
              }}
              disabled={activeIsRoot}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] flex items-center gap-1 transition-colors",
                activeIsRoot
                  ? "border-border/40 text-muted-foreground/40 cursor-not-allowed"
                  : "border-border text-muted-foreground hover:border-primary/60 hover:text-primary hover:bg-primary/5",
              )}
            >
              {/* WHY strokeWidth={1.5}: Lucide default 2 reads as too heavy in terminal chrome */}
              <Plus className="h-3 w-3" strokeWidth={1.5} />
              Add Position
            </button>
          )}

          {/* "New Portfolio" — always visible so users can create their first
              portfolio even when they have none yet. */}
          <button
            aria-label="Create a new portfolio"
            onClick={onCreatePortfolio}
            className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors flex items-center gap-1"
          >
            {/* WHY strokeWidth={1.5}: Lucide default 2 reads as too heavy in terminal chrome */}
            <Plus className="h-3 w-3" strokeWidth={1.5} />
            New Portfolio
          </button>

          {/* F-013 (QA 2026-04-28): Delete button. WHY disabled for ROOT: the
              S1 backend rejects archive on the aggregate
              (RootPortfolioNotArchivableError). The tooltip explains why so
              the affordance is honest about the constraint. */}
          {activePortfolioId && (
            <button
              aria-label={
                activeIsRoot
                  ? "Cannot delete the aggregate portfolio"
                  : "Delete this portfolio"
              }
              title={
                activeIsRoot
                  ? "Cannot delete the aggregate portfolio"
                  : undefined
              }
              onClick={() => {
                if (!activeIsRoot) onDeletePortfolio();
              }}
              disabled={activeIsRoot}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] flex items-center gap-1 transition-colors",
                activeIsRoot
                  ? "border-border/40 text-muted-foreground/40 cursor-not-allowed"
                  : "border-border text-muted-foreground hover:border-negative/60 hover:text-negative",
              )}
            >
              {/* WHY strokeWidth={1.5}: Lucide default 2 reads as too heavy in terminal chrome */}
              <Trash2 className="h-3 w-3" strokeWidth={1.5} />
              Delete
            </button>
          )}
        </div>
      </div>

      {/* ── ROOT read-only hint ─────────────────────────────────────────── */}
      {/* WHY: the Add Position button is silently disabled for root portfolios.
          Without explanation, users may think it's a bug. This one-liner makes
          the constraint explicit (T-5-01 / PLAN-0108 W5). Only shown when the
          active portfolio is the aggregate root. */}
      {activeIsRoot && (
        <p className="text-[10px] text-muted-foreground mt-0.5">
          Select a portfolio to add positions. ALL is read-only.
        </p>
      )}

      {/* ── F-021: scope hint sub-line ──────────────────────────────────── */}
      {/* WHY h-6 (24px): a thin secondary row below the main header keeps
          context in the user's eye-line without taking visual weight away
          from the primary actions above. Hidden when null (manual portfolios)
          so we don't introduce a phantom empty bar. */}
      {scopeHint && (
        <div className="h-6 shrink-0 px-3 flex items-center border-b border-border/60 bg-muted/10">
          <span className="text-[10px] text-muted-foreground font-mono tabular-nums">
            {scopeHint}
          </span>
        </div>
      )}
    </>
  );
}
