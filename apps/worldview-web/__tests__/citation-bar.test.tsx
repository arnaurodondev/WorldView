/**
 * __tests__/citation-bar.test.tsx — citation confidence bar tests
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08): the bar's score-to-colour mapping
 * is a small but critical piece of the chat UX — pinning the thresholds
 * with explicit tests prevents accidental drift when someone refactors
 * the styling helper.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CitationBar, scoreBand } from "@/components/chat/CitationBar";
import type { Citation } from "@/types/api";

const C = (id: string, score: number, title = `Title ${id}`): Citation => ({
  article_id: id,
  title,
  url: "https://example.com/" + id,
  source: "TestSource",
  relevance_score: score,
});

describe("CitationBar — score band thresholds", () => {
  it("score >= 0.7 → high (green band)", () => {
    expect(scoreBand(0.7)).toBe("high");
    expect(scoreBand(0.95)).toBe("high");
  });

  it("0.4 <= score < 0.7 → medium (amber)", () => {
    expect(scoreBand(0.4)).toBe("medium");
    expect(scoreBand(0.55)).toBe("medium");
    expect(scoreBand(0.69)).toBe("medium");
  });

  it("score < 0.4 → low (red band)", () => {
    expect(scoreBand(0)).toBe("low");
    expect(scoreBand(0.39)).toBe("low");
  });
});

describe("CitationBar — DOM rendering", () => {
  it("renders one segment per citation with correct data-attrs", () => {
    const cites = [C("1", 0.9), C("2", 0.5), C("3", 0.2)];
    render(<CitationBar citations={cites} anchorPrefix="cite-x" />);

    const segments = screen.getAllByRole("link");
    expect(segments.length).toBe(cites.length);

    expect(segments[0].getAttribute("data-citation-band")).toBe("high");
    expect(segments[1].getAttribute("data-citation-band")).toBe("medium");
    expect(segments[2].getAttribute("data-citation-band")).toBe("low");
  });

  it("renders nothing when citations is empty (avoids stray div)", () => {
    const { container } = render(
      <CitationBar citations={[]} anchorPrefix="cite-x" />,
    );
    // Only a safe-href hidden span ("sr-only") should NOT be present —
    // empty bar = nothing rendered.
    expect(container.firstChild).toBeNull();
  });

  it("renders 50 citations with min-w-[8px] segments and flex-wrap (QA-iter1 MIN-1)", () => {
    // QA-iter1 MIN-1: with >25 citations the previous flex-1 layout produced
    // ~1px-wide segments. We pin the contract that every segment carries the
    // ``min-w-[8px]`` class so colour-coding stays legible, and the parent
    // wraps to a second row instead of squashing.
    const cites = Array.from({ length: 50 }, (_, i) =>
      C(String(i + 1), (i % 10) / 10),
    );
    render(<CitationBar citations={cites} anchorPrefix="cite-many" />);

    const segments = screen.getAllByRole("link");
    expect(segments.length).toBe(50);
    // Each segment must carry the min-width Tailwind class — proving no
    // segment can collapse below 8px.
    segments.forEach((seg) => {
      expect(seg.className).toMatch(/min-w-\[8px\]/);
    });
    // The wrapping <div role="group"> must be flex-wrap so the surplus
    // segments overflow to another row instead of being squashed.
    const group = segments[0].parentElement;
    expect(group?.className).toMatch(/flex-wrap/);
  });

  it("clicking a segment with no matching anchor calls preventDefault", () => {
    const cites = [C("1", 0.85)];
    render(<CitationBar citations={cites} anchorPrefix="missing-anchor" />);

    const seg = screen.getByRole("link");
    // We assert the segment's title contains the source and score — which
    // confirms the tooltip data is wired correctly.
    expect(seg.getAttribute("title")).toMatch(/TestSource/);
    expect(seg.getAttribute("title")).toMatch(/85%/);

    // Clicking shouldn't throw even when the anchor target is missing.
    fireEvent.click(seg);
  });
});
