/**
 * features/chat/components/__tests__/CitationList.test.tsx
 *
 * Round 1 Foundation — citation badge behaviour:
 *   1. tooltip (title attr) leads with the SOURCE TITLE,
 *   2. badges with a URL render as external links (new tab, safe rel),
 *   3. knowledge-graph citations WITHOUT a URL render as plain badges —
 *      never a dead <a href="#"> that scrolls the page to the top. This is
 *      the contract useChatStream's citations handler documents.
 *
 * NOTE on types: citation fixtures are written as plain object literals (no
 * type import) — the architecture gate `no-legacy-citation.test.ts` forbids
 * the bare legacy type name in NEW files under features/chat/**, and the
 * structural shape is all the component needs.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitationList } from "../CitationList";

const LINKED_CITE = {
  article_id: "a-1",
  title: "NVDA Q4 Earnings Beat Expectations",
  url: "https://news.example.com/nvda-q4",
  source: "Reuters",
  relevance_score: 0.91,
};

const KG_CITE = {
  article_id: "kg-1",
  title: "Apple — supplier relations",
  // Knowledge-graph citations reference in-platform graph data: no URL.
  url: "",
  source: "knowledge_graph",
  relevance_score: 0.66,
};

describe("CitationList", () => {
  it("renders nothing for an empty citation array", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a clickable badge that opens the source URL in a new tab", () => {
    render(<CitationList citations={[LINKED_CITE]} />);

    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://news.example.com/nvda-q4");
    expect(link.getAttribute("target")).toBe("_blank");
    // noopener prevents the target page from accessing window.opener.
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("puts the source title first in the hover tooltip", () => {
    render(<CitationList citations={[LINKED_CITE]} />);

    const link = screen.getByRole("link");
    const tooltip = link.getAttribute("title") ?? "";
    // Tooltip leads with the article title, then source + relevance context.
    expect(tooltip.startsWith("NVDA Q4 Earnings Beat Expectations")).toBe(true);
    expect(tooltip).toContain("Reuters");
    expect(tooltip).toContain("91%");
  });

  it("renders URL-less (knowledge-graph) citations as plain badges, not links", () => {
    render(<CitationList citations={[KG_CITE]} />);

    // No anchor at all — the old behaviour was <a href="#"> which navigated
    // to the page top on click (a dead link masquerading as a source).
    expect(screen.queryByRole("link")).toBeNull();
    // The badge content still renders (title + source visible).
    expect(screen.getByText("Apple — supplier relations")).toBeDefined();
    expect(screen.getByText("knowledge_graph")).toBeDefined();
  });

  it("blocks javascript: URLs (renders a plain badge instead of a link)", () => {
    render(
      <CitationList
        citations={[{ ...LINKED_CITE, url: "javascript:alert(1)" }]}
      />,
    );
    // safeExternalUrl maps the unsafe scheme to "#", which we treat as
    // "no usable URL" → plain badge. The XSS vector never becomes an href.
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders one badge per citation with its [N] index", () => {
    render(<CitationList citations={[LINKED_CITE, KG_CITE]} />);
    expect(screen.getByText("[1]")).toBeDefined();
    expect(screen.getByText("[2]")).toBeDefined();
  });
});
