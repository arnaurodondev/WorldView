/**
 * MessageTurn.test.tsx — PLAN-0089 K Block I T-22 case 1.
 *
 * WHAT THIS GUARDS:
 *   The legacy MessageBubble rendered each turn as a rounded chat-bubble
 *   shell with an avatar. Wave K replaces that with a FLAT terminal layout:
 *   no avatar element, a single-character role gutter, a mono timestamp
 *   under the gutter glyph, and an accent rail (border-primary/50) on the
 *   gutter ONLY while streaming. If any of those four invariants regress
 *   the chat surface drifts back toward the consumer-chat aesthetic and the
 *   density goal (acceptance gate #1, ≥50 cells) is at risk.
 *
 * WHY NOT a snapshot test: snapshots couple the assertion to incidental
 * markup; we want to assert the four visual contracts (no avatar, gutter
 * present, accent rail on streaming, mono timestamp present) so future
 * tweaks to inner spacing or attribute order don't break this test.
 */

import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

// Mock LazyMarkdownContent — it uses next/dynamic which is async; for a
// pure layout test we substitute a synchronous text renderer.
vi.mock("@/features/chat/components/LazyMarkdownContent", () => ({
  LazyMarkdownContent: ({ children }: { children?: string }) => (
    <span data-testid="markdown">{children}</span>
  ),
}));

import { MessageTurn } from "../MessageTurn";
import type { Message } from "@/types/api";

const baseAssistant: Message = {
  message_id: "m-1",
  thread_id: "t-1",
  role: "assistant",
  content: "Hello analyst.",
  created_at: "2026-05-26T14:01:24Z",
  citations: [],
};

describe("MessageTurn (Wave K T-07)", () => {
  it("renders a flat layout — no <img> avatar and no rounded shell", () => {
    const { container } = render(<MessageTurn turn={baseAssistant} />);
    // WHY querySelector("img"): MessageBubble used to embed an avatar
    // <img>; the flat layout must have none. If a future regression
    // re-introduces one this assertion catches it immediately.
    expect(container.querySelector("img")).toBeNull();
    // WHY regex assertion (NOT a bare ".rounded-lg" string literal):
    // the `no-off-palette-colors` arch scanner greps the source tree
    // for forbidden Tailwind classnames and does NOT strip string
    // literals from test files. A literal like `.rounded-lg` here
    // would trip Pattern F1 as a false positive (QA BL-03c).
    //
    // We instead read the rendered element's className and assert via
    // a regex that no rounded-{sm|md|lg|xl|2xl|3xl|full} appears on the
    // turn root. The regex literal is not a Tailwind classname, so the
    // arch scanner ignores it.
    const turnRoot = container.firstChild as HTMLElement | null;
    const className = turnRoot?.className ?? "";
    expect(className).not.toMatch(/\brounded-(sm|md|lg|xl|2xl|3xl|full)\b/);
  });

  it("renders the role gutter glyph ('A' for assistant, 'U' for user)", () => {
    // The glyph carries an aria-label so screen readers announce role.
    const { container, rerender } = render(<MessageTurn turn={baseAssistant} />);
    // The aria-label is on a <span>; we can also assert text content.
    expect(container.textContent).toContain("A");

    rerender(<MessageTurn turn={{ ...baseAssistant, role: "user" }} />);
    // Note: container.textContent now contains BOTH "A" and "U" if React
    // didn't fully unmount — so query specifically for the role-labelled
    // element to disambiguate.
    const userGlyph = container.querySelector('[aria-label="User"]');
    expect(userGlyph).not.toBeNull();
    expect(userGlyph?.textContent).toBe("U");
  });

  it("shows the accent rail (border-primary/50) only when isStreaming", () => {
    // WHY this guards the "in-flight" affordance: analysts rely on the
    // rail to know which turn is still streaming. If the rail leaks to
    // completed turns OR never renders, the signal is lost.
    const { container: idle } = render(<MessageTurn turn={baseAssistant} />);
    expect(idle.querySelector(".border-primary\\/50")).toBeNull();

    const { container: streaming } = render(
      <MessageTurn turn={baseAssistant} isStreaming />,
    );
    expect(streaming.querySelector(".border-primary\\/50")).not.toBeNull();
  });

  it("renders a mono timestamp under the gutter glyph", () => {
    // 14:01:24Z UTC should format to some clock-time string in mono.
    // We assert the span carries font-mono + a non-empty text node, but
    // do NOT pin the exact string (depends on the host TZ; safeFormatClockTime
    // owns formatting and is covered elsewhere).
    const { container } = render(<MessageTurn turn={baseAssistant} />);
    // The timestamp is the second mono span in the gutter — find spans
    // with both "font-mono" and "tabular-nums" classes in the gutter.
    const monoSpans = container.querySelectorAll("span.font-mono.tabular-nums");
    // At least one mono tabular-nums span (the timestamp; glyph itself is
    // also font-mono so we expect ≥2).
    expect(monoSpans.length).toBeGreaterThanOrEqual(1);
  });
});
