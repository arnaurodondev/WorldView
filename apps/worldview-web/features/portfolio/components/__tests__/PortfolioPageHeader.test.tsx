/**
 * features/portfolio/components/__tests__/PortfolioPageHeader.test.tsx
 *
 * WHY THIS FILE EXISTS (PLAN-0108 W5 T-5-01): covers the two UX fixes:
 *   1. ROOT inline hint text rendered when activeIsRoot=true
 *   2. ROOT inline hint text absent for non-root portfolios
 *
 * No TanStack Query provider is required — PortfolioPageHeader is a pure
 * presentational component that receives all data via props.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioPageHeader } from "../PortfolioPageHeader";
import type { Portfolio } from "@/types/api";

// ── Minimal portfolio fixtures ─────────────────────────────────────────────

/** The aggregate "ALL" portfolio (kind=root). */
const ROOT_PORTFOLIO: Portfolio = {
  portfolio_id: "019500000000000000000001",
  name: "All Accounts",
  kind: "root",
  // WHY cast: Portfolio may have optional fields; we only need the discriminant
  // and id for these rendering tests.
} as Portfolio;

/** A normal user-created portfolio (kind=manual). */
const MANUAL_PORTFOLIO: Portfolio = {
  portfolio_id: "019500000000000000000002",
  name: "Tech Growth",
  kind: "manual",
} as Portfolio;

// ── Shared no-op callbacks ─────────────────────────────────────────────────

const noop = vi.fn();

const BASE_PROPS = {
  sortedPortfolios: [ROOT_PORTFOLIO, MANUAL_PORTFOLIO],
  holdingCount: 5,
  scopeHint: null,
  onSelectPortfolio: noop,
  onAddPosition: noop,
  onCreatePortfolio: noop,
  onDeletePortfolio: noop,
};

// ── Tests ─────────────────────────────────────────────────────────────────

describe("PortfolioPageHeader", () => {
  it("shows ROOT inline text when activeIsRoot is true", () => {
    // ARRANGE: render with the aggregate portfolio active
    render(
      <PortfolioPageHeader
        {...BASE_PROPS}
        activePortfolio={ROOT_PORTFOLIO}
        activePortfolioId={ROOT_PORTFOLIO.portfolio_id}
        activeIsRoot={true}
      />,
    );

    // ASSERT: the explanatory hint is present
    expect(
      screen.getByText("Select a portfolio to add positions. ALL is read-only."),
    ).toBeInTheDocument();
  });

  it("hides ROOT inline text for non-root portfolio", () => {
    // ARRANGE: render with a manual portfolio active
    render(
      <PortfolioPageHeader
        {...BASE_PROPS}
        activePortfolio={MANUAL_PORTFOLIO}
        activePortfolioId={MANUAL_PORTFOLIO.portfolio_id}
        activeIsRoot={false}
      />,
    );

    // ASSERT: the hint must not appear for a normal (non-root) portfolio
    expect(
      screen.queryByText(
        "Select a portfolio to add positions. ALL is read-only.",
      ),
    ).not.toBeInTheDocument();
  });
});
