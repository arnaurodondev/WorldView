/**
 * components/ui/__tests__/SentimentBadge.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0091 C-2):
 * SentimentBadge renders "POS"/"NEG"/"NEU"/"MIX" pills in the Intelligence
 * tab news rail. Four tests pin the exact rendering contract so a future
 * refactor that accidentally swaps colors or labels catches in CI.
 *
 * TEST STRATEGY:
 * Render the component with each sentiment variant and assert:
 *   1. The correct label text is rendered.
 *   2. The correct color class is present on the element.
 *   3. null/undefined sentiment renders nothing (returns null).
 *
 * WHY no QueryClient wrapper:
 * SentimentBadge is a pure presentational component — it takes a prop and
 * renders markup. No hooks, no queries, no context needed.
 *
 * WHY we check class strings (not CSS-in-JS computed styles):
 * The badge uses Tailwind classes with inline hex colors (e.g. text-[#26A69A]).
 * jsdom doesn't compute CSS variables so testing computed style would always
 * return "". Checking the class name is the correct assertion for Tailwind.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SentimentBadge } from "@/components/ui/sentiment-badge";

describe("SentimentBadge", () => {
  it('renders "POS" with positive color classes for sentiment="positive"', () => {
    render(<SentimentBadge sentiment="positive" />);

    // WHY getByText (not getByRole): the badge is a <span>, not a button/heading.
    // Text is the stable contract — "POS" must always be the positive label.
    const badge = screen.getByText("POS");
    expect(badge).toBeDefined();

    // Verify the positive teal color class is present.
    // WHY toContain (not toEqual): Tailwind cn() may add more classes from the
    // className prop or base styles; we only care the color class is included.
    expect(badge.className).toContain("text-[#26A69A]");
    expect(badge.className).toContain("bg-[#26A69A]/10");
    expect(badge.className).toContain("border-[#26A69A]/30");
  });

  it('renders "NEG" with negative color classes for sentiment="negative"', () => {
    render(<SentimentBadge sentiment="negative" />);

    const badge = screen.getByText("NEG");
    expect(badge).toBeDefined();

    // Verify the negative red color class is present.
    expect(badge.className).toContain("text-[#EF5350]");
    expect(badge.className).toContain("bg-[#EF5350]/10");
    expect(badge.className).toContain("border-[#EF5350]/30");
  });

  it('renders "MIX" with warning color classes for sentiment="mixed"', () => {
    render(<SentimentBadge sentiment="mixed" />);

    const badge = screen.getByText("MIX");
    expect(badge).toBeDefined();

    // Verify the warning amber color class is present.
    expect(badge.className).toContain("text-[#FFB000]");
    expect(badge.className).toContain("bg-[#FFB000]/10");
    expect(badge.className).toContain("border-[#FFB000]/30");
  });

  it("renders nothing (null) for sentiment={null}", () => {
    // WHY container check: when a component returns null React renders nothing,
    // but render() still returns a container. We assert the container is empty
    // (no child nodes) rather than querying for an element that shouldn't exist.
    const { container } = render(<SentimentBadge sentiment={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing (null) for sentiment={undefined}", () => {
    // WHY separate test for undefined: TypeScript allows `undefined` via the
    // optional props pattern. Both null and undefined must be guarded.
    const { container } = render(<SentimentBadge sentiment={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders "NEU" with muted color classes for sentiment="neutral"', () => {
    render(<SentimentBadge sentiment="neutral" />);

    const badge = screen.getByText("NEU");
    expect(badge).toBeDefined();

    // Neutral should use muted foreground — NOT a bright accent color.
    expect(badge.className).toContain("text-muted-foreground");
  });
});
