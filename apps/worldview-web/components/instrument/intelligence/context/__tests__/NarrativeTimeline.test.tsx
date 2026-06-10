/**
 * NarrativeTimeline.test.tsx — narrative history timeline (Round-2 item 4).
 *
 * CONTRACTS PINNED:
 *   1. Entries render newest-first regardless of input order.
 *   2. Each entry shows its date + headline.
 *   3. Sentiment dots use the semantic colour tokens when sentiment is
 *      provided — and render a hollow (non-sentiment) marker when absent,
 *      so "unscored" can never be misread as "neutral".
 *   4. Named empty state for zero entries.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  NarrativeTimeline,
  type NarrativeTimelineEntry,
} from "@/components/instrument/intelligence/context/NarrativeTimeline";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const ENTRIES: NarrativeTimelineEntry[] = [
  {
    id: "v1",
    date: "2026-04-01T10:00:00Z",
    headline: "Oldest narrative headline.",
    sentiment: "negative",
  },
  {
    id: "v3",
    date: "2026-06-01T10:00:00Z",
    headline: "Newest narrative headline.",
    sentiment: "positive",
    fullText: "Newest narrative headline. Full body of the newest narrative.",
  },
  {
    id: "v2",
    date: "2026-05-01T10:00:00Z",
    headline: "Middle narrative headline.",
    // No sentiment — backend does not provide it (hollow marker path).
  },
];

// ── Tests ────────────────────────────────────────────────────────────────────

describe("NarrativeTimeline", () => {
  it("renders entries newest-first regardless of input order", () => {
    render(<NarrativeTimeline entries={ENTRIES} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Newest narrative headline.");
    expect(items[1]).toHaveTextContent("Middle narrative headline.");
    expect(items[2]).toHaveTextContent("Oldest narrative headline.");
  });

  it("shows the formatted date for each entry", () => {
    render(<NarrativeTimeline entries={ENTRIES} />);
    expect(screen.getByText("1 Jun 26")).toBeInTheDocument();
    expect(screen.getByText("1 May 26")).toBeInTheDocument();
    expect(screen.getByText("1 Apr 26")).toBeInTheDocument();
  });

  it("maps sentiment to semantic colour tokens on the timeline dot", () => {
    render(<NarrativeTimeline entries={ENTRIES} />);
    const dots = screen.getAllByTestId("timeline-dot");
    // Newest-first order: positive (v3), no-sentiment (v2), negative (v1).
    expect(dots[0]!.className).toContain("bg-positive");
    expect(dots[2]!.className).toContain("bg-negative");
  });

  it("renders a hollow marker (NOT a neutral dot) when sentiment is absent", () => {
    render(<NarrativeTimeline entries={ENTRIES} />);
    const dots = screen.getAllByTestId("timeline-dot");
    const middle = dots[1]!;
    // Hollow: transparent fill + border — distinct from bg-muted-foreground
    // which is reserved for an EXPLICIT "neutral" classification.
    expect(middle.className).toContain("bg-transparent");
    expect(middle.className).toContain("border");
    expect(middle.className).not.toContain("bg-muted-foreground ");
  });

  it("renders an explicit neutral classification with the muted filled dot", () => {
    render(
      <NarrativeTimeline
        entries={[{ id: "n1", date: "2026-06-02T00:00:00Z", headline: "Neutral take.", sentiment: "neutral" }]}
      />,
    );
    expect(screen.getByTestId("timeline-dot").className).toContain("bg-muted-foreground");
  });

  it("exposes the full narrative behind a disclosure when fullText is given", () => {
    render(<NarrativeTimeline entries={ENTRIES} />);
    expect(
      screen.getByText("Newest narrative headline. Full body of the newest narrative."),
    ).toBeInTheDocument();
  });

  it("renders the named empty state for zero entries", () => {
    render(<NarrativeTimeline entries={[]} />);
    expect(screen.getByText("No narrative history")).toBeInTheDocument();
  });
});
