/**
 * hooks/useResolvedPortfolioId.ts — single source of truth for "which
 * portfolio should this widget scope to?".
 *
 * WHY THIS EXISTS (QA A-F-002 / 2026-05-21):
 *   The W1.1 F-002 fix wired the new PortfolioSwitcher chip into
 *   `usePortfolioMetrics` so the TopBar rail follows the user's
 *   selection. But three other widgets (WorkspacePortfolioPanel,
 *   PortfolioSummary, HoldingsMoversWidget) still picked
 *   `portfolios?.[0]?.portfolio_id` regardless of the chip. From the
 *   user's POV the switcher only flipped the TopBar — half-shipped.
 *   This helper extracts the same resolution logic (`useActivePortfolio`
 *   first, fallback to `portfolios[0]`, validate the persisted id is
 *   still in the user's portfolios) so every consumer follows one
 *   contract.
 *
 * SEMANTICS:
 *   - `activePortfolioId` from context wins when set AND still exists.
 *   - If the persisted id no longer exists (deleted portfolio, fresh
 *     login, etc.), fall back to `portfolios[0]`. This prevents the
 *     downstream `getHoldings(...)` call from 404'ing on a stale uuid.
 *   - When `portfolios` is undefined (still loading), returns null —
 *     callers should gate their dependent queries on a truthy result.
 *   - When the context has no value (or no provider is mounted), falls
 *     through to `portfolios[0]` — pre-W1.1 behaviour preserved.
 */

import type { Portfolio } from "@/types/api";
import { useActivePortfolio } from "@/contexts/ActivePortfolioContext";

export function useResolvedPortfolioId(
  portfolios: readonly Portfolio[] | undefined,
): string | null {
  const { activePortfolioId } = useActivePortfolio();
  if (!portfolios || portfolios.length === 0) return null;
  if (
    activePortfolioId &&
    portfolios.some((p) => p.portfolio_id === activePortfolioId)
  ) {
    return activePortfolioId;
  }
  return portfolios[0]?.portfolio_id ?? null;
}
