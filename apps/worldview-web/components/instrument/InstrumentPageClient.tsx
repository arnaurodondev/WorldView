/**
 * components/instrument/InstrumentPageClient.tsx — Instrument Detail page shell (Wave A)
 *
 * WHY THIS EXISTS (PLAN-0090 T-A-05): the previous monolithic page.tsx mixed
 * server-side params handling, client-side data fetching, tab state, hotkeys,
 * skeleton, cache-priming, and resizable panels in one ~525-line file. The
 * redesign (PRD-0088) replaces that with a 3-tab structure (Quote / Financials
 * / Intelligence) and a slim client component. This shell:
 *   1. Owns the active-tab state.
 *   2. Fetches the page-bundle once via useInstrumentBundle().
 *   3. Seeds the per-section TanStack Query caches so child tab components
 *      paint from cache on first mount (PRD-0088 §6.3).
 *   4. Composes the new InstrumentHeader / AiBriefBanner / InstrumentTabs
 *      components (T-A-04) and the Wave A placeholder tab contents.
 *
 * WHY SPLIT INTO SERVER + CLIENT: page.tsx remains a Next.js 15 Server
 * Component (just unwraps the `params` Promise). Everything that needs
 * browser APIs (useState, useEffect, TanStack Query, useRouter) lives here
 * under "use client".
 *
 * LINE LIMIT: this file must stay ≤200 lines per PLAN-0090 T-A-05.
 */

"use client";
// WHY "use client": this component uses useState (activeTab), useEffect
// (entityId guard + cache seeding), useRouter / useQueryClient (browser-only
// React contexts), and the useInstrumentBundle TanStack Query hook. All of
// these require the React client runtime.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query/keys";
import { useInstrumentBundle } from "@/components/instrument/hooks/useInstrumentBundle";
import { InstrumentHeader } from "@/components/instrument/header/InstrumentHeader";
import { AiBriefBanner } from "@/components/instrument/brief/AiBriefBanner";
import { InstrumentTabs } from "@/components/instrument/tabs/InstrumentTabs";
import { FinancialsTab } from "@/components/instrument/financials/FinancialsTab";
// WHY direct import (no `next/dynamic`): IntelligenceTab itself is a thin
// orchestrator; its heavy children (NewsColumn list, GraphColumn → sigma.js)
// are the ones that need code-splitting and they already dynamic-import their
// own dependencies. Loading the tab itself eagerly avoids a layout flash when
// the analyst hits the Intelligence tab the first time.
import { IntelligenceTab } from "@/components/instrument/intelligence/IntelligenceTab";
import { QuoteTab } from "@/components/instrument/quote/QuoteTab";

// ── Public props ─────────────────────────────────────────────────────────────
//
// WHY just entityId: the server component pulls the URL param and hands the
// pre-resolved string in. This keeps the client-side `useParams` indirection
// out of the redesigned page (one fewer ambient dependency to mock in tests).

export interface InstrumentPageClientProps {
  /** Authoritative KG entity_id from the URL segment. */
  readonly entityId: string;
}

// ── Tab union ────────────────────────────────────────────────────────────────
//
// WHY a string union (not enum): TabsTrigger components in InstrumentTabs.tsx
// (T-A-04) are typed with the same literal union. Sharing string literals
// keeps the controlled-Tabs `value`/`onValueChange` plumbing type-safe.

type ActiveTab = "quote" | "financials" | "intelligence";

