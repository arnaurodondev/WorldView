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
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";

export default function PortfolioTransactionsPage() {
  const { accessToken } = useAuth();
  const [connectModalOpen, setConnectModalOpen] = useState(false);

  // WHY selectedPeriod = "1D": same lock as the main page (T-B-2-07). The period
  // is only used by usePortfolioData for the performance query — irrelevant here
  // but the hook requires it. Using "1D as const" keeps the type narrow.
  const selectedPeriod = "1D" as const;
  const {
    activePortfolioId,
    activePortfolio,
    txLoading,
    transactionsResp,
    holdingOverviews,
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
      />

      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}
    </div>
  );
}
