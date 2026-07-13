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

import { useState } from "react";
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

  // ── A11Y: keyboard focus-stepping ──────────────────────────────────────────

  it("test_tour_focuses_advance_button_on_open: keyboard user lands on Next", async () => {
    markTourPending();
    renderTour();

    // Once the step renders, focus is moved to the primary advance button so a
    // keyboard user can press Enter to advance (non-blocking focus, not a trap).
    await waitFor(() => {
      expect(screen.getByTestId("portfolio-tour-next")).toHaveFocus();
    });
    // On the first step the advance button reads "Next".
    expect(screen.getByTestId("portfolio-tour-next")).toHaveTextContent(/next/i);
  });

  it("test_tour_focuses_done_on_final_step: focus follows to the Done button", async () => {
    const user = userEvent.setup();
    markTourPending();
    // No column-toggle → Connect-brokerage (step 3) is the final live step.
    renderTour({ withColumnToggle: false });

    await waitFor(() => expect(screen.getByTestId("portfolio-tour-next")).toHaveFocus());

    // Walk to the final live step (index 3).
    await user.click(screen.getByTestId("portfolio-tour-next")); // → Detail level
    await user.click(screen.getByTestId("portfolio-tour-next")); // → Add a position
    await user.click(screen.getByTestId("portfolio-tour-next")); // → Connect a brokerage (last)

    expect(await screen.findByText(/Or connect a brokerage/i)).toBeInTheDocument();
    const advance = screen.getByTestId("portfolio-tour-next");
    // Final step: the advance button reads "Done" and receives focus.
    expect(advance).toHaveTextContent(/done/i);
    await waitFor(() => expect(advance).toHaveFocus());
  });

  it("test_tour_focus_stepping_does_not_break_escape_dismiss: Escape still ends", async () => {
    markTourPending();
    renderTour();
    // Focus-stepping put focus inside the popover…
    await waitFor(() => expect(screen.getByTestId("portfolio-tour-next")).toHaveFocus());

    // …but Escape must still dismiss + persist "done" (non-blocking preserved).
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });

  // ── A11Y: focus must not be stolen on scroll/resize (Defect 1 regression) ───

  it("test_tour_does_not_steal_focus_on_scroll: reflow (scroll/resize) never yanks focus back to the advance button", async () => {
    markTourPending();
    renderTour();

    // The tour opens and focus-steps to its advance button.
    await waitFor(() => expect(screen.getByTestId("portfolio-tour-next")).toHaveFocus());

    // Move focus to a DIFFERENT focusable element and hold it there. We use the
    // tour's own "Skip tour" button: it is focusable, and — crucially — it lives
    // INSIDE the popover, so moving focus to it does NOT trip Radix's
    // onFocusOutside auto-dismiss (a non-modal Popover closes when focus leaves
    // its content). That keeps this test a clean, deterministic probe of ONE
    // thing: does reflow steal focus back onto the advance button? The steal path
    // is identical whether focus sat on this button or on an external page input.
    const skip = screen.getByTestId("portfolio-tour-skip");
    skip.focus();
    expect(skip).toHaveFocus();

    // A scroll AND a resize each fire the reflow listener, which calls
    // setRect(measure()) with a FRESH rect object (new reference every time).
    // Against the pre-fix code (focus effect depending on `rect`) this re-runs the
    // focus effect and calls advanceButtonRef.focus() → focus is STOLEN from Skip
    // onto Next → this assertion FAILS. After the fix (effect keyed off stepIndex
    // only) the rect churn is a no-op for focus, so focus stays put.
    fireEvent.scroll(document); // capture-phase window "scroll" listener
    fireEvent.resize(window); // window "resize" listener

    // Give any effects a tick to flush, then assert focus was NOT stolen.
    await waitFor(() => {
      expect(skip).toHaveFocus();
    });
    // Belt-and-braces: the tour is still open (reflow doesn't dismiss it) and
    // focus is definitively NOT on the tour's advance button.
    expect(screen.getByTestId("portfolio-tour")).toBeInTheDocument();
    expect(screen.getByTestId("portfolio-tour-next")).not.toHaveFocus();
  });

  // ── A11Y: focus restore on close (Defect 2) ─────────────────────────────────

  it("test_tour_restores_focus_on_close: focus returns to the pre-tour element, not <body>", async () => {
    const user = userEvent.setup();
    markTourPending();

    // Harness lets us FOCUS an element BEFORE the tour mounts (the tour auto-opens
    // on mount and immediately grabs focus, so we defer mounting it behind a
    // click that also leaves focus on the pre-tour button).
    function Harness() {
      const [showTour, setShowTour] = useState(false);
      return (
        <div>
          <div data-tour-target="portfolio-header">Portfolio</div>
          <button type="button" data-tour-target="mode-toggle">
            mode
          </button>
          <button type="button" data-tour-target="add-position">
            Add Position
          </button>
          <button type="button" data-testid="pre-focus" onClick={() => setShowTour(true)}>
            before tour
          </button>
          {showTour && <PortfolioTour hasExistingPortfolio />}
        </div>
      );
    }

    render(<Harness />);
    const priorFocus = screen.getByTestId("pre-focus");

    // Clicking focuses the pre-tour button AND mounts the tour. At the moment the
    // tour's onOpenAutoFocus fires, document.activeElement is this button, so it
    // is captured as the return-focus target.
    await user.click(priorFocus);

    // Tour opened and moved focus to its advance button.
    await waitFor(() => expect(screen.getByTestId("portfolio-tour-next")).toHaveFocus());

    // Dismiss via Escape (also exercises the dismiss path).
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("portfolio-tour")).not.toBeInTheDocument());

    // Focus is restored to the pre-tour element — NOT dropped to document.body.
    expect(priorFocus).toHaveFocus();
    expect(document.body).not.toHaveFocus();
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
