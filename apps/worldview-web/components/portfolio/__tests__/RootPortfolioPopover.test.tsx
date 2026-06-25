/**
 * components/portfolio/__tests__/RootPortfolioPopover.test.tsx
 *
 * WHY THIS EXISTS: Guards the RootPortfolioPopover's key behaviours:
 *  1. Renders for kind="root" portfolio (shows the ℹ button).
 *  2. Does not render for kind="manual" or kind="brokerage" portfolios.
 *  3. Dismiss sets localStorage key "worldview:root_portfolio_popover_dismissed".
 *  4. Does not render the popover content on re-mount after dismissal
 *     (checks localStorage on mount).
 *
 * WHY we test localStorage behaviour: the dismissed-state persistence is the
 * primary UX contract of this component. Without it, users would see the
 * popover on every page load which defeats the purpose of "dismiss once".
 *
 * WHY we mock localStorage: jsdom provides a real localStorage implementation,
 * but we spy on it to assert calls rather than reading the internal state.
 * This makes tests independent of leftover state from other tests.
 *
 * PRD-0114 W5-T09
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { RootPortfolioPopover, DISMISSED_KEY } from "../RootPortfolioPopover";

// ── localStorage setup ────────────────────────────────────────────────────────

// WHY clear before each test: if one test writes the dismissed key, subsequent
// tests that don't clear it will behave as "already dismissed" — a false
// positive. Clearing ensures each test starts from a clean state.
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("RootPortfolioPopover", () => {
  it("renders the ℹ info button for kind='root' portfolio", () => {
    render(<RootPortfolioPopover portfolioKind="root" />);
    // The info button should be present and accessible.
    expect(
      screen.getByRole("button", { name: /learn about all accounts/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing for kind='manual' portfolio", () => {
    const { container } = render(<RootPortfolioPopover portfolioKind="manual" />);
    // The component returns null for non-root portfolios.
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for kind='brokerage' portfolio", () => {
    const { container } = render(<RootPortfolioPopover portfolioKind="brokerage" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when portfolioKind is not provided and defaults to root", () => {
    // WHY: default is "root" so without a prop, the button still renders.
    render(<RootPortfolioPopover />);
    expect(
      screen.getByRole("button", { name: /learn about all accounts/i }),
    ).toBeInTheDocument();
  });

  it("shows the popover content when the ℹ button is clicked", async () => {
    const user = userEvent.setup();
    render(<RootPortfolioPopover portfolioKind="root" />);

    const infoButton = screen.getByRole("button", { name: /learn about all accounts/i });
    await user.click(infoButton);

    // After clicking, the popover content should be visible.
    // The heading "All Accounts (Aggregate View)" is defined in the component.
    await waitFor(() => {
      expect(screen.getByText(/All Accounts \(Aggregate View\)/i)).toBeInTheDocument();
    });
  });

  it("shows a 'Got it' dismiss button inside the popover", async () => {
    const user = userEvent.setup();
    render(<RootPortfolioPopover portfolioKind="root" />);

    await user.click(screen.getByRole("button", { name: /learn about all accounts/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /got it/i })).toBeInTheDocument();
    });
  });

  it("sets localStorage key on dismiss via 'Got it' button", async () => {
    const user = userEvent.setup();
    render(<RootPortfolioPopover portfolioKind="root" />);

    // Open the popover first.
    await user.click(screen.getByRole("button", { name: /learn about all accounts/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /got it/i })).toBeInTheDocument()
    );

    // Click "Got it" to dismiss.
    await user.click(screen.getByRole("button", { name: /got it/i }));

    // WHY check localStorage directly (not via spy): vi.spyOn(Storage.prototype, "setItem")
    // is unreliable in jsdom when beforeEach clears mocks — the spy intercepts calls but the
    // jsdom implementation also fires, and clearAllMocks can desync the tracking. Checking the
    // actual localStorage state is the most reliable assertion for this contract.
    await waitFor(() => {
      expect(localStorage.getItem(DISMISSED_KEY)).toBe("1");
    });
  });

  it("does not auto-show popover on mount when already dismissed", async () => {
    // Simulate a previous dismissal by pre-writing the key.
    localStorage.setItem(DISMISSED_KEY, "1");

    render(<RootPortfolioPopover portfolioKind="root" />);

    // Wait briefly to ensure any auto-open timer has had time to fire.
    // WHY 500ms: the component uses a 300ms setTimeout before auto-opening.
    await new Promise((r) => setTimeout(r, 500));

    // The "All Accounts (Aggregate View)" heading should NOT be in the DOM
    // because the popover should not have auto-opened after a previous dismissal.
    expect(screen.queryByText(/All Accounts \(Aggregate View\)/i)).not.toBeInTheDocument();
  });

  it("DISMISSED_KEY export matches the expected localStorage key", () => {
    // WHY test the exported constant: the test that checks localStorage.setItem
    // relies on this constant. If the key ever changes in the implementation,
    // the tests should break loudly rather than silently reading the wrong key.
    expect(DISMISSED_KEY).toBe("worldview:root_portfolio_popover_dismissed");
  });
});
