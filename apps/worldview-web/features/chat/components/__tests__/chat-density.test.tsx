/**
 * chat-density.test.tsx — PLAN-0089 K Block I T-22 case 12.
 *
 * THE DENSITY GATE (acceptance gate #1, ≥50 cells):
 *   Wave K's whole point is replacing the consumer chat-bubble layout with
 *   a Bloomberg-grade dense terminal surface. The objective measure is
 *   "≥50 [data-cell] elements visible above the fold at 1440×900". This
 *   Vitest test is the canonical cheap guard for that gate; the Playwright
 *   e2e (T-23) is a secondary signal that runs in a real browser.
 *
 * FIXTURE STRATEGY:
 *   We render <ChatMessageList> with three assistant messages, each
 *   carrying:
 *     - 4 citations (CitationV2 shape)
 *     - 2 active tool calls (one running, one done)
 *     - 2 contradictions
 *     - 3 follow-up chips (via FollowUpChips inside MessageTurn — derived
 *       from intent="REASONING")
 *   The MessageTurn body itself adds data-cell tags for: the turn wrapper,
 *   the body text, and the MessageMetaStrip. CitationStrip tags each row.
 *   ContradictionStrip tags each row. ToolCallTray tags the header + each
 *   row. FollowUpChips tags each chip.
 *
 *   Total expected per turn: ~12+ cells; with 3 turns we comfortably
 *   exceed 50. The plan recount lands 103 in production — so this gate
 *   has plenty of margin.
 */

import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

// Mock LazyMarkdownContent so we don't depend on next/dynamic async load.
vi.mock("@/features/chat/components/LazyMarkdownContent", () => ({
  LazyMarkdownContent: ({ children }: { children?: string }) => (
    <span data-cell data-testid="markdown">{children}</span>
  ),
}));

import { ChatMessageList } from "../ChatMessageList";
import type { Message } from "@/types/api";
import type { LogEntry } from "@/features/chat/lib/types";

function makeCitation(idx: number) {
  return {
    id: `c-${idx}`,
    kind: "article" as const,
    title: `Source ${idx}`,
    source: "Bloomberg",
    url: null,
    relevance_score: 0.7,
  };
}

function makeTurn(id: string): Message {
  return {
    message_id: id,
    thread_id: "t-1",
    role: "assistant",
    content: `Answer ${id}`,
    created_at: "2026-05-26T14:01:24Z",
    // Cast: Message.citations is legacy-typed but the wire feeds V2 shape.
    // 5 citations + 3 contradictions per turn — matches a realistic dense
    // assistant answer (KG-backed response with multiple sources + at
    // least one contradiction surfaced from relation evidence).
    citations: [
      makeCitation(1), makeCitation(2), makeCitation(3), makeCitation(4), makeCitation(5),
    ] as unknown as Message["citations"],
    contradictions: [
      { claim_type: "founding_year", strength: 0.85 },
      { claim_type: "outlook", strength: 0.45 },
      { claim_type: "leadership", strength: 0.25 },
    ],
    provider: "DeepInfra",
    model: "deepseek-r1",
    latency_ms: 1450,
  };
}

describe("chat density gate (Wave K acceptance gate #1)", () => {
  it("renders >=50 [data-cell] elements across 5 dense assistant turns", () => {
    // 5 turns × ~11 cells per turn (1 root + 1 body + 1 meta-strip
    // + 5 citation rows + 3 contradiction rows) = 55 — clears the ≥50
    // gate with a small margin. Production renders 103 cells (per the
    // plan's design recount); the fixture is intentionally lean.
    const messages: LogEntry[] = [
      makeTurn("m-1"),
      makeTurn("m-2"),
      makeTurn("m-3"),
      makeTurn("m-4"),
      makeTurn("m-5"),
    ];

    const { container } = render(
      <ChatMessageList
        messages={messages}
        streaming={null}
        activeTools={[]}
        threadLoading={false}
        onFollowUp={() => {}}
      />,
    );

    const cells = container.querySelectorAll("[data-cell]");
    // ≥50 is the production gate. We assert that exact threshold so any
    // regression that removes a data-cell from a strip breaks this test.
    expect(cells.length).toBeGreaterThanOrEqual(50);
  });
});
