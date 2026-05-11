/**
 * __tests__/dashboard-empty-state.test.tsx — Unit tests for DashboardEmptyState
 *
 * WHY THIS EXISTS: pins the title/message/cta contract so dashboard widgets
 * relying on the shared empty state cannot regress silently.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";

// next/link rendering is fine in jsdom — no special mock needed for href-only.
// (next/router would, but DashboardEmptyState only uses Link, not navigation.)

describe("DashboardEmptyState", () => {
  it("renders the title and message", () => {
    render(
      <DashboardEmptyState
        title="No alerts yet"
        message="Trigger one to see it here."
      />,
    );
    expect(screen.getByText("No alerts yet")).toBeInTheDocument();
    expect(screen.getByText("Trigger one to see it here.")).toBeInTheDocument();
  });

  it("does not render a CTA when not provided", () => {
    render(
      <DashboardEmptyState title="Empty" message="No data" />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders the CTA link with correct label and href when provided", () => {
    render(
      <DashboardEmptyState
        title="No watchlists"
        message="Create one to begin."
        cta={{ label: "Create watchlist", href: "/portfolio/watchlists" }}
      />,
    );
    const link = screen.getByRole("link", { name: "Create watchlist" });
    expect(link.getAttribute("href")).toBe("/portfolio/watchlists");
  });

  it("uses role=status for assistive tech", () => {
    render(<DashboardEmptyState title="t" message="m" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
