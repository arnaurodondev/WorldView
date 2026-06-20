/**
 * components/portfolio/__tests__/LastSyncedBadge.test.tsx
 *
 * WHY THESE TESTS:
 * LastSyncedBadge is a small but important UX component — it surfaces the
 * `brokerage_last_synced_at` field that was previously hidden (G-4). Wrong
 * copy ("Invalid Date", empty string, or a crash on null) would undermine
 * user trust in the sync status panel.
 *
 * WHAT WE TEST:
 *   1. Valid ISO string → renders "Last synced: <relative time>"
 *   2. null → renders "Never synced" in the muted-text span
 *   3. The test-id attributes so parent components can query by testid
 *
 * MOCKED: useFormattedTimestamp — this hook's correctness is tested separately
 * (lib/hooks/__tests__/useFormattedTimestamp.test.ts). Here we care that the
 * badge passes the right value to the hook and renders the result correctly.
 * Mocking isolates this test from the hook's date-arithmetic logic so tests
 * don't break if relative time thresholds change.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Mock useFormattedTimestamp ─────────────────────────────────────────────────
// WHY mock the hook: we want to assert that the badge component passes the
// correct arguments and renders whatever the hook returns, without coupling
// the test to the hook's exact threshold logic (e.g. "2h ago" vs "3h ago"
// depending on when the test runs).
vi.mock("@/lib/hooks/useFormattedTimestamp", () => ({
  useFormattedTimestamp: (value: string | null) => {
    // Mirror what the real hook returns for null — "—"
    // and for a valid ISO string — a relative time string.
    if (!value) return "—";
    return "2h ago";
  },
}));

// ── SUT import (after mocks) ─────────────────────────────────────────────────
import { LastSyncedBadge } from "../LastSyncedBadge";

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("LastSyncedBadge", () => {
  it("renders relative time when lastSyncedAt is a valid ISO string", () => {
    render(<LastSyncedBadge lastSyncedAt="2026-06-20T10:00:00Z" />);

    // The badge should show "Last synced: <relative>" — the relative part
    // comes from the mocked hook which returns "2h ago" for any non-null value.
    const badge = screen.getByTestId("last-synced-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Last synced: 2h ago");
  });

  it("renders 'Never synced' when lastSyncedAt is null", () => {
    render(<LastSyncedBadge lastSyncedAt={null} />);

    // Null → the "never synced" variant is rendered with its own test-id.
    const badge = screen.getByTestId("last-synced-badge-never");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Never synced");

    // The normal badge must NOT appear when the sync has never run.
    expect(screen.queryByTestId("last-synced-badge")).not.toBeInTheDocument();
  });

  it("includes the raw ISO string as the title attribute for power users", () => {
    const iso = "2026-06-20T10:00:00Z";
    render(<LastSyncedBadge lastSyncedAt={iso} />);

    // The title attribute lets traders hover to see the exact UTC timestamp —
    // useful when they need to cross-reference with their brokerage's activity log.
    const badge = screen.getByTestId("last-synced-badge");
    expect(badge).toHaveAttribute("title", `Last synced: ${iso}`);
  });
});
