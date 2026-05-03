/**
 * __tests__/structured-brief.test.tsx — StructuredBrief component tests (T-W4-D-02)
 *
 * WHY THIS EXISTS:
 * StructuredBrief is the shared rendering engine for PLAN-0062-W4 briefs across
 * four surfaces (MorningBriefCard, InstrumentBriefPanel, InstrumentAISubheader,
 * MessageBubble). Testing it in isolation here verifies:
 *
 *   1. All three variants render correctly ("full", "compact", "inline")
 *   2. LeadProse renders in all variants when lead is present
 *   3. CitationChips renders per-bullet in "full" variant, hidden in "compact"
 *   4. Confidence badge only appears in "full" variant when confidence < 0.6
 *   5. Section titles and bullet text render correctly
 *   6. MAX_CITATION_CHIPS cap is enforced (3 chips, "+N more" for overflow)
 *   7. Empty sections array renders nothing (no empty section chrome)
 *   8. Null/absent lead renders no lead block (no orphan border-left stripe)
 *   9. Legacy BriefingCitation objects (source_id) render without crashing
 *  10. External article chips are Next.js Links; event/alert chips are plain spans
 *  11. data-testid markers are present for E2E test parity assertions
 *  12+ more assertions per spec
 *
 * WHY NOT USE SNAPSHOT TESTS:
 * Snapshot tests for UI components are brittle — any class name change in
 * Tailwind or HTML structure change breaks the snapshot without changing
 * behavior. We use explicit DOM queries (getByTestId, getByText, queryByTestId)
 * so tests describe WHAT the component does, not HOW it's structured.
 *
 * WHY MOCK next/link:
 * next/link uses the Next.js router context, which isn't available in jsdom.
 * We render it as a plain <a> so we can assert href attributes without mounting
 * the full App Router.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { BriefSection, BriefCitation, BriefingCitation } from "@/types/api";

// ── Next.js Link mock ─────────────────────────────────────────────────────────
// WHY: StructuredBrief and CitationChips use next/link for external citation
// chips. jsdom doesn't mount the App Router, so mock Link as a plain <a>.
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// ── Component import (after vi.mock) ─────────────────────────────────────────
import {
  StructuredBrief,
  LeadProse,
  CitationChips,
} from "@/components/brief/StructuredBrief";

// ── Fixture helpers ───────────────────────────────────────────────────────────

function makeCitation(overrides: Partial<BriefCitation> = {}): BriefCitation {
  return {
    document_id: "doc-1",
    source_type: "article",
    title: "Apple beats Q4 earnings",
    url: "https://reuters.com/aapl-q4",
    ...overrides,
  };
}

function makeBullet(text: string, citations: BriefCitation[] = [makeCitation()]) {
  return { text, citations };
}

function makeSection(title: string, bullets: string[] = ["Bullet A", "Bullet B"]): BriefSection {
  return {
    title,
    bullets: bullets.map((b) => makeBullet(b)),
  };
}

// ── LeadProse tests ───────────────────────────────────────────────────────────

describe("LeadProse", () => {
  it("renders the lead text", () => {
    render(<LeadProse lead="Markets opened higher on strong payrolls." />);
    expect(screen.getByTestId("brief-lead")).toHaveTextContent(
      "Markets opened higher on strong payrolls.",
    );
  });

  it("renders in compact variant (smaller font class)", () => {
    const { container } = render(
      <LeadProse lead="Compact lead text." variant="compact" />,
    );
    // WHY check for text-[10px] class: compact variant uses 10px base, full uses 11px.
    // This class change is the only visual difference between variants in LeadProse.
    expect(container.firstChild).toHaveClass("text-[10px]");
  });

  it("renders in inline variant with truncate class", () => {
    const { container } = render(
      <LeadProse lead="Inline lead text." variant="inline" />,
    );
    // WHY check truncate: inline variant is a single-line band — overflow must be truncated.
    expect(container.firstChild).toHaveClass("truncate");
  });

  it("has data-testid=brief-lead for E2E test parity", () => {
    render(<LeadProse lead="Some lead." />);
    expect(screen.getByTestId("brief-lead")).toBeInTheDocument();
  });
});

// ── CitationChips tests ───────────────────────────────────────────────────────

describe("CitationChips", () => {
  it("renders a chip for each citation", () => {
    const citations: BriefCitation[] = [
      makeCitation({ document_id: "d1", url: "https://reuters.com" }),
      makeCitation({ document_id: "d2", url: "https://bloomberg.com" }),
    ];
    render(<CitationChips citations={citations} />);
    // WHY check for domain text: chips show the source domain, not the full URL.
    expect(screen.getByText("reuters.com")).toBeInTheDocument();
    expect(screen.getByText("bloomberg.com")).toBeInTheDocument();
  });

  it("renders external article chips as links with href", () => {
    const citations: BriefCitation[] = [
      makeCitation({ document_id: "d1", url: "https://reuters.com/aapl" }),
    ];
    render(<CitationChips citations={citations} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "https://reuters.com/aapl");
  });

  it("renders event citations as plain spans (no link)", () => {
    const citations: BriefCitation[] = [
      makeCitation({ document_id: "evt-1", source_type: "event", url: null }),
    ];
    render(<CitationChips citations={citations} />);
    // WHY queryByRole("link"): event chips should NOT be links — verify absence.
    expect(screen.queryByRole("link")).toBeNull();
    // The chip content is still rendered as a span.
    expect(screen.getByTestId("citation-chips")).toBeInTheDocument();
  });

  it("caps rendered chips at max (default 3) and shows +N more", () => {
    // WHY 5 citations: tests the overflow behavior when a bullet has more
    // than MAX_CITATION_CHIPS sources cited.
    const citations: BriefCitation[] = [
      makeCitation({ document_id: "d1", url: "https://reuters.com" }),
      makeCitation({ document_id: "d2", url: "https://bloomberg.com" }),
      makeCitation({ document_id: "d3", url: "https://wsj.com" }),
      makeCitation({ document_id: "d4", url: "https://ft.com" }),
      makeCitation({ document_id: "d5", url: "https://cnbc.com" }),
    ];
    render(<CitationChips citations={citations} max={3} />);
    // Only first 3 domains should be visible
    expect(screen.getByText("reuters.com")).toBeInTheDocument();
    expect(screen.getByText("bloomberg.com")).toBeInTheDocument();
    expect(screen.getByText("wsj.com")).toBeInTheDocument();
    // ft.com and cnbc.com are hidden (overflow)
    expect(screen.queryByText("ft.com")).toBeNull();
    // Overflow indicator: "+2 more"
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("renders no overflow indicator when citations ≤ max", () => {
    const citations: BriefCitation[] = [makeCitation({ document_id: "d1" })];
    render(<CitationChips citations={citations} />);
    expect(screen.queryByText(/\+ \d+ more/)).toBeNull();
  });

  it("works with legacy BriefingCitation objects", () => {
    // WHY: pre-W4 Top Stories chips come from BriefingCitation objects.
    // The CitationChips component must render them without crashing.
    const legacyCitations: BriefingCitation[] = [
      {
        source_id: "art-legacy-1",
        source_type: "article",
        title: "Legacy article",
        url: "https://legacy-news.com/article",
      },
    ];
    render(<CitationChips citations={legacyCitations} />);
    expect(screen.getByText("legacy-news.com")).toBeInTheDocument();
  });

  it("has data-testid=citation-chips for E2E test parity", () => {
    render(<CitationChips citations={[makeCitation()]} />);
    expect(screen.getByTestId("citation-chips")).toBeInTheDocument();
  });
});

// ── StructuredBrief full variant tests ───────────────────────────────────────

describe("StructuredBrief — full variant (default)", () => {
  it("renders the lead block when lead is provided", () => {
    render(
      <StructuredBrief
        lead="Markets opened higher."
        sections={[makeSection("Market Context")]}
      />,
    );
    expect(screen.getByTestId("brief-lead")).toHaveTextContent("Markets opened higher.");
  });

  it("omits lead block when lead is null", () => {
    render(<StructuredBrief lead={null} sections={[makeSection("Section A")]} />);
    expect(screen.queryByTestId("brief-lead")).toBeNull();
  });

  it("renders section titles", () => {
    render(
      <StructuredBrief
        sections={[makeSection("Market Context"), makeSection("Risk Factors")]}
      />,
    );
    expect(screen.getByText("Market Context")).toBeInTheDocument();
    expect(screen.getByText("Risk Factors")).toBeInTheDocument();
  });

  it("renders bullet text from BriefBullet.text", () => {
    render(
      <StructuredBrief
        sections={[
          {
            title: "Drivers",
            bullets: [makeBullet("Tech rallied 1.2%"), makeBullet("10Y yield fell 3bp")],
          },
        ]}
      />,
    );
    expect(screen.getByText("Tech rallied 1.2%")).toBeInTheDocument();
    expect(screen.getByText("10Y yield fell 3bp")).toBeInTheDocument();
  });

  it("renders citation chips in full variant", () => {
    const cit = makeCitation({ document_id: "d1", url: "https://reuters.com/story" });
    render(
      <StructuredBrief
        sections={[{ title: "S", bullets: [makeBullet("Some claim", [cit])] }]}
      />,
    );
    expect(screen.getByTestId("citation-chips")).toBeInTheDocument();
  });

  it("renders confidence badge when confidence < 0.6", () => {
    render(
      <StructuredBrief
        sections={[makeSection("S")]}
        confidence={0.42}
      />,
    );
    expect(screen.getByTestId("confidence-indicator")).toBeInTheDocument();
    expect(screen.getByText(/Low confidence/)).toBeInTheDocument();
  });

  it("does NOT render confidence badge when confidence >= 0.6", () => {
    render(
      <StructuredBrief
        sections={[makeSection("S")]}
        confidence={0.85}
      />,
    );
    // WHY queryByTestId (not getByTestId): when confidence is high (normal case)
    // the badge MUST NOT render — asserting absence, not presence.
    expect(screen.queryByTestId("confidence-indicator")).toBeNull();
  });

  it("does NOT render confidence badge when confidence is absent", () => {
    render(<StructuredBrief sections={[makeSection("S")]} />);
    expect(screen.queryByTestId("confidence-indicator")).toBeNull();
  });

  it("renders no sections chrome when sections is empty", () => {
    render(<StructuredBrief lead="Just a lead." sections={[]} />);
    // The brief-sections container must not exist when there's nothing to render.
    expect(screen.queryByTestId("brief-sections")).toBeNull();
  });

  it("has data-testid=structured-brief for E2E assertions", () => {
    render(<StructuredBrief sections={[makeSection("S")]} />);
    expect(screen.getByTestId("structured-brief")).toBeInTheDocument();
  });

  it("shows percentage confidence in the badge (e.g. 42%)", () => {
    render(<StructuredBrief sections={[makeSection("S")]} confidence={0.42} />);
    // WHY check "42%": confidence is displayed as round(0.42 * 100) + "%" = "42%"
    expect(screen.getByText(/42%/)).toBeInTheDocument();
  });
});

// ── StructuredBrief compact variant tests ────────────────────────────────────

describe("StructuredBrief — compact variant", () => {
  it("renders section titles and bullet text", () => {
    render(
      <StructuredBrief
        variant="compact"
        sections={[{ title: "Compact Section", bullets: [makeBullet("Compact bullet")] }]}
      />,
    );
    expect(screen.getByText("Compact Section")).toBeInTheDocument();
    expect(screen.getByText("Compact bullet")).toBeInTheDocument();
  });

  it("does NOT render citation chips in compact variant", () => {
    // WHY: compact variant suppresses citation chips to save vertical space.
    render(
      <StructuredBrief
        variant="compact"
        sections={[
          { title: "S", bullets: [makeBullet("Bullet with citation", [makeCitation()])] },
        ]}
      />,
    );
    expect(screen.queryByTestId("citation-chips")).toBeNull();
  });

  it("does NOT render confidence badge in compact variant (even when low)", () => {
    render(
      <StructuredBrief
        variant="compact"
        sections={[makeSection("S")]}
        confidence={0.1}
      />,
    );
    // WHY: compact is a space-constrained panel — no badge regardless of score.
    expect(screen.queryByTestId("confidence-indicator")).toBeNull();
  });
});

// ── StructuredBrief inline variant tests ─────────────────────────────────────

describe("StructuredBrief — inline variant", () => {
  it("renders lead text in inline mode", () => {
    render(<StructuredBrief variant="inline" lead="Inline lead text." />);
    expect(screen.getByTestId("brief-lead")).toHaveTextContent("Inline lead text.");
  });

  it("does NOT render sections in inline variant", () => {
    // WHY: inline is a single-line band — sections are never shown.
    render(
      <StructuredBrief
        variant="inline"
        lead="Lead."
        sections={[makeSection("Hidden Section")]}
      />,
    );
    expect(screen.queryByText("Hidden Section")).toBeNull();
  });

  it("renders confidence indicator in inline mode when confidence < threshold", () => {
    // WHY: inline variant DOES show a confidence chip (compact version) for
    // InstrumentAISubheader — the confidence is a key signal in the subheader.
    render(
      <StructuredBrief
        variant="inline"
        lead="Lead."
        confidence={0.35}
      />,
    );
    expect(screen.getByTestId("confidence-indicator")).toBeInTheDocument();
  });

  it("shows bullet count fallback when lead is absent", () => {
    // WHY: when the S8 backend didn't emit a lead block (pre-W4 brief), the inline
    // variant shows a "N points" count as a placeholder rather than an empty band.
    render(
      <StructuredBrief
        variant="inline"
        sections={[
          { title: "S1", bullets: [makeBullet("A"), makeBullet("B")] },
          { title: "S2", bullets: [makeBullet("C")] },
        ]}
      />,
    );
    // 3 bullets total → "3 points"
    expect(screen.getByText("3 points")).toBeInTheDocument();
  });
});
