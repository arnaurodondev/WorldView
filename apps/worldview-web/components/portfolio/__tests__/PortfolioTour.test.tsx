/**
 * components/portfolio/__tests__/PortfolioTour.test.tsx — PLAN-0122 W-F (T-A-F-01).
 *
 * WHY THIS EXISTS: PortfolioTour is the onboarding guide. These tests pin the
 * behaviours the PRD §6.8 requirements (R-28…R-31) turn on:
 *   • it auto-starts from a "pending" flag and immediately writes "done" (never
 *     re-shows), and stays hidden when the flag is "done";
 *   • it backfills an existing user (flag unset + has a portfolio) to "done"
 *     without showing;
 *   • ×, Skip, and Escape each end the tour AND persist "done" (R-31);
 *   • Next advances, and a step whose data-tour-target anchor is ABSENT is
 *     skipped rather than crashing (R-29/§11 — e.g. the column toggle in Simple);
 *   • the tour is non-blocking — a sibling button stays clickable while it's open
 *     (R-30).
 *
 * NOTE ON ANCHORS: the tour resolves each step's element via
 * document.querySelector("[data-tour-target='…']"). In jsdom getBoundingClientRect
 * returns a (zeroed) rect, which counts as "present", so any anchor we render is
 * treated as live and any anchor we omit is treated as missing → skipped.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  PortfolioTour,
  PORTFOLIO_TOUR_SEEN_KEY,
  markTourPending,
} from "@/components/portfolio/PortfolioTour";

/**
 * Render the tour alongside a realistic set of anchors. By default every anchor
 * EXCEPT `column-toggle` is present (mirrors Simple mode, where the column toggle
 * is not rendered) so the last step self-skips. Pass `withColumnToggle` to also
 * render the Advanced-only anchor.
 */
function renderTour(opts: { withColumnToggle?: boolean; hasExistingPortfolio?: boolean } = {}) {
  const { withColumnToggle = false, hasExistingPortfolio = true } = opts;
  return render(
    <div>
      {/* The anchors the tour points at. Real ones live in the header / toggles;
          here we render stand-ins carrying the same data-tour-target contract. */}
      <div data-tour-target="portfolio-header">Portfolio</div>
      <button type="button" data-tour-target="mode-toggle">
        mode
      </button>
      <button type="button" data-tour-target="add-position">
        Add Position
      </button>
      {withColumnToggle && (
        <button type="button" data-tour-target="column-toggle">
          columns
        </button>
      )}
      {/* Sibling control to prove the tour is non-blocking. */}
      <button type="button" data-testid="page-action">
        page action
      </button>
      <PortfolioTour hasExistingPortfolio={hasExistingPortfolio} />
    </div>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  cleanup();
});

describe("PLAN-0122 W-F · PortfolioTour", () => {
  it("test_tour_auto_starts_from_pending_and_marks_done: pending → shows + flag done", async () => {
    markTourPending(); // arm as a first-ever create would
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("pending");

    renderTour();

    // The tour popover appears (auto-started at step 0 — Welcome).
    await waitFor(() => {
      expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument();
    });
    expect(screen.getByText(/Welcome to your portfolio/i)).toBeInTheDocument();
    // Flag flips to "done" the MOMENT the tour starts (never re-triggers).
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });

  it("test_tour_hidden_when_flag_done: does not show once seen", async () => {
    window.localStorage.setItem(PORTFOLIO_TOUR_SEEN_KEY, "done");
    renderTour();
    // Give effects a tick, then assert nothing rendered.
    await Promise.resolve();
    expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument();
  });

  it("test_existing_users_backfilled_done: unset + has portfolio → done, no tour", async () => {
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBeNull();
    renderTour({ hasExistingPortfolio: true });

    await waitFor(() => {
      expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
    });
    expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument();
  });

  it("test_tour_next_advances_and_skips_missing_anchor: Next walks steps; absent column-toggle skipped", async () => {
    const user = userEvent.setup();
    markTourPending();
    // No column-toggle anchor → the last step must be skipped.
    renderTour({ withColumnToggle: false });

    await waitFor(() => expect(screen.getByText(/Welcome to your portfolio/i)).toBeInTheDocument());

    // Step 0 → 1 (Detail level)
    await user.click(screen.getByTestId("portfolio-tour-next"));
    expect(await screen.findByText(/Choose your detail level/i)).toBeInTheDocument();

    // Step 1 → 2 (Add a position)
    await user.click(screen.getByTestId("portfolio-tour-next"));
    expect(await screen.findByText(/Add a position/i)).toBeInTheDocument();

    // Step 2 → 3 (Connect a brokerage) — this is now the LAST live step because
    // step 4 (Tune your columns / column-toggle) has no anchor.
    await user.click(screen.getByTestId("portfolio-tour-next"));
    expect(await screen.findByText(/Or connect a brokerage/i)).toBeInTheDocument();
    // The button reads "Done" (no further live step to advance to).
    expect(screen.getByTestId("portfolio-tour-next")).toHaveTextContent(/done/i);

    // Clicking Done ends the tour; the "Tune your columns" step is never shown.
    await user.click(screen.getByTestId("portfolio-tour-next"));
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());
    expect(screen.queryByText(/Tune your columns/i)).not.toBeInTheDocument();
  });

  it("test_tour_shows_advanced_column_step_when_anchor_present: Advanced reaches step 5", async () => {
    const user = userEvent.setup();
    markTourPending();
    renderTour({ withColumnToggle: true });

    await waitFor(() => expect(screen.getByText(/Welcome to your portfolio/i)).toBeInTheDocument());
    // Walk to the last step. Sequential awaits are intentional — each Next must
    // resolve (advance + re-measure the anchor) before the next click.
    for (let i = 0; i < 4; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await user.click(screen.getByTestId("portfolio-tour-next"));
    }
    expect(await screen.findByText(/Tune your columns/i)).toBeInTheDocument();
  });

  it("test_tour_dismiss_close_button_ends_and_flags_done", async () => {
    const user = userEvent.setup();
    markTourPending();
    renderTour();
    await waitFor(() => expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument());

    await user.click(screen.getByTestId("portfolio-tour-close"));
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });

  it("test_tour_dismiss_skip_ends_and_flags_done", async () => {
    const user = userEvent.setup();
    markTourPending();
    renderTour();
    await waitFor(() => expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument());

    await user.click(screen.getByTestId("portfolio-tour-skip"));
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });

  it("test_tour_dismiss_escape_ends_and_flags_done", async () => {
    markTourPending();
    renderTour();
    await waitFor(() => expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument());

    // Radix DismissableLayer listens for Escape on the document.
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });

  it("test_tour_non_blocking: a sibling page action stays clickable while the tour is open", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    markTourPending();
    render(
      <div>
        <div data-tour-target="portfolio-header">Portfolio</div>
        <button type="button" data-tour-target="mode-toggle">
          mode
        </button>
        <button type="button" data-tour-target="add-position">
          Add Position
        </button>
        <button type="button" data-testid="page-action" onClick={onClick}>
          page action
        </button>
        <PortfolioTour hasExistingPortfolio />
      </div>,
    );

    await waitFor(() => expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument());
    // With modal={false} the tour does not trap focus or block outside clicks.
    await user.click(screen.getByTestId("page-action"));
    expect(onClick).toHaveBeenCalledTimes(1);
    // Tour is still open (a background click doesn't necessarily dismiss it in
    // this assertion — the point is the click reached the button).
  });
});
