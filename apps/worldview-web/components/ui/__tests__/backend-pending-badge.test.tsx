/**
 * components/ui/__tests__/backend-pending-badge.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: pins the BackendPendingBadge contract — default copy + custom
 * override — so a future refactor cannot silently change either without
 * an explicit test diff. The badge is referenced from two surfaces
 * (IntelligenceFilterGroup + ColumnSettingsPopover) and one copy change
 * would cascade.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BackendPendingBadge } from "@/components/ui/backend-pending-badge";

describe("BackendPendingBadge", () => {
  it("renders the default 'Backend pending' copy when no text prop", () => {
    // WHY: default copy is the most common surface (every intelligence row).
    // Locking it ensures a future i18n / refactor doesn't change it without
    // an explicit test failure forcing a review.
    render(<BackendPendingBadge />);
    expect(screen.getByText("Backend pending")).toBeInTheDocument();
  });

  it("renders custom copy when text prop is supplied", () => {
    // WHY: ColumnSettingsPopover uses 'L-pending' (denser surface). The
    // override surface must keep working for that single consumer.
    render(<BackendPendingBadge text="L-pending" />);
    expect(screen.getByText("L-pending")).toBeInTheDocument();
  });

  it("exposes a status role with the badge text as aria-label", () => {
    // WHY: screen-reader users hear the badge as a status update. The
    // role + aria-label pair are the only a11y contract — pinning them
    // here keeps the badge accessible if a future tweak changes the
    // visual chrome.
    render(<BackendPendingBadge text="Hello" />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveAttribute("aria-label", "Hello");
    expect(badge).toHaveTextContent("Hello");
  });
});
