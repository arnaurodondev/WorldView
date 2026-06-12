/**
 * components/instrument/financials/usePeers.ts — upgraded peers fetcher + hook
 * (Wave-2 Financials redesign, scope item 4).
 *
 * WHY THIS FILE LIVES UNDER financials/ (not lib/api/instruments.ts): the
 * Wave-2 sprint splits ownership — lib/api/instruments.ts is owned by the
 * Quote-tab agent and its `getPeers()` still speaks the PRE-Wave-1 response
 * shape (5 peers, `gics_sector`, no day-change). The Wave-1 backend upgraded
 * GET /v1/instruments/{id}/peers to return 8 peers with `change_pct` +
 * `last_price` and a top-level `industry` (per-peer `gics_sector` is gone).
 * Per the sprint contract, new fetchers needed by the Financials tab live
 * under financials/** — this file is that fetcher + its TanStack hook.
 *
 * VERIFIED LIVE 2026-06-10 against the dev gateway (AAPL):
 *   { instrument_id, industry: "Technology", peers: [ { instrument_id,
 *     ticker, name, market_cap, pe_ratio, return_1y, change_pct,
 *     last_price } × 8 ] }
 *   — return_1y / change_pct / last_price are null for peers without OHLCV
 *   coverage (TSM, AVGO, … in the current seed), so every field is nullable.
 *
 * WHY A DISTINCT QUERY KEY (suffix "v2"/n=8): useFinancialsSidebarData (hooks/
 * dir — Quote-agent owned, read-only for this wave) still fires the legacy
 * n=5 fetch into qk.instruments.peers(id). Reusing that key here would make
 * the rendered peer count depend on which observer mounted first (TanStack
 * keeps ONE queryFn per key). A distinct key is deterministic; the legacy
 * n=5 response stays in its own cache slot (24h stale, one tiny GET) until
 * the sidebar hook drops its peers leg in a future wave.
 *
 * WHO USES IT: PeerComparisonTable.tsx (self-fetching panel).
 */

"use client";
// WHY "use client": useQuery requires the TanStack QueryClient context.

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/_client";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

// ── Wire types (Wave-1 upgraded response) ────────────────────────────────────

/** One peer row from the upgraded endpoint. All metrics nullable (see above). */
export interface PeerRowV2 {
  instrument_id: string;
  ticker: string;
  name: string;
  /** Market capitalisation in USD. */
  market_cap: number | null;
  /** Trailing P/E; null = no earnings / not computed. */
  pe_ratio: number | null;
  /** 1-year price return as a decimal (0.57 = +57%). */
  return_1y: number | null;
  /** Day change as an already-percent number (1.61 = +1.61%). */
  change_pct: number | null;
  /** Last traded price in USD. */
  last_price: number | null;
}

export interface PeersV2Response {
  instrument_id: string;
  /** Shared classification of the peer set, e.g. "Technology". */
  industry: string | null;
  peers: PeerRowV2[];
}

// ── Fetcher ──────────────────────────────────────────────────────────────────

/** Number of peers the redesigned table shows (Wave-1 backend default-max). */
export const PEER_COUNT = 8;

/**
 * fetchPeersV2 — GET /v1/instruments/{id}/peers?n=8 with the upgraded shape.
 * Plain function (not a gateway method) so tests can mock apiFetch directly.
 */
export function fetchPeersV2(
  token: string | null | undefined,
  instrumentId: string,
  n: number = PEER_COUNT,
): Promise<PeersV2Response> {
  return apiFetch<PeersV2Response>(
    `/v1/instruments/${encodeURIComponent(instrumentId)}/peers?n=${n}`,
    { token: token ?? undefined },
  );
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * usePeers — TanStack hook for the upgraded peers panel.
 *
 * staleTime 5 min (NOT the legacy 24h): the upgraded response carries
 * `last_price` + `change_pct` — intraday figures that go stale within a
 * session. 5 min matches the technicals cadence used elsewhere on the tab.
 */
export function usePeers(instrumentId: string) {
  const token = useAccessToken();
  return useQuery<PeersV2Response>({
    // Extends the canonical peers key with the v2/n discriminator — see the
    // module header for why this must NOT collide with the legacy n=5 key.
    queryKey: [...qk.instruments.peers(instrumentId), "v2", PEER_COUNT],
    queryFn: () => fetchPeersV2(token, instrumentId),
    staleTime: 5 * 60 * 1000,
    enabled: !!instrumentId,
  });
}
