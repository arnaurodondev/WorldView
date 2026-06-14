/**
 * __tests__/morning-brief-card.test.tsx — PLAN-0049 T-D-4-05 regression coverage.
 *
 * WHY THIS EXISTS: MorningBriefCard is the single most prominent surface on the
 * dashboard. PLAN-0049 Wave A added a structured BriefResponse contract
 * (sections + headline + summary + citations) but kept the legacy narrative
 * field as a fallback. This test pins three contracts that must NEVER regress:
 *
 *   1. Structured render path — when ``brief.sections`` is populated AND the
 *      user has expanded the card, each section's title + bullets render.
 *   2. Narrative fallback — when ``sections`` is empty or absent, the expanded
 *      card falls back to a markdown render of ``brief.narrative`` so older
 *      cached briefs (pre-section parsing) still render.
 *   3. Empty/missing-narrative state — when both narrative and summary are
 *      empty strings, the card shows the AI-brief-unavailable empty state
 *      (the "AI brief unavailable" copy guarded by the ``!brief`` check).
 *
 * WHY MOCK THE GATEWAY: The card calls ``createGateway(token).getMorningBrief()``
 * inside a TanStack Query. Mocking ``@/lib/gateway`` lets us drive the three
 * scenarios deterministically without running the S8 backend.
 *
 * WHY MOCK next/navigation: MorningBriefCard renders Next.js ``<Link>`` for
 * entity-mention deep-links and Top Stories chips. ``next/navigation`` is not
 * mounted in jsdom — without the mock the tree throws.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { BriefingResponse, BriefBullet } from "@/types/api";

// ── Test adapter ──────────────────────────────────────────────────────────────
// WHY _toBriefBullet: PLAN-0062-W4 changed BriefSection.bullets from string[]
// to BriefBullet[]. Existing fixture strings are wrapped here rather than
// deleting/rewriting every assertion — R19 forbids weakening existing tests.
// The placeholder citation keeps the shape valid without needing real article IDs.
function _toBriefBullet(text: string): BriefBullet {
  return {
    text,
    citations: [
      {
        document_id: "test-doc-placeholder",
        source_type: "article",
        title: "Placeholder citation for test fixture",
        url: null,
      },
    ],
  };
}

// ── Next.js navigation mock ───────────────────────────────────────────────────
// MorningBriefCard imports ``next/link`` (which internally reads router config)
// and ``next/navigation`` is the supporting module — stub all three hooks even
// if MorningBriefCard itself only needs Link rendering.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY a top-level mutable var: each test reassigns the resolved value before
// rendering so TanStack Query receives the per-scenario payload.
const mockGetMorningBrief = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getMorningBrief: mockGetMorningBrief,
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Component import (after vi.mock) ─────────────────────────────────────────
import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";

// ── Wrapper helpers ───────────────────────────────────────────────────────────
function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

// ── Fixture builders ──────────────────────────────────────────────────────────
// WHY typed via BriefingResponse: enforces the no-`any` contract from CLAUDE.md.
// Any field rename in the API surface trips the test before it ships.
// WHY long narrative (>200 chars): MorningBriefCard gates the "Read more"
// expand button on ``narrativeWithLinks.length > 200``. Without exceeding that
// threshold the user can't reach the expanded view in tests.
const LONG_NARRATIVE_PADDING =
  " ".repeat(0) +
  "Markets opened mixed today as tech outperformed and energy lagged. " +
  "Banks led the rally on rising bond yields. Volatility ticked up modestly " +
  "but breadth remained healthy across sectors. Fed minutes due Wednesday.";

function structuredBrief(): BriefingResponse {
  return {
    narrative:
      "## Drivers\n\n- Tech rallied 1.2%\n- 10Y yield -3bp\n\n## Implications\n\n- Watch Fed minutes Wed\n\n" +
      LONG_NARRATIVE_PADDING,
    summary: "Markets opened mixed; tech outperformed.",
    lead: "Markets opened mixed; tech outperformed.",
    risk_summary: null,
    entity_mentions: [],
    citations: [
      {
        source_type: "article",
        source_id: "art-1",
        title: "Apple beats earnings",
        url: "https://news.example.com/aapl-q1",
      },
      {
        source_type: "article",
        source_id: "art-2",
        title: "CPI cools",
        url: "https://news.example.com/cpi",
      },
    ],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    sections: [
      // WHY _toBriefBullet: BriefSection.bullets is now BriefBullet[] (PLAN-0062-W4).
      // We adapt the string fixture so R19 (never delete/weaken tests) is honoured.
      { title: "Drivers", bullets: ["Tech rallied 1.2%", "10Y yield -3bp"].map(_toBriefBullet) },
      { title: "Implications", bullets: ["Watch Fed minutes Wed"].map(_toBriefBullet) },
    ],
  };
}

function narrativeOnlyBrief(): BriefingResponse {
  return {
    narrative:
      "**Market Update**: A long-form narrative with no parsed sections. " +
      LONG_NARRATIVE_PADDING,
    summary: "Short summary line.",
    risk_summary: null,
    entity_mentions: [],
    citations: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    // WHY sections: []: simulates a brief where the backend's
    // _parse_sections_from_markdown() couldn't structure the content. The
    // expanded view must fall back to MarkdownContent on narrative.
    sections: [],
  };
}

// User report 2026-06-14: the live v4.x morning brief leaks cryptic uppercase
// citation markers — [N2]/[N10]/[N12] — into both the collapsed summary and the
// expanded narrative. This fixture reproduces the exact leak (the [N2] from the
// real "Manus deal" report) plus a content-bearing bracket that MUST survive
// the strip (a date range), so the regression test verifies BOTH directions:
// markers gone, real brackets kept.
function leakedMarkersBrief(): BriefingResponse {
  return {
    narrative:
      "**Market Snapshot** [N1]\n\n- META reportedly unwinding a $2B Manus deal " +
      "after Beijing's demand [N2] — regulatory headline risk [N10]. Window closes " +
      "[2026-06-30]. " +
      LONG_NARRATIVE_PADDING,
    // Collapsed view reads summary_paragraph first (3-tier fallback).
    summary_paragraph:
      "META reportedly unwinding a $2B Manus deal after Beijing's demand [N2]; " +
      "NVDA tailwind from CoreWeave [N12]. Reassess by [2026-06-30].",
    summary: "META unwinds $2B Manus deal [N2].",
    risk_summary: null,
    entity_mentions: [],
    citations: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    sections: [],
  };
}

function emptyBrief(): BriefingResponse {
  return {
    // WHY both empty: triggers the "AI brief unavailable" guard. A brief object
    // returned by S8 with neither summary nor narrative shouldn't render
    // anything but the empty-state copy.
    narrative: "",
    summary: "",
    risk_summary: null,
    entity_mentions: [],
    citations: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    sections: [],
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("MorningBriefCard — PLAN-0049 T-D-4-01 contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders structured sections + citation chips when brief.sections is populated", async () => {
    // WHY this is the primary path: the v2.2 prompt + section parser succeeds
    // for every well-formed brief. A regression in the structured render
    // would silently fall back to plain markdown — visually similar but
    // missing the polished section cards. We pin both the section titles
    // and bullet text so any layout drift trips the test.
    mockGetMorningBrief.mockResolvedValue(structuredBrief());

    const user = userEvent.setup();
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    // Wait for the brief to land (collapsed view is the default).
    await waitFor(() => {
      // The summary line is present in collapsed view.
      expect(screen.getByText(/Markets opened mixed/)).toBeInTheDocument();
    });

    // Click "Read more" to expand — the structured-render path is gated on
    // ``expanded === true``.
    const expandBtn = await screen.findByRole("button", { name: /Expand morning brief/i });
    await user.click(expandBtn);

    // Both section titles must appear after expansion.
    await waitFor(() => {
      expect(screen.getByText("Drivers")).toBeInTheDocument();
      expect(screen.getByText("Implications")).toBeInTheDocument();
    });
    // Bullet text from the first section.
    expect(screen.getByText("Tech rallied 1.2%")).toBeInTheDocument();
    // Citation chips (Top Stories) — both article-type citations should appear.
    expect(screen.getByText("Apple beats earnings")).toBeInTheDocument();
    expect(screen.getByText("CPI cools")).toBeInTheDocument();
  });

  it("falls back to narrative markdown when sections array is empty", async () => {
    // WHY this is the fallback path: legacy cached briefs + briefs whose
    // markdown can't be parsed into sections must still render. A regression
    // here would leave older briefs blank.
    mockGetMorningBrief.mockResolvedValue(narrativeOnlyBrief());

    const user = userEvent.setup();
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // The summary line is rendered in the collapsed view.
      expect(screen.getByText(/Short summary line/)).toBeInTheDocument();
    });

    const expandBtn = await screen.findByRole("button", { name: /Expand morning brief/i });
    await user.click(expandBtn);

    // Expanded view falls back to ReactMarkdown over narrative — at least the
    // bold text inside "**Market Update**" should land in the DOM. Multiple
    // matches exist (the collapsed summary path also rendered earlier text);
    // we just require the narrative text to appear AT LEAST once.
    await waitFor(() => {
      const matches = screen.getAllByText(/Market Update/);
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("strips cryptic [N#] citation markers from collapsed + expanded text but keeps real brackets", async () => {
    // Regression for the 2026-06-14 user report: literal "[N2]"/"[N10]"/"[N12]"
    // markers were leaking into the rendered morning brief because the card's
    // ReactMarkdown render path (collapsed + narrative-fallback) never stripped
    // them — only StructuredBrief did, and the live brief has empty sections[]
    // so it never runs StructuredBrief.
    mockGetMorningBrief.mockResolvedValue(leakedMarkersBrief());

    const user = userEvent.setup();
    const { container } = render(<MorningBriefCard />, { wrapper: makeWrapper() });

    // Collapsed view (summary_paragraph) must be marker-free.
    await waitFor(() => {
      expect(screen.getByText(/Manus deal/)).toBeInTheDocument();
    });
    // No cryptic [N#] token anywhere in the collapsed card.
    expect(container.textContent).not.toMatch(/\[N\d+\]/);
    // Content-bearing bracket (a date) must be preserved — proves the strip is
    // surgical and doesn't eat legitimate bracketed values.
    expect(container.textContent).toMatch(/\[2026-06-30\]/);

    // Expand → narrative-fallback markdown path must ALSO be marker-free.
    const expandBtn = await screen.findByRole("button", { name: /Expand morning brief/i });
    await user.click(expandBtn);
    await waitFor(() => {
      expect(screen.getAllByText(/Manus deal/).length).toBeGreaterThanOrEqual(1);
    });
    expect(container.textContent).not.toMatch(/\[N\d+\]/);
    expect(container.textContent).toMatch(/\[2026-06-30\]/);
  });

  it("renders the unavailable empty state when narrative + summary are empty", async () => {
    // WHY this is the empty-state path: S8 may return ``{}`` while the brief
    // is still being generated. A regression here would render an empty card
    // with no chrome — confusing to traders ("did my dashboard break?").
    mockGetMorningBrief.mockResolvedValue(emptyBrief());

    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    // Empty-state copy from MorningBriefCard line 173-174.
    await waitFor(() => {
      expect(screen.getByText(/AI brief unavailable/i)).toBeInTheDocument();
    });
  });
});

// ── Round 1 foundation (2026-06-10): named empty state ───────────────────────
// The bare "system initializing" one-liner became a structured empty state:
// icon + headline + last-attempt timestamp + Regenerate action. These tests
// pin the NEW contract; the headline copy test above is untouched (R19).

describe("MorningBriefCard — Round 1 named empty state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the last-attempt timestamp and a Regenerate action", async () => {
    mockGetMorningBrief.mockResolvedValue(emptyBrief());

    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/AI brief unavailable/i)).toBeInTheDocument();
    });
    // dataUpdatedAt is set by the successful (but empty) fetch — the empty
    // state must surface WHEN we last heard from S8.
    expect(screen.getByText(/Last attempt \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC/)).toBeInTheDocument();
    // Regenerate is the named CTA (wired to a refetch of the morning-brief
    // endpoint — S8 background-regenerates when the cached brief is stale).
    expect(
      screen.getByRole("button", { name: /Regenerate morning brief/i }),
    ).toBeInTheDocument();
    // role=status so assistive tech announces the empty state.
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("clicking Regenerate refetches the morning brief", async () => {
    mockGetMorningBrief.mockResolvedValue(emptyBrief());

    const user = userEvent.setup();
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/AI brief unavailable/i)).toBeInTheDocument();
    });
    const callsBefore = mockGetMorningBrief.mock.calls.length;

    await user.click(
      screen.getByRole("button", { name: /Regenerate morning brief/i }),
    );

    // The button triggers refetch() — the gateway method must be hit again.
    await waitFor(() => {
      expect(mockGetMorningBrief.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });
});
