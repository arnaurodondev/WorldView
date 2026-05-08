/**
 * __tests__/brief-diff-badge.test.tsx — BriefDiffBadge component tests
 * (PLAN-0066 Wave F T-W10-F-01)
 *
 * WHY THESE TESTS:
 * BriefDiffBadge is the entry-point for the diff UX — if it silently hides
 * or crashes, the trader never sees that new information is available. These
 * tests pin:
 *   1. Badge shows "N new" when new_bullets are present.
 *   2. Badge is hidden when status = "no_diff_available" (no data to show).
 *
 * WHY MOCK useQuery:
 * useQuery depends on a QueryClient provider and fetches from the network.
 * Tests should not make real network calls — we mock the module-level useQuery
 * to return the fixture data directly, which is the standard pattern in this
 * codebase (see AskAiPanel.test.tsx, WatchlistMoversWidget.insights.test.tsx).
 *
 * WHY MOCK next/link:
 * BriefDiffPanel uses next/link for citations. jsdom doesn't mount the App Router
 * so we mock Link as a plain <a>.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BriefDiffResponse } from "@/types/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// Mock useQuery so we control what data the badge "receives"
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
}));

// Mock next/link — BriefDiffPanel uses it internally but jsdom lacks App Router
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Import after mocks are registered
import { useQuery } from "@tanstack/react-query";
import { BriefDiffBadge } from "@/features/dashboard/components/BriefDiffBadge";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeDiff(overrides: Partial<BriefDiffResponse> = {}): BriefDiffResponse {
  return {
    status: "diff_available",
    today_generated_at: "2026-05-08T07:00:00Z",
    yesterday_generated_at: "2026-05-07T07:00:00Z",
    new_bullets: [
      { section_title: "Market Context", text: "New bullet text", citations: [] },
      { section_title: "Risk Factors", text: "Another new bullet", citations: [] },
    ],
    removed_bullets: [
      { section_title: "Market Context", text: "Old bullet text", citations: [] },
    ],
    changed_sections: ["Market Context"],
    delta_summary: "2 new bullets, 1 removed since 2026-05-07",
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("BriefDiffBadge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("test_brief_diff_badge_shows_new_count — badge shows count when new_bullets present", () => {
    // WHY: the diff badge is the primary signal that new information exists.
    // If it renders incorrectly, the trader won't know the brief updated.
    (useQuery as ReturnType<typeof vi.fn>).mockReturnValue({ data: makeDiff() });

    render(<BriefDiffBadge token="test-token" briefId="brief-123" />);

    // WHY getByRole("button"): the badge IS a button (toggles the panel).
    // Checking for button ensures it is interactive, not just decorative.
    const badge = screen.getByRole("button", { name: /2 new bullets/i });
    expect(badge).toBeInTheDocument();
    // WHY check visible text: traders scan visually; the count must be in the label.
    expect(badge).toHaveTextContent("2 new");
  });

  it("test_brief_diff_badge_hidden_when_no_data — badge hidden when no_diff_available", () => {
    // WHY: the badge must NOT appear when there is only one brief (nothing to diff).
    // An empty amber badge on every first-time user's dashboard would be confusing.
    (useQuery as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { status: "no_diff_available", new_bullets: [], removed_bullets: [], changed_sections: [], delta_summary: "", today_generated_at: null, yesterday_generated_at: null },
    });

    const { container } = render(<BriefDiffBadge token="test-token" briefId="brief-123" />);
    // WHY check container is empty: the component returns null — no DOM output at all.
    expect(container.firstChild).toBeNull();
  });

  it("badge opens BriefDiffPanel on click and shows delta_summary", () => {
    // WHY: the panel must open on click and show the diff content — ensures
    // the toggle mechanism works end-to-end.
    (useQuery as ReturnType<typeof vi.fn>).mockReturnValue({ data: makeDiff() });

    render(<BriefDiffBadge token="test-token" briefId="brief-123" />);

    const badge = screen.getByRole("button", { name: /2 new bullets/i });
    fireEvent.click(badge);

    // WHY check delta_summary: confirms BriefDiffPanel rendered and received the diff data
    expect(screen.getByTestId("brief-diff-panel")).toBeInTheDocument();
    expect(screen.getByText("2 new bullets, 1 removed since 2026-05-07")).toBeInTheDocument();
  });

  it("badge hidden when data is undefined (loading state)", () => {
    // WHY: during loading, data is undefined. The badge must not flash
    // with zero/incorrect counts before the real data arrives.
    (useQuery as ReturnType<typeof vi.fn>).mockReturnValue({ data: undefined });

    const { container } = render(<BriefDiffBadge token="test-token" briefId="brief-123" />);
    expect(container.firstChild).toBeNull();
  });
});
