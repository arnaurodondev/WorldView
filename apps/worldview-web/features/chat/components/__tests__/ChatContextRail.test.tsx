/**
 * ChatContextRail.test.tsx — PLAN-0089 K Block I T-22 case 10.
 *
 * WHAT THIS GUARDS:
 *   - Renders all four section headings (entity / recent citations /
 *     contradictions / related) UNCONDITIONALLY — empty sections must
 *     show an "—" placeholder rather than disappearing entirely. The
 *     stable visual rhythm is a Bloomberg-grade requirement.
 *   - Q-4 dedup: a citation referenced twice appears once with a
 *     "· 2×" count suffix in the recent-citations section.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ChatContextRail } from "../ChatContextRail";
import type { Message } from "@/types/api";

function withTooltip(ui: React.ReactNode) {
  return <TooltipProvider>{ui}</TooltipProvider>;
}

describe("ChatContextRail (Wave K T-16)", () => {
  it("renders all four section headings even when every section is empty", () => {
    // WHY: hiding empty sections would shift other sections up between
    // turns, disorienting the analyst. The placeholder "—" line keeps
    // the layout stable.
    render(
      withTooltip(
        <ChatContextRail threadId="t-1" messages={[]} activeEntity={null} />,
      ),
    );
    // SectionHeading text is lowercase per the design spec.
    expect(screen.getByText("entity")).toBeInTheDocument();
    expect(screen.getByText("recent citations")).toBeInTheDocument();
    expect(screen.getByText("contradictions")).toBeInTheDocument();
    expect(screen.getByText("related")).toBeInTheDocument();
  });

  it("renders the '—' placeholder when sections have no data", () => {
    const { container } = render(
      withTooltip(<ChatContextRail threadId="t-1" messages={[]} />),
    );
    // At least one — placeholder visible (recent citations / contradictions
    // / related sections all empty for an empty messages array).
    const placeholders = Array.from(container.querySelectorAll("[data-cell]"))
      .filter((el) => el.textContent?.trim() === "—");
    expect(placeholders.length).toBeGreaterThanOrEqual(1);
  });

  it("dedupes recent citations and adds the '· N×' count suffix", () => {
    // Same citation id twice across two assistant turns. Q-4 lock says
    // the rail should fold them into one row with "· 2×".
    const c1 = {
      id: "c-1",
      kind: "article" as const,
      title: "Apple Q4",
      source: "Bloomberg",
      url: null,
      relevance_score: 0.8,
    };
    const messages: Message[] = [
      {
        message_id: "m1",
        thread_id: "t",
        role: "assistant",
        content: "x",
        created_at: "2026-01-01T00:00:00Z",
        // Cast through unknown because Message.citations is typed legacy
        // but useChatStream populates with CitationV2 shape (file header).
        citations: [c1] as unknown as Message["citations"],
      },
      {
        message_id: "m2",
        thread_id: "t",
        role: "assistant",
        content: "y",
        created_at: "2026-01-01T00:01:00Z",
        citations: [c1] as unknown as Message["citations"],
      },
    ];
    render(
      withTooltip(<ChatContextRail threadId="t" messages={messages} />),
    );
    expect(screen.getByText(/· 2×/)).toBeInTheDocument();
  });
});
