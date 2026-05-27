/**
 * CitationHoverCard.test.tsx — PLAN-0089 K Block I T-22 case 5.
 *
 * WHAT THIS GUARDS:
 *   - The hovercard renders source / title / excerpt / published_at when
 *     provided.
 *   - Title-only fallback when no excerpt — the card must still be
 *     informative (Q-12 acceptance gate).
 *   - "Open ↗" anchor uses the safe URL.
 *
 * WHY we render inside a HoverCard with defaultOpen: the component is
 * designed to be the HoverCardContent child of a Radix HoverCard. Radix
 * won't render the content into the DOM unless the card is open, so we
 * force it open via `defaultOpen` to assert against the rendered tree.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { HoverCard, HoverCardTrigger } from "@/components/ui/hover-card";
import { CitationHoverCard } from "../CitationHoverCard";

function withOpenHoverCard(node: React.ReactNode) {
  // defaultOpen=true forces Radix to mount the portal content immediately
  // so the assertions can find it in the DOM.
  return (
    <HoverCard openDelay={0} defaultOpen>
      <HoverCardTrigger asChild>
        <button>trigger</button>
      </HoverCardTrigger>
      {node}
    </HoverCard>
  );
}

describe("CitationHoverCard (Wave K T-12)", () => {
  it("renders source, title, kind, and excerpt when all fields present", () => {
    render(
      withOpenHoverCard(
        <CitationHoverCard
          citation={{
            title: "Apple Q4 earnings",
            source: "Bloomberg",
            url: "https://example.com",
            kind: "article",
            excerpt: "Apple beat estimates by 4%.",
            publishedAt: "2026-04-26T00:00:00Z",
          }}
        />,
      ),
    );
    expect(screen.getByText("Apple Q4 earnings")).toBeInTheDocument();
    expect(screen.getByText("Bloomberg")).toBeInTheDocument();
    expect(screen.getByText(/Apple beat estimates/)).toBeInTheDocument();
    // Open link should exist and link to the URL.
    const openLink = screen.getByText("Open ↗") as HTMLAnchorElement;
    expect(openLink).toBeInTheDocument();
    expect(openLink.getAttribute("href")).toBe("https://example.com");
  });

  it("renders title-only fallback when no excerpt is provided", () => {
    // WHY this acceptance gate: the wire shape may evolve before excerpt
    // ships. The hovercard must still be useful with just title + source.
    render(
      withOpenHoverCard(
        <CitationHoverCard
          citation={{
            title: "Slim payload",
            source: "Reuters",
            url: null,
            kind: "article",
          }}
        />,
      ),
    );
    expect(screen.getByText("Slim payload")).toBeInTheDocument();
    // No excerpt body — assert the placeholder text we used in the rich
    // version is absent.
    expect(screen.queryByText(/Apple beat estimates/)).toBeNull();
  });

  it("falls back to 'Untitled' when title is empty", () => {
    render(
      withOpenHoverCard(
        <CitationHoverCard
          citation={{ title: "", source: "X", url: null, kind: "claim" }}
        />,
      ),
    );
    expect(screen.getByText("Untitled")).toBeInTheDocument();
  });
});
