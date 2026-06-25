/**
 * components/portfolio/__tests__/ManualPortfolioEmptyState.test.tsx
 *
 * WHY THESE TESTS:
 * ManualPortfolioEmptyState is the onboarding empty state for MANUAL portfolios
 * (FR-5 / G-5). The most critical user journey for the thesis demo is:
 *   "Maria creates a MANUAL portfolio, sees this empty state, clicks the CTA,
 *    records a transaction, and sees her position in the Holdings tab."
 *
 * If the CTA doesn't call onOpenAddPosition, that journey breaks at step 3.
 * If the headline/body copy is missing, Maria doesn't understand what to do.
 *
 * WHAT WE TEST:
 *   1. Renders the headline "No positions yet"
 *   2. Renders body copy explaining the transaction → holdings relationship
 *   3. Renders the "Record Transaction" CTA button
 *   4. Clicking the CTA calls onOpenAddPosition
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ManualPortfolioEmptyState } from "../ManualPortfolioEmptyState";

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ManualPortfolioEmptyState", () => {
  it("renders the headline 'No positions yet'", () => {
    render(<ManualPortfolioEmptyState onOpenAddPosition={vi.fn()} />);

    const headline = screen.getByTestId("manual-empty-headline");
    expect(headline).toBeInTheDocument();
    expect(headline).toHaveTextContent("No positions yet");
  });

  it("renders body copy explaining the transaction→holdings relationship", () => {
    render(<ManualPortfolioEmptyState onOpenAddPosition={vi.fn()} />);

    // Verify that the core UX message is present — users must understand that
    // holdings are computed from transactions, not entered directly.
    expect(
      screen.getByText(/Record a transaction to start tracking/i),
    ).toBeInTheDocument();

    // The "within seconds" copy is critical (FR-8 alignment): it sets the
    // correct expectation for the async W1 Kafka consumer path.
    expect(screen.getByText(/within seconds/i)).toBeInTheDocument();
  });

  it("renders the 'Record Transaction' CTA button", () => {
    render(<ManualPortfolioEmptyState onOpenAddPosition={vi.fn()} />);

    const cta = screen.getByTestId("manual-empty-cta");
    expect(cta).toBeInTheDocument();
    // Matches the button label — case-insensitive because the button uses
    // uppercase CSS tracking, but the DOM text node is the original casing.
    expect(cta).toHaveTextContent(/Record Transaction/i);
  });

  it("calls onOpenAddPosition when the CTA button is clicked", () => {
    const onOpenAddPosition = vi.fn();
    render(<ManualPortfolioEmptyState onOpenAddPosition={onOpenAddPosition} />);

    // Clicking the CTA should trigger the parent's dialog open callback.
    // In page.tsx this is wired to setAddPositionOpen(true).
    fireEvent.click(screen.getByTestId("manual-empty-cta"));

    expect(onOpenAddPosition).toHaveBeenCalledOnce();
  });

  it("renders the empty state container with the correct testid", () => {
    render(<ManualPortfolioEmptyState onOpenAddPosition={vi.fn()} />);

    // Parent components (and browser tests) may query by this testid
    // to assert that the empty state is visible.
    expect(
      screen.getByTestId("manual-portfolio-empty-state"),
    ).toBeInTheDocument();
  });
});
