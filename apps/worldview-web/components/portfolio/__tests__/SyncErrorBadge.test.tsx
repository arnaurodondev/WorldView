/**
 * components/portfolio/__tests__/SyncErrorBadge.test.tsx
 *
 * WHY THESE TESTS:
 * SyncErrorBadge is the persistent visual indicator for brokerage sync errors
 * (FR-7 / G-7). Two failure modes exist:
 *   a) Badge renders when it shouldn't (errorCount === 0) → misleads users
 *      into thinking there are errors when there are none.
 *   b) onClick doesn't fire → user can't navigate to the error details.
 *
 * These tests guard both modes.
 *
 * WHAT WE TEST:
 *   1. Renders red dot + count when errorCount > 0
 *   2. Renders nothing when errorCount === 0
 *   3. Clicking the badge calls onClickScrollToErrors
 *   4. Singular/plural text ("1 sync error" vs "3 sync errors")
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SyncErrorBadge } from "../SyncErrorBadge";

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SyncErrorBadge", () => {
  it("renders red dot and error count when errorCount > 0", () => {
    render(<SyncErrorBadge errorCount={3} onClickScrollToErrors={vi.fn()} />);

    const badge = screen.getByTestId("sync-error-badge");
    expect(badge).toBeInTheDocument();

    // The ● dot and count should be visible.
    expect(badge).toHaveTextContent("●");
    expect(badge).toHaveTextContent("3 sync errors");
  });

  it("renders nothing (null) when errorCount === 0", () => {
    const { container } = render(
      <SyncErrorBadge errorCount={0} onClickScrollToErrors={vi.fn()} />,
    );

    // Component returns null — no DOM node at all.
    // Checking container.firstChild is more reliable than queryByTestId
    // because a null-returning component leaves no DOM node to query.
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("sync-error-badge")).not.toBeInTheDocument();
  });

  it("calls onClickScrollToErrors when badge is clicked", () => {
    const onClickScrollToErrors = vi.fn();
    render(<SyncErrorBadge errorCount={2} onClickScrollToErrors={onClickScrollToErrors} />);

    fireEvent.click(screen.getByTestId("sync-error-badge"));

    // The parent (HoldingsTab) wires this to a scrollIntoView call on the
    // BrokerageStatusBanner ref — we just verify the callback fires once.
    expect(onClickScrollToErrors).toHaveBeenCalledOnce();
  });

  it("uses singular 'error' for errorCount === 1", () => {
    render(<SyncErrorBadge errorCount={1} onClickScrollToErrors={vi.fn()} />);

    const badge = screen.getByTestId("sync-error-badge");
    // WHY check aria-label (not textContent): the aria-label is the accessible
    // name for screen readers — it must be grammatically correct.
    expect(badge).toHaveAttribute(
      "aria-label",
      "1 brokerage sync error — click to view",
    );
    // Visual text also singular.
    expect(badge).toHaveTextContent("1 sync error");
  });

  it("uses plural 'errors' for errorCount > 1", () => {
    render(<SyncErrorBadge errorCount={5} onClickScrollToErrors={vi.fn()} />);

    const badge = screen.getByTestId("sync-error-badge");
    expect(badge).toHaveAttribute(
      "aria-label",
      "5 brokerage sync errors — click to view",
    );
    expect(badge).toHaveTextContent("5 sync errors");
  });
});
