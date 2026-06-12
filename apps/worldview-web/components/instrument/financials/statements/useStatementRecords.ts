/**
 * components/instrument/financials/statements/useStatementRecords.ts
 * Data source for the Financial Statements section — bundle-first with a
 * Wave-1 dedicated-endpoint fallback.
 *
 * WHY THIS HOOK EXISTS (Wave-2 redesign): the statements section needs the
 * raw income_statement / balance_sheet / cash_flow records. TWO sources
 * exist:
 *
 *   1. The financials-bundle `fundamentals` leg (POST /v1/fundamentals/{id}/
 *      financials-bundle) — the all-sections payload the tab ALREADY fetches
 *      via useFinancialsBundle. Verified live 2026-06-10 (AAPL): the leg
 *      carries 163 quarterly balance_sheet + 146 quarterly cash_flow +
 *      204 income_statement records. Reading it here dedupes by query key →
 *      ZERO extra round-trips on the happy path.
 *
 *   2. The Wave-1 dedicated endpoints — GET /v1/fundamentals/{id}/
 *      income-statement, /balance-sheet, /cash-flow. These fire ONLY when
 *      the bundle cannot answer (request failed, or the `fundamentals` leg
 *      degraded to null server-side).
 *
 * WHY THE FALLBACK MATTERS (fixes a Round-4 known dishonesty): the old
 * FinancialStatementsPanel admitted it "cannot distinguish 'leg errored'
 * from 'no records' client-side" and rendered the NO-DATA empty state for a
 * failed leg. With the dedicated endpoints we now CAN resolve that
 * ambiguity: leg null → probe the endpoints; records → render them; empty →
 * the empty state is finally honest; all failed → named error with Retry.
 *
 * WHO USES IT: StatementsSection.tsx (and nothing else — the hook's return
 * shape is tailored to that panel's four render states).
 */

"use client";
// WHY "use client": useQuery requires the TanStack QueryClient context.

import { useQuery } from "@tanstack/react-query";

import { useFinancialsBundle } from "@/components/instrument/hooks/useFinancialsBundle";
import { apiFetch } from "@/lib/api/_client";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { FundamentalsRecord, FundamentalsSectionResponse } from "@/types/api";

// ── Wave-1 fetchers ──────────────────────────────────────────────────────────
// Plain functions under financials/** (the sprint contract: new fetchers the
// Financials agent needs do NOT go into lib/api/instruments.ts — that module
// is owned by the Quote agent this wave).

/** GET /v1/fundamentals/{id}/balance-sheet — quarterly records (Wave-1). */
export function fetchBalanceSheet(
  token: string | null | undefined,
  instrumentId: string,
): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/balance-sheet`,
    { token: token ?? undefined },
  );
}

/** GET /v1/fundamentals/{id}/cash-flow — quarterly records (Wave-1). */
export function fetchCashFlow(
  token: string | null | undefined,
  instrumentId: string,
): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/cash-flow`,
    { token: token ?? undefined },
  );
}

/** GET /v1/fundamentals/{id}/income-statement — annual + quarterly records. */
export function fetchIncomeStatement(
  token: string | null | undefined,
  instrumentId: string,
): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/income-statement`,
    { token: token ?? undefined },
  );
}

// Statements change on filing cadence (quarterly) — 24h staleness is plenty
// for the fallback queries (matches the bundle legs' own staleness ceiling).
const STALE_24H = 24 * 60 * 60 * 1000;

// ── Return shape ─────────────────────────────────────────────────────────────

export interface StatementRecordsResult {
  /** Merged raw records (all three sections), or null while unresolved. */
  records: readonly FundamentalsRecord[] | null;
  /** True during the cold first load of whichever source is active. */
  isLoading: boolean;
  /** True only when BOTH the bundle AND the fallback path failed. */
  isError: boolean;
  /** Retry the failed source(s) — wired to the panel's Retry button. */
  refetch: () => void;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useStatementRecords(instrumentId: string): StatementRecordsResult {
  const token = useAccessToken();

  // Source 1 — the composite bundle (deduped against useFinancialsTabData's
  // identical call: same query key, same render tree → one HTTP request).
  const bundleQuery = useFinancialsBundle(instrumentId);

  // The bundle leg is typed `unknown` (generated types not re-rolled); the
  // runtime shape is the S3 all-sections FundamentalsResponse — the same
  // contract the per-section endpoints use.
  const bundleLeg = (bundleQuery.data?.fundamentals ?? null) as FundamentalsSectionResponse | null;
  const bundleRecords = bundleLeg?.records ?? null;

  // Fallback trigger: bundle settled but could not answer. NOT triggered by
  // an empty-but-present records array — that is a genuine "no statements".
  const needFallback =
    !bundleQuery.isLoading && (bundleQuery.isError || (bundleQuery.data != null && bundleLeg == null));

  // Source 2 — Wave-1 dedicated endpoints, one query per statement.
  // WHY qk.instruments.incomeStatement for the income leg: that key is the
  // canonical one (useFinancialsTabData also owns it) → free dedupe if the
  // tab's own income query already resolved despite the bundle failing.
  const incomeQuery = useQuery({
    queryKey: qk.instruments.incomeStatement(instrumentId),
    queryFn: () => fetchIncomeStatement(token, instrumentId),
    staleTime: STALE_24H,
    enabled: needFallback && !!instrumentId,
  });
  const balanceQuery = useQuery({
    queryKey: [...qk.instruments.detail(instrumentId), "balance-sheet"],
    queryFn: () => fetchBalanceSheet(token, instrumentId),
    staleTime: STALE_24H,
    enabled: needFallback && !!instrumentId,
  });
  const cashFlowQuery = useQuery({
    queryKey: [...qk.instruments.detail(instrumentId), "cash-flow"],
    queryFn: () => fetchCashFlow(token, instrumentId),
    staleTime: STALE_24H,
    enabled: needFallback && !!instrumentId,
  });

  // ── Merge ──────────────────────────────────────────────────────────────────
  if (bundleRecords != null) {
    // Happy path: the bundle answered — fallback queries never fired.
    return {
      records: bundleRecords,
      isLoading: false,
      isError: false,
      refetch: () => void bundleQuery.refetch(),
    };
  }

  if (!needFallback) {
    // Bundle still in flight (cold start) — loading.
    return {
      records: null,
      isLoading: bundleQuery.isLoading,
      isError: false,
      refetch: () => void bundleQuery.refetch(),
    };
  }

  // Fallback path. Partial tolerance: each statement table renders from its
  // own section slice, so two healthy endpoints + one failed one should still
  // paint two tables (the failed section simply has zero records → that
  // table is skipped by buildStatementTable's null return).
  const fallbackLoading =
    incomeQuery.isLoading || balanceQuery.isLoading || cashFlowQuery.isLoading;
  const allFailed = incomeQuery.isError && balanceQuery.isError && cashFlowQuery.isError;

  const merged: FundamentalsRecord[] = [
    ...(incomeQuery.data?.records ?? []),
    ...(balanceQuery.data?.records ?? []),
    ...(cashFlowQuery.data?.records ?? []),
  ];

  return {
    records: fallbackLoading || allFailed ? null : merged,
    isLoading: fallbackLoading,
    isError: allFailed,
    refetch: () => {
      // Retry whichever sources failed — bundle first (it may recover and
      // make the fallback unnecessary), then any failed dedicated legs.
      void bundleQuery.refetch();
      if (incomeQuery.isError) void incomeQuery.refetch();
      if (balanceQuery.isError) void balanceQuery.refetch();
      if (cashFlowQuery.isError) void cashFlowQuery.refetch();
    },
  };
}
