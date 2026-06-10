/**
 * app/(app)/portfolio/transactions/page.tsx — Transactions sub-page stub.
 *
 * WHY THIS EXISTS: W2 removes the tabs from /portfolio, moving TransactionsTab
 * to its own route. This stub renders the existing TransactionsTab component
 * at /portfolio/transactions. The "T" hotkey on /portfolio navigates here.
 * WHO USES IT: PMs who want a full-height transaction history view.
 * DATA SOURCE: Same as TransactionsTab — fetches from S9 portfolio routes.
 * DESIGN REFERENCE: PRD-0089 W2 §4.20, V15
 */
"use client";
// WHY "use client": useState (modal open/close), usePortfolioData hook.

import { useAuth } from "@/hooks/useAuth";
import { useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";

// R1 sprint: lazy-load the AddPositionDialog exactly like the main portfolio
// page does — it pulls in react-hook-form + zod + a Radix portal that are only
// needed after the empty-state CTA is clicked. ssr:false because the Radix
// Dialog portal needs a browser DOM; loading: null because the dialog starts
// closed (nothing would be visible during the chunk load anyway).
const AddPositionDialog = dynamic(
  () =>
    import("@/features/portfolio/components/AddPositionDialog").then((m) => ({
      default: m.AddPositionDialog,
    })),
  { ssr: false, loading: () => null },
);

export default function PortfolioTransactionsPage() {
  const { accessToken } = useAuth();
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  // R1 sprint: empty-state "Add your first transaction" CTA opens this dialog.
  const [addPositionOpen, setAddPositionOpen] = useState(false);

  // WHY selectedPeriod = "1D": same lock as the main page (T-B-2-07). The period
  // is only used by usePortfolioData for the performance query — irrelevant here
  // but the hook requires it. Using "1D as const" keeps the type narrow.
  const selectedPeriod = "1D" as const;
  const {
    activePortfolioId,
    activePortfolio,
    activeIsRoot,
    txLoading,
    transactionsResp,
    setTxOffset,
    holdingOverviews,
    handlePositionAdded,
  } = usePortfolioData({ accessToken, selectedPeriod });

  return (
    <div className="flex flex-col h-full min-h-0 bg-background">
      {/* Page header with back link */}
      <div className="flex h-[36px] shrink-0 items-center border-b border-border bg-card px-3 gap-3">
        <Link href="/portfolio" className="font-mono text-[10px] text-muted-foreground hover:text-foreground">← Portfolio</Link>
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Transactions</span>
      </div>

      <TransactionsTab
        activePortfolioId={activePortfolioId}
        txLoading={txLoading}
        transactionsResp={transactionsResp}
        holdingOverviews={holdingOverviews}
        onConnect={() => setConnectModalOpen(true)}
        // R1 sprint: same wiring as the main page — the CTA is hidden on the
        // read-only ROOT aggregate (S1 rejects manual transactions there).
        onAddPosition={
          activeIsRoot ? undefined : () => setAddPositionOpen(true)
        }
        // R1 sprint: server-side pager (offset is part of the hook's queryKey).
        onTxOffsetChange={setTxOffset}
      />

      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}

      {/* ── R1 sprint: Add Position dialog (empty-state CTA target) ─────── */}
      {activePortfolioId && (
        <AddPositionDialog
          open={addPositionOpen}
          onOpenChange={setAddPositionOpen}
          onSuccess={() => {
            setAddPositionOpen(false);
            // handlePositionAdded invalidates holdings + transactions +
            // quotes + performance + bundle so the new BUY shows up
            // immediately in the table below.
            handlePositionAdded();
          }}
          portfolioId={activePortfolioId}
          accessToken={accessToken}
        />
      )}
    </div>
  );
}
