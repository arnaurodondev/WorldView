/**
 * features/portfolio/components/PortfolioPageHeader.tsx — Portfolio page chrome.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the portfolio page held ~170 LOC
 * of header markup (portfolio selector, position-count badge, three action
 * buttons, the F-021 scope-hint sub-line). Lifting it into a stateless
 * component keeps the page focused on data orchestration, and makes the
 * header trivially testable in isolation (no TanStack provider needed).
 *
 * W2 CHANGES (PRD-0089 W2 §4.1):
 *   - Removed the inline DropdownMenu portfolio selector — portfolio selection
 *     is now owned by the W1 TopBar PortfolioSwitcher, so the in-page duplicate
 *     is redundant and adds confusion when both widgets are visible.
 *   - "Add Position" is now hidden (not just disabled) when activeIsRoot=true.
 *     WHY: a disabled button that silently does nothing is an affordance lie.
 *     Hiding it when ROOT communicates cleanly "this action isn't available here".
 *   - Deprecated props kept as optional to avoid breaking the existing call
 *     site in portfolio/page.tsx until step 4.19 rewrites the page.
 *
 * WHO USES IT: only the portfolio page (`/portfolio`).
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio, PRD-0089 W2 §4.1.
 */

"use client";
// WHY "use client": binds onClick handlers on buttons.

import { Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Portfolio } from "@/types/api";

interface PortfolioPageHeaderProps {
  /**
   * @deprecated W2: selection moved to W1 TopBar PortfolioSwitcher.
   * Kept optional so the existing call site compiles until page.tsx is
   * rewritten in step 4.19.
   */
  sortedPortfolios?: Portfolio[] | undefined;
  /**
   * @deprecated W2: not needed after removing the inline dropdown.
   */
  activePortfolio?: Portfolio | undefined;
  /** Currently active portfolio id (used for scoping actions). */
  activePortfolioId: string | null;
  /** True when the active portfolio is the kind=root aggregate. */
  activeIsRoot: boolean;
  /** Number of enriched holdings — drives the position-count badge. */
  holdingCount: number;
  /** F-021 scope hint sub-line. Null hides the entire 24px row. */
  scopeHint: string | null;

  // ── Action callbacks ───────────────────────────────────────────────────
  /**
   * @deprecated W2: selection moved to W1 TopBar PortfolioSwitcher.
   */
  onSelectPortfolio?: (portfolioId: string) => void;
  /** Open the AddPositionDialog. Only rendered when not root (W2 change). */
  onAddPosition: () => void;
  /** Open the CreatePortfolioDialog. */
  onCreatePortfolio: () => void;
  /** Open the DeletePortfolioDialog (only invoked when not root). */
  onDeletePortfolio: () => void;
}

export function PortfolioPageHeader({
  activePortfolioId,
  activeIsRoot,
  holdingCount,
  scopeHint,
  onAddPosition,
  onCreatePortfolio,
  onDeletePortfolio,
}: PortfolioPageHeaderProps) {
  return (
    <>
      {/* ── Page header ─────────────────────────────────────────────────── */}
      {/* WHY h-[36px] shrink-0: 36px header is the terminal standard. shrink-0
          prevents flexbox from compressing the header to make room for tab
          content. WHY bg-card: the page is bg-background (#09090B); the
          header needs the panel tone (#111113) to read as the chrome row
          at the top of the workspace. */}
      <div className="flex h-[36px] shrink-0 items-center border-b border-border px-3 gap-3 bg-card">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Portfolio
        </h1>

        {/* Position count — quick glance at book size. */}
        {holdingCount > 0 && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {holdingCount} positions
          </span>
        )}

        {/* WHY ml-auto: push the action buttons to the right side, matching
            Bloomberg convention of left=labels, right=actions. */}
        <div className="ml-auto flex items-center gap-2">
          {/* "Add Position" — W2: hidden entirely when ROOT (not just disabled).
              WHY: a disabled button that silently does nothing is an affordance
              lie. ROOT portfolios reject POST /v1/transactions at the API layer
              (HTTP 400 CANNOT_RECORD_TRANSACTION_ON_ROOT), so hiding the button
              communicates the constraint honestly. */}
          {activePortfolioId && !activeIsRoot && (
            <button
              aria-label="Add a new position to this portfolio"
              onClick={onAddPosition}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] flex items-center gap-1 transition-colors",
                "border-border text-muted-foreground hover:border-primary/60 hover:text-primary",
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
