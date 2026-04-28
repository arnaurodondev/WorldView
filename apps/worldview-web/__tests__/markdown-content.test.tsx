/**
 * __tests__/markdown-content.test.tsx — Unit tests for MarkdownContent
 *
 * WHY THIS EXISTS: MarkdownContent centralises markdown rendering for every
 * surface that displays LLM output. Regressions in its custom element overrides
 * (table borders, code-block styling, link safety) would silently degrade the
 * morning brief, instrument intelligence, and AI chat surfaces all at once.
 * Tests pin the contract.
 *
 * COVERAGE:
 *   - Renders headings, paragraphs, lists
 *   - Tables get border-collapse + zebra styling
 *   - Code blocks get bg-muted/30 + font-mono
 *   - External links get target=_blank + rel=noopener noreferrer
 *   - "compact" vs "comfortable" size variants apply different base-text classes
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownContent } from "@/components/ui/markdown-content";

describe("MarkdownContent", () => {
  it("renders headings with size-appropriate classes", () => {
    render(<MarkdownContent>{"## Hello"}</MarkdownContent>);
    const h2 = screen.getByRole("heading", { level: 2, name: "Hello" });
    // Comfortable variant uses text-[13px]; the actual class string is the
    // contract, not the rendered font-size at runtime.
    expect(h2.className).toContain("text-[13px]");
    expect(h2.className).toContain("uppercase");
  });

  it("renders paragraphs with muted-foreground colour", () => {
    render(<MarkdownContent>This is a paragraph.</MarkdownContent>);
    const p = screen.getByText("This is a paragraph.");
    expect(p.tagName).toBe("P");
    expect(p.className).toContain("text-muted-foreground");
  });

  it("renders unordered lists with disc markers", () => {
    render(<MarkdownContent>{"- item one\n- item two"}</MarkdownContent>);
    expect(screen.getByText("item one").className).toContain("list-disc");
    expect(screen.getByText("item two").className).toContain("list-disc");
  });

  it("renders tables with border-collapse + bordered cells", () => {
    const md = `| h1 | h2 |\n| --- | --- |\n| a | b |`;
    const { container } = render(<MarkdownContent>{md}</MarkdownContent>);

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.className).toContain("border-collapse");
    expect(table?.className).toContain("border-border/40");

    // Zebra: tr should carry odd:bg-muted/20
    const tr = container.querySelector("tbody tr");
    expect(tr?.className).toContain("odd:bg-muted/20");
  });

  it("styles inline code with bg-muted/30 + font-mono", () => {
    render(<MarkdownContent>{"This is `inline code` here."}</MarkdownContent>);
    const code = screen.getByText("inline code");
    expect(code.tagName).toBe("CODE");
    expect(code.className).toContain("bg-muted/30");
    expect(code.className).toContain("font-mono");
    expect(code.className).toContain("rounded-[2px]");
  });

  it("renders code blocks inside <pre> with border + bg-muted/30", () => {
    const md = "```\nconst x = 1;\n```";
    const { container } = render(<MarkdownContent>{md}</MarkdownContent>);
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.className).toContain("bg-muted/30");
    expect(pre?.className).toContain("rounded-[2px]");
  });

  it("renders external links with target=_blank + rel=noopener noreferrer", () => {
    render(<MarkdownContent>{"[link](https://example.com)"}</MarkdownContent>);
    const a = screen.getByRole("link", { name: "link" });
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    expect(a.className).toContain("text-primary");
  });

  it("does not add target=_blank to relative links", () => {
    render(<MarkdownContent>{"[home](/dashboard)"}</MarkdownContent>);
    const a = screen.getByRole("link", { name: "home" });
    expect(a.getAttribute("target")).toBeNull();
  });

  it("compact variant uses 10px base font", () => {
    const { container } = render(
      <MarkdownContent size="compact">paragraph</MarkdownContent>,
    );
    expect(container.firstChild).not.toBeNull();
    expect((container.firstChild as HTMLElement).className).toContain("text-[10px]");
  });

  it("comfortable variant uses 12px base font", () => {
    const { container } = render(
      <MarkdownContent size="comfortable">paragraph</MarkdownContent>,
    );
    expect((container.firstChild as HTMLElement).className).toContain("text-[12px]");
  });

  it("renders blockquotes with left-rule + italic muted text", () => {
    render(<MarkdownContent>{"> quoted thought"}</MarkdownContent>);
    const bq = screen.getByText("quoted thought").closest("blockquote");
    expect(bq).not.toBeNull();
    expect(bq?.className).toContain("italic");
    expect(bq?.className).toContain("text-muted-foreground");
  });
});