export function InstrumentPageClient({ entityId }: InstrumentPageClientProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // ── Active tab state ──────────────────────────────────────────────────────
  // WHY controlled (not Tabs `defaultValue`): later waves may need to switch
  // tabs programmatically (e.g. an "Open in Intelligence" deep-link from
  // Quote). Controlled state from day one avoids a future refactor.
  const [activeTab, setActiveTab] = useState<ActiveTab>("quote");

  // ── entityId === "undefined" guard ────────────────────────────────────────
  // WHY this guard exists: PLAN-0052 platform-QA round 7 (BP-302) — broken
  // link generators (notably an early screener-row bug) produced URLs like
  // /instruments/undefined. The literal slug "undefined" hits the page-bundle
  // endpoint and returns 200 with synthetic data, so the page renders a fake
  // instrument. Redirecting to the list route is the safe behaviour.
  useEffect(() => {
    if (!entityId || entityId === "undefined") {
      router.replace("/instruments");
    }
  }, [entityId, router]);

  // ── Bundle fetch (T-A-03) ─────────────────────────────────────────────────
  // The hook owns the queryKey (qk.instruments.pageBundle), staleTime, and
  // gateway wiring. We only consume its data here; tab components handle
  // their own loading UI via the per-section query hooks.
  const { data: bundle } = useInstrumentBundle(entityId);

  // ── Cache priming (PRD-0088 §6.3) ─────────────────────────────────────────
  // We seed the per-section query caches so when a tab content component
  // mounts and runs its own useQuery, TanStack Query returns the cached
  // payload immediately and skips the network round-trip. The dedicated
  // hooks remain authoritative for refetch/invalidation semantics — this
  // setQueryData call only PRIMES the cache.
  useEffect(() => {
    if (!bundle) return;
    const instrumentId = bundle.instrument_id;

    // WHY overview seed: child Quote-tab components read overview via
    // qk.instruments.overview to render price + instrument metadata.
    if (bundle.overview) {
      queryClient.setQueryData(qk.instruments.overview(entityId), bundle.overview);
    }

    // WHY technicals seed: TechnicalSnapshot / chart toolbar widgets read
    // qk.instruments.technicals(instrumentId). The bundle returns the same
    // shape as the standalone /technicals endpoint so seeding is safe.
    if (bundle.technicals) {
      queryClient.setQueryData(qk.instruments.technicals(instrumentId), bundle.technicals);
    }

    // WHY insider/ownership seed: the Quote-tab "Recent Insider Transactions"
    // strip and Ownership panels read qk.instruments.ownership(instrumentId).
    if (bundle.insider) {
      queryClient.setQueryData(qk.instruments.ownership(instrumentId), bundle.insider);
    }

    // WHY NOT fundamentals (BP-379): the bundle's `fundamentals` field is a
    // raw FundamentalsSectionResponse (section-records array). The
    // qk.instruments.fundamentals cache key (consumed by getFundamentals()
    // → useMetricsTableData) expects the flat `Fundamentals` shape produced
    // by the client-side transformer. Seeding the wrong shape locks the
    // cache for the entire staleTime window (~1hr) and the Financials/Quote
    // tabs render all "—". The fundamentals hook fires its own fetch.
    // PLAN-0099 follow-up G note: we considered flattening here to address
    // BP-379 but the transformer lives inside getFundamentals() in
    // lib/api/instruments.ts (highlights + valuation_ratios + analyst_consensus
    // + technicals_snapshot merge) — duplicating that here would risk
    // divergence. Skipped per task instructions; keeps BP-379 behaviour intact.

    // PLAN-0099 follow-up G (audit Q1): seed fundamentalsSnapshot +
    // shareStatistics caches so useMetricsTableData (Quote tab) finds them
    // pre-warmed on first paint, eliminating 2 RTTs. The cache keys
    // (qk.instruments.fundamentalsSnapshot / .shareStatistics) MUST match
    // the keys read by useMetricsTableData.ts:67-89 verbatim — otherwise
    // the Quote tab fires the network calls anyway.
    if (bundle.fundamentals_snapshot) {
      queryClient.setQueryData(
        qk.instruments.fundamentalsSnapshot(instrumentId),
        bundle.fundamentals_snapshot,
      );
    }
    // WHY share_statistics: same shape as the dedicated
    // /v1/fundamentals/{id}/share-statistics endpoint (FundamentalsSectionResponse).
    // getShareStatistics() returns the response verbatim — no transformer —
    // so seeding the bundle leg directly is safe.
    if (bundle.share_statistics) {
      queryClient.setQueryData(
        qk.instruments.shareStatistics(instrumentId),
        bundle.share_statistics,
      );
    }
  }, [bundle, entityId, queryClient]);

  // ── Layout ────────────────────────────────────────────────────────────────
  // WHY flex column + h-screen: the page must fill the viewport so the active
  // tab pane can scroll inside its own box (min-h-0 + overflow-hidden on the
  // child container). overflow-hidden on the outer element prevents the whole
  // page from scrolling — only the active tab's content scrolls.
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background">
      {/* Sticky header: ticker + price + key stats (T-A-04). InstrumentHeader
          expects the three sub-resources, not the full bundle, so it can keep
          its prop surface narrow and unit-testable. We fall back to null while
          the bundle is loading — the header renders "—" placeholders rather
          than collapsing layout. */}
      {/* AUDIT 2026-05-20: render unconditionally so the 36px sticky row never
          disappears mid-fetch. InstrumentHeader handles `instrument: null` with
          "—" fallbacks and skips the LiveQuoteBadge subscription until the id
          is known. */}
      <InstrumentHeader
        instrument={bundle?.overview?.instrument ?? null}
        quote={bundle?.overview?.quote ?? null}
        fundamentals={bundle?.overview?.fundamentals ?? null}
      />

      {/* AI brief banner: returns null when no brief is available, so the
          banner area disappears cleanly with no reserved space. */}
      <AiBriefBanner entityId={entityId} />

      {/* Controlled 3-tab nav (Quote / Financials / Intelligence). The
          Q/F/I mnemonic hotkeys live inside InstrumentTabs (T-A-04) — the
          legacy D/F/N/I bindings from the old page have been removed. */}
      <InstrumentTabs activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Active-tab content. WHY min-h-0 overflow-hidden: lets each tab's
          own component own its scroll container (e.g. the Quote tab chart
          will have its own internal scroll area in Wave B). */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {/* QUOTE tab (T-B-04): chart left + MetricsTable right.
            WHY the prop fallbacks (`?? ""`, `?? null`): the bundle is null
            during the initial fetch. QuoteTab tolerates empty instrumentId
            (its children gate on `enabled` flags) so we can render an empty
            shell rather than a flash of placeholder text. */}
        {activeTab === "quote" && (
          <QuoteTab
            instrumentId={bundle?.instrument_id ?? ""}
            entityId={entityId}
            fundamentals={bundle?.overview?.fundamentals ?? null}
            quote={bundle?.overview?.quote ?? null}
            initialBars={bundle?.overview?.ohlcv?.bars}
            bundle={bundle ?? null}
          />
        )}
        {/* Wave C: Financials tab orchestrator (T-C-03). WHY guard on the
            bundle's instrument_id: FinancialsTab keys all its fetches off the
            S9 instrument_id (NOT entityId — the KG entity id can't address
            /v1/fundamentals/*). Until the page-bundle resolves, no fetches
            should fire — pass undefined-coerced empty string makes useQuery's
            enabled flag false. */}
        {/* PLAN-0089 W3 T-25: FinancialsTab now receives instrument + entityId
            for the 7-panel sidebar (CompanySnapshotPanel needs Instrument fields;
            AIBriefPanel needs entityId for the briefing endpoint). Post-F2,
            entityId === instrumentId for all new instruments. */}
        {activeTab === "financials" && (
          <FinancialsTab
            instrumentId={bundle?.instrument_id ?? ""}
            entityId={entityId}
            instrument={bundle?.overview?.instrument ?? null}
            quote={bundle?.overview?.quote ?? null}
          />
        )}
        {/* Wave D: Intelligence tab (T-D-04) — 3-column orchestrator
            (NewsColumn | GraphColumn | ContextPanel). All data fetching lives
            inside the children, so this slot only needs the entityId. */}
        {activeTab === "intelligence" && (
          <IntelligenceTab entityId={entityId} />
        )}
      </div>
    </div>
  );
}
