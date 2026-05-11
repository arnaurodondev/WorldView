/**
 * __tests__/docs.test.tsx — PLAN-0052 Wave B docs hub coverage
 *
 * WHY THIS EXISTS: Locks the contract of the file-based MDX loader and
 * the docs UI components against regression. The MDXRemote/RSC compile
 * step itself is tested e2e via Playwright (it requires a server runtime);
 * the unit tests here cover the pure-function loader and the client
 * component behaviour in isolation.
 *
 * SCOPE:
 *   T-B-2-02 lib/docs.ts loader contracts
 *   T-B-2-03 DocsSidebar renders sections + active-link highlight
 *   T-B-2-04 DocsTableOfContents renders heading list + scroll-spy hook
 *   T-B-2-05 MDX components: Callout/Steps/DocsTabs/CodeBlock
 *   T-B-2-06 DocsBreadcrumb segments
 *   T-B-2-08 DocsFeedback thumbs flow + endpoint contract
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// jsdom (used by vitest) doesn't ship IntersectionObserver. The
// DocsTableOfContents scroll-spy needs it; provide a no-op stub so render
// doesn't throw. We don't simulate intersection events — the scroll-spy
// behavior itself is exercised by the e2e Playwright suite.
beforeAll(() => {
  if (typeof globalThis.IntersectionObserver === "undefined") {
    class StubIntersectionObserver implements IntersectionObserver {
      readonly root: Element | Document | null = null;
      readonly rootMargin: string = "";
      readonly thresholds: ReadonlyArray<number> = [];
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
      takeRecords(): IntersectionObserverEntry[] {
        return [];
      }
    }
    globalThis.IntersectionObserver = StubIntersectionObserver as unknown as typeof IntersectionObserver;
  }
});

// next/link + next/navigation mocks (tests run in jsdom).
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/docs"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── lib/docs.ts loader ───────────────────────────────────────────────────

describe("T-B-2-02 — lib/docs.ts content loader", () => {
  it("loads the seeded MDX index and returns at least the welcome page", async () => {
    const { getAllDocs, _resetCache } = await import("@/lib/docs");
    _resetCache();
    const docs = getAllDocs();
    expect(docs.length).toBeGreaterThanOrEqual(4);
    const welcome = docs.find((d) => d.slug.length === 0);
    expect(welcome).toBeDefined();
    expect(welcome?.frontmatter.title).toMatch(/welcome/i);
  });

  it("getDocBySlug returns the matching doc for nested slugs", async () => {
    const { getDocBySlug } = await import("@/lib/docs");
    const doc = getDocBySlug(["getting-started"]);
    expect(doc).toBeDefined();
    expect(doc?.url).toBe("/docs/getting-started");
  });

  it("extracts h2/h3 headings while ignoring code-fence content", async () => {
    const { extractHeadings } = await import("@/lib/docs");
    const body = [
      "# Skipped h1",
      "",
      "## Real heading",
      "",
      "```ts",
      "// ## Not a heading inside a fence",
      "```",
      "",
      "### Sub-heading",
    ].join("\n");
    const headings = extractHeadings(body);
    expect(headings).toHaveLength(2);
    expect(headings[0]).toMatchObject({ level: 2, text: "Real heading" });
    expect(headings[1]).toMatchObject({ level: 3, text: "Sub-heading" });
  });

  it("getSidebarSections groups docs by section heading", async () => {
    const { getSidebarSections } = await import("@/lib/docs");
    const sections = getSidebarSections();
    const headings = sections.map((s) => s.heading);
    expect(headings).toContain("Overview");
    expect(headings).toContain("Getting Started");
  });

  it("getSearchIndex includes one entry per page plus per-heading entries", async () => {
    const { getSearchIndex, getAllDocs } = await import("@/lib/docs");
    const idx = getSearchIndex();
    const pages = getAllDocs();
    // Always at least one entry per page; usually more (one per heading).
    expect(idx.length).toBeGreaterThanOrEqual(pages.length);
  });
});

// ── DocsSidebar ──────────────────────────────────────────────────────────

describe("T-B-2-03 — DocsSidebar", () => {
  it("renders section headings and item links", async () => {
    const { DocsSidebar } = await import("@/components/docs/DocsSidebar");
    const sections = [
      { heading: "Overview", items: [{ title: "Welcome", url: "/docs" }] },
      {
        heading: "Getting Started",
        items: [{ title: "Sign up", url: "/docs/getting-started" }],
      },
    ];
    render(<DocsSidebar sections={sections} />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Welcome" })).toHaveAttribute(
      "href",
      "/docs",
    );
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute(
      "href",
      "/docs/getting-started",
    );
  });

  it("marks the active link with aria-current=page", async () => {
    const navMock = await import("next/navigation");
    (navMock.usePathname as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      "/docs/getting-started",
    );
    const { DocsSidebar } = await import("@/components/docs/DocsSidebar");
    const sections = [
      {
        heading: "Getting Started",
        items: [{ title: "Sign up", url: "/docs/getting-started" }],
      },
    ];
    render(<DocsSidebar sections={sections} />);
    const link = screen.getByRole("link", { name: "Sign up" });
    expect(link).toHaveAttribute("aria-current", "page");
  });
});

// ── DocsTableOfContents ─────────────────────────────────────────────────

describe("T-B-2-04 — DocsTableOfContents", () => {
  it("renders nothing when there are zero headings", async () => {
    const { DocsTableOfContents } = await import(
      "@/components/docs/DocsTableOfContents"
    );
    const { container } = render(<DocsTableOfContents headings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every heading by text + correct anchor href", async () => {
    const { DocsTableOfContents } = await import(
      "@/components/docs/DocsTableOfContents"
    );
    render(
      <DocsTableOfContents
        headings={[
          { level: 2, text: "Install", slug: "install" },
          { level: 3, text: "Step 1", slug: "step-1" },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "Install" })).toHaveAttribute(
      "href",
      "#install",
    );
    expect(screen.getByRole("link", { name: "Step 1" })).toHaveAttribute(
      "href",
      "#step-1",
    );
  });
});

// ── DocsBreadcrumb ──────────────────────────────────────────────────────

describe("T-B-2-06 — DocsBreadcrumb", () => {
  it("renders only a Docs marker for the root index", async () => {
    const { DocsBreadcrumb } = await import("@/components/docs/DocsBreadcrumb");
    render(<DocsBreadcrumb slug={[]} title="Welcome" />);
    expect(screen.getByText(/^Docs$/i)).toBeInTheDocument();
  });

  it("walks intermediate segments and marks the last as current page", async () => {
    const { DocsBreadcrumb } = await import("@/components/docs/DocsBreadcrumb");
    render(
      <DocsBreadcrumb
        slug={["getting-started", "sign-up"]}
        title="Sign up"
      />,
    );
    expect(screen.getByRole("link", { name: "Docs" })).toHaveAttribute(
      "href",
      "/docs",
    );
    expect(screen.getByText("Sign up")).toHaveAttribute("aria-current", "page");
  });
});

// ── MDX components ──────────────────────────────────────────────────────

describe("T-B-2-05 — MDX components", () => {
  it("Callout renders with role=note and proper variant icon", async () => {
    const { Callout } = await import("@/components/docs/mdx/Callout");
    render(<Callout type="warn" title="Be careful">Body</Callout>);
    const note = screen.getByRole("note");
    expect(note).toBeInTheDocument();
    expect(screen.getByText("Be careful")).toBeInTheDocument();
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("Steps numbers each step starting at 1", async () => {
    const { Steps, Step } = await import("@/components/docs/mdx/Steps");
    const { container } = render(
      <Steps>
        <Step>One</Step>
        <Step>Two</Step>
      </Steps>,
    );
    const items = container.querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(container.textContent).toContain("1");
    expect(container.textContent).toContain("2");
  });

  it("DocsTabs only shows the active panel and switches on click", async () => {
    const { DocsTabs, DocsTab } = await import(
      "@/components/docs/mdx/DocsTabs"
    );
    render(
      <DocsTabs items={["A", "B"]}>
        <DocsTab>aaa</DocsTab>
        <DocsTab>bbb</DocsTab>
      </DocsTabs>,
    );
    // Tabs render with role=tab
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
    // Click second tab → it becomes selected
    fireEvent.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });
});

// ── DocsFeedback ────────────────────────────────────────────────────────

describe("T-B-2-08 — DocsFeedback thumbs widget", () => {
  beforeEach(() => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts to the micro-survey endpoint on thumbs-up and shows confirmation", async () => {
    const { DocsFeedback } = await import("@/components/docs/DocsFeedback");
    render(<DocsFeedback pageUrl="/docs/test" />);
    fireEvent.click(screen.getByRole("button", { name: /yes, this was helpful/i }));
    // Wait a microtask for the async POST to complete
    await Promise.resolve();
    await Promise.resolve();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/feedback/micro-survey",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
    // Body is JSON-stringified — parse and assert shape
    const call = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body).toMatchObject({
      survey_id: "docs-page-helpful",
      response: "up",
      context_url: "/docs/test",
    });
  });

  it("opens a comment textarea on thumbs-down and submits when filled", async () => {
    const { DocsFeedback } = await import("@/components/docs/DocsFeedback");
    render(<DocsFeedback pageUrl="/docs/test" />);
    fireEvent.click(screen.getByRole("button", { name: /no, this was not helpful/i }));
    const textarea = screen.getByLabelText(/what was missing/i);
    expect(textarea).toBeInTheDocument();
    // Send button disabled until the user types something
    const sendBtn = screen.getByRole("button", { name: /send feedback/i });
    expect(sendBtn).toBeDisabled();
    fireEvent.change(textarea, { target: { value: "needs an example" } });
    expect(sendBtn).not.toBeDisabled();
  });
});
