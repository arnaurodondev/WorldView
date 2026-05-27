/**
 * CitationStrip.test.tsx — PLAN-0089 K Block I T-22 case 4.
 *
 * WHAT THIS GUARDS:
 *   - Renders the V2 wire shape ({id, kind, title, source, url, relevance_score}).
 *   - Q-12 low-confidence chip appears when relevance_score < 0.6.
 *   - Click on a row triggers scrollIntoView on the matching inline anchor
 *     (DOM mutation guarded via spy on the global).
 *   - NaN% guard: when relevance_score is undefined the row MUST NOT render
 *     literal text containing "NaN" (the Q-10 drift bug we fixed).
 *   - Returns null on empty arrays — the strip never renders an empty box.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { CitationStrip } from "../CitationStrip";
import type { CitationV2 } from "@/types/api";

const baseCite: CitationV2 = {
  id: "c-1",
  kind: "article",
  title: "Apple Q4 earnings",
  source: "Bloomberg",
  url: "https://example.com",
  relevance_score: 0.82,
};

describe("CitationStrip (Wave K T-10)", () => {
  beforeEach(() => {
    // jsdom does not implement scrollIntoView; without a mock the click
    // handler would crash before we can assert it was called.
    // WHY HTMLElement (not Element): vitest.setup.ts stubs the method
    // specifically on HTMLElement.prototype — when the call site reaches
    // a span (the citation anchor) we must override the same prototype
    // the setup file installed, or scrollIntoView resolves to the inert
    // setup-file no-op instead of our spy.
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it("returns null on empty arrays", () => {
    const { container } = render(<CitationStrip citations={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a row per citation with the V2 shape", () => {
    const { container } = render(<CitationStrip citations={[baseCite]} />);
    // Each row carries data-citation-row={ref} — stable selector.
    const row = container.querySelector("[data-citation-row]");
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain("Apple Q4 earnings");
    expect(row?.textContent).toContain("Bloomberg");
    expect(row?.textContent).toContain("82%");
  });

  it("renders the low-conf chip when relevance_score < 0.6", () => {
    const lowConf: CitationV2 = { ...baseCite, id: "c-2", relevance_score: 0.42 };
    const { container } = render(<CitationStrip citations={[lowConf]} />);
    // "low-conf" string per Q-12 — appears only below the 0.6 threshold.
    expect(container.textContent).toContain("low-conf");
  });

  it("does NOT render NaN% when relevance_score is undefined (Q-10 drift bug guard)", () => {
    // WHY this assertion: pre-Wave-K the strip rendered "NaN%" when the
    // backend forgot to attach relevance_score. The fix returns null from
    // formatPercent — so the text "NaN" must NEVER appear in the DOM.
    const undefScore: CitationV2 = {
      id: "c-3",
      kind: "article",
      title: "Missing score",
      source: "Reuters",
      url: null,
      // relevance_score intentionally omitted
    };
    const { container } = render(<CitationStrip citations={[undefScore]} />);
    expect(container.textContent).not.toContain("NaN");
  });

  it("calls scrollIntoView when a row is clicked", () => {
    // We render the strip alongside a synthetic anchor with the matching
    // data-citation-ref. Clicking the row should trigger scrollIntoView
    // on the anchor (jsdom mock).
    //
    // WHY assign to prototype BEFORE render: the CitationStrip's click
    // handler resolves Element.prototype.scrollIntoView lazily inside
    // scrollToAnchor — assigning before render guarantees the spy is the
    // active method when the handler queries it.
    const scrollSpy = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scrollSpy;
    // requestAnimationFrame is called after scrollIntoView for the flash
    // effect; stub it so it doesn't try to schedule against a missing
    // jsdom impl. We don't care about the flash for this assertion.
    window.requestAnimationFrame = vi.fn() as unknown as typeof window.requestAnimationFrame;
    const { container } = render(
      <div>
        <span data-citation-ref="1">anchor</span>
        <CitationStrip citations={[baseCite]} />
      </div>,
    );
    const row = container.querySelector("[data-citation-row]") as HTMLElement;
    // WHY direct invocation of onclick via fireEvent.click on the row:
    // CitationStrip wraps the row inside <HoverCardTrigger asChild> which
    // clones the button. The button's own onClick handler is preserved
    // and fires on a synthetic click event.
    fireEvent.click(row);
    expect(scrollSpy).toHaveBeenCalled();
  });
});
