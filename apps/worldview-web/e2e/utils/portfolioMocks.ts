/**
 * e2e/utils/portfolioMocks.ts — shared portfolio-page mock stack for the
 * PLAN-0122 W-F specs (T-A-F-03).
 *
 * WHY THIS EXISTS: the new Simple-mode / typeahead / edit / tour specs all need
 * the same realistic backend: a single non-root manual portfolio with one AAPL
 * holding, plus sane zero-value responses for every sub-route the page fires
 * (exposure, performance, realized-pnl, sector-breakdown, concentration,
 * value-history, quotes, transactions, watchlists, risk-metrics, bundle). This
 * mirrors the (proven) helper stack in plan0108-portfolio-redesign.spec.ts,
 * factored out so the five new specs stay DRY and consistent.
 *
 * ROUTE ORDER (Playwright matches LIFO — last-registered wins): register the
 * broad catch-all FIRST, then the narrower holdings/portfolios/search/auth so the
 * specific patterns take priority.
 *
 * NO REAL BACKEND: the mocked Playwright project runs against a built app with
 * every S9 call intercepted here.
 */

import type { Page } from "@playwright/test";
import { buildFakeToken } from "../fixtures/api-mocks";

/** A raw S1 portfolio (note: the wire field is `id`, renamed to `portfolio_id`
 *  client-side — using `portfolio_id` here would leave activePortfolioId null). */
export interface RawPortfolio {
  id: string;
  name: string;
  currency: string;
  owner_id: string;
  tenant_id?: string;
  status?: string;
  kind?: string;
  created_at: string;
}

/** The default single manual portfolio used by every W-F spec. */
export const E2E_PORTFOLIO: RawPortfolio = {
  id: "port-e2e",
  name: "E2E Portfolio",
  currency: "USD",
  owner_id: "e2e-user",
  tenant_id: "e2e-tenant",
  status: "active",
  kind: "manual",
  created_at: "2026-01-01T00:00:00Z",
};

/** One AAPL holding (raw S1 shape: `id`, string decimals). */
export const E2E_HOLDING = {
  id: "h-aapl-1",
  portfolio_id: "port-e2e",
  instrument_id: "ins-aapl",
  entity_id: "ent-aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  quantity: "10.00000000",
  average_cost: "150.00000000",
  currency: "USD",
};

/** Auth refresh + ws-token so the page mounts without redirecting to /login. */
export async function installAuthMocks(page: Page): Promise<void> {
  const token = buildFakeToken();
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: token,
        expires_in: 3600,
        user: {
          user_id: "e2e-user",
          tenant_id: "e2e-tenant",
          email: "e2e@test.local",
          name: "E2E User",
        },
      }),
    }),
  );
  await page.route("**/api/v1/auth/ws-token", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws" }),
    }),
  );
}

/** URL-aware catch-all returning zero-value typed shapes for every sub-route so
 *  no strip crashes on `.toFixed()` of an undefined field. */
export async function installCatchAllMock(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    if (url.includes("/exposure"))
      return json({ invested: 1500, cash: 500, gross_exposure_pct: "0.75", net_exposure_pct: "0.75", leverage: 1.0, buying_power: 500, prices_stale: false });
    if (url.includes("/concentration"))
      return json({ portfolio_id: "port-e2e", hhi: 1200, label: "moderate", top_3_share_pct: "45.00", positions_count: 1, top_positions: [], prices_stale: false });
    if (url.includes("/performance"))
      return json({ portfolio_id: "port-e2e", period: "1D", return_pct: 0.0, return_abs: 0.0, covered_pct: 1.0 });
    if (url.includes("/value-history")) return json({ dates: [], values: [] });
    if (url.includes("/quotes/batch")) return json({ quotes: {} });
    if (url.includes("/realized-pnl"))
      return json({ portfolio_id: "port-e2e", total_realized: 0.0, realized_long_term: 0.0, realized_short_term: 0.0 });
    if (url.includes("/sector-breakdown")) return json({ sectors: [] });
    if (url.includes("/risk-metrics"))
      return json({ max_drawdown: null, volatility: null, sharpe_ratio: null, sortino_ratio: null, beta_vs_spy: null });
    if (url.includes("/bundle")) return json({});
    if (url.includes("/transactions")) return json({ items: [], total: 0, limit: 50, offset: 0 });
    if (url.includes("/watchlists")) return json([]);
    return json({});
  });
}

/** GET /api/v1/portfolios → the provided list (default: the single E2E portfolio). */
export async function installPortfolioMock(page: Page, portfolios: RawPortfolio[] = [E2E_PORTFOLIO]): Promise<void> {
  await page.route("**/api/v1/portfolios", (route) => {
    // Only intercept GET — POST (create) / DELETE fall through to the catch-all.
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: portfolios, total: portfolios.length, limit: 100, offset: 0 }),
    });
  });
}

/** GET /api/v1/holdings/{id} → the provided holdings (default: one AAPL). */
export async function installHoldingsMock(page: Page, holdings: unknown[] = [E2E_HOLDING]): Promise<void> {
  await page.route("**/api/v1/holdings/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(holdings) }),
  );
}

/** GET /api/v1/search/instruments → a single AAPL match for the typeahead. */
export async function installSearchMock(page: Page): Promise<void> {
  await page.route("**/api/v1/search/instruments**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: [
          { instrument_id: "ins-aapl", ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", asset_class: "equity" },
        ],
        total: 1,
      }),
    }),
  );
}

/**
 * Install the full default stack (auth + catch-all + portfolios + holdings) in
 * the correct LIFO order. Pass `holdings: []` for an empty portfolio.
 */
export async function installPortfolioPage(
  page: Page,
  opts: { portfolios?: RawPortfolio[]; holdings?: unknown[]; withSearch?: boolean } = {},
): Promise<void> {
  await installCatchAllMock(page); // broad — registered first (lowest priority)
  await installHoldingsMock(page, opts.holdings ?? [E2E_HOLDING]);
  await installPortfolioMock(page, opts.portfolios ?? [E2E_PORTFOLIO]);
  if (opts.withSearch) await installSearchMock(page);
  await installAuthMocks(page); // always-200 — registered last (highest priority)
}
