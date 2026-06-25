/**
 * brief-catalyst-preview.test.tsx — coverage for the cited, structured Morning
 * Briefing collapsed-view preview (roadmap 2026-06-19 Top-8 #8 / C3).
 *
 * WHY THIS FILE EXISTS:
 * Top-8 item #8 promotes the morning brief from a prose blob to a structured,
 * cited catalyst preview in the COLLAPSED card. These tests pin the new
 * contract so it can't silently regress to a text blob:
 *
 *   1. BriefCatalystPreview (the new sub-component) renders section headers +
 *      cited catalyst bullets, links article citations, surfaces an
 *      affected-ticker pill from entity_mentions, strips [N#] markers, and
 *      returns null when there are no renderable bullets.
 *   2. MorningBriefCard, in its COLLAPSED view, shows the structured preview
 *      (section title + bullet + source chip) when brief.sections is populated
 *      — without requiring the user to click "Read more".
 *   3. The card falls back to the prose summary when sections are empty (the
 *      live v4.x reality) and renders the freshness dot in every loaded state.
 *
 * WHY MOCK next/navigation + gateway + auth: same rationale as
 * __tests__/morning-brief-card.test.tsx — the card fetches via TanStack Query
 * and renders next/link, neither of which is mounted in jsdom by default.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type {
  BriefingResponse,
  BriefSection,
  BriefingEntityMention,
} from "@/types/api";

// ── Next.js navigation mock (next/link reads router config in jsdom) ──────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock — card reads accessToken ───────────────────────────────────────
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

// ── Gateway mock — drives the morning-brief payload per test ──────────────────
const mockGetMorningBrief = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getMorningBrief: mockGetMorningBrief,
    refreshToken: vi.fn(),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Components under test (imported after vi.mock) ───────────────────────────
import { BriefCatalystPreview } from "@/components/dashboard/BriefCatalystPreview";
import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const MENTIONS: BriefingEntityMention[] = [
  { entity_id: "e-aapl", name: "Apple Inc.", ticker: "AAPL" },
  { entity_id: "e-nvda", name: "NVIDIA", ticker: "NVDA" },
];

const SECTIONS: BriefSection[] = [
  {
    title: "Market Snapshot",
    bullets: [
      {
        // [N1] marker must be stripped from the rendered text.
        text: "Apple Inc. rallied on strong iPhone demand [N1].",
        citations: [
          {
            document_id: "doc-1",
            source_type: "article",
            title: "Apple beats expectations",
            url: "https://www.bloomberg.com/aapl",
          },
        ],
      },
    ],
  },
  {
    title: "Portfolio Impact",
    bullets: [
      {
        text: "NVIDIA guidance lifted the AI complex.",
        citations: [
          {
            document_id: "doc-2",
            source_type: "article",
            title: "NVIDIA guidance",
            url: "https://www.reuters.com/nvda",
          },
        ],
      },
    ],
  },
];

function structuredBrief(): BriefingResponse {
  return {
    narrative: "Long narrative body ".repeat(20),
    summary_paragraph: "Markets mixed; tech leads.",
    summary: "Markets mixed; tech leads.",
    lead: "Markets mixed; tech leads.",
    risk_summary: null,
    entity_mentions: MENTIONS,
    citations: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    sections: SECTIONS,
  };
}

function sectionlessBrief(): BriefingResponse {
  return {
    narrative: "A plain narrative with no parsed sections. ".repeat(10),
    summary_paragraph: "Markets opened mixed; tech outperformed.",
    summary: "Markets opened mixed; tech outperformed.",
    risk_summary: null,
    entity_mentions: [],
    citations: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    sections: [],
  };
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestWrapper";
  return Wrapper;
}

// ── BriefCatalystPreview unit tests ──────────────────────────────────────────

describe("BriefCatalystPreview", () => {
  it("renders section headers and cited catalyst bullets", () => {
    render(<BriefCatalystPreview sections={SECTIONS} mentions={MENTIONS} />);

    expect(screen.getByTestId("brief-catalyst-preview")).toBeInTheDocument();
    expect(screen.getByText("Market Snapshot")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Impact")).toBeInTheDocument();
    // The bullet text renders WITHOUT the cryptic [N1] marker.
    expect(screen.getByText(/Apple Inc\. rallied on strong iPhone demand/)).toBeInTheDocument();
    expect(screen.queryByText(/\[N1\]/)).not.toBeInTheDocument();
  });

  it("links article citations to their source URL (the cited part)", () => {
    render(<BriefCatalystPreview sections={SECTIONS} mentions={MENTIONS} />);

    // Source chip is a link to the external article, opening in a new tab.
    const chip = screen.getByText("bloomberg.com").closest("a");
    expect(chip).toHaveAttribute("href", "https://www.bloomberg.com/aapl");
    expect(chip).toHaveAttribute("target", "_blank");
  });

  it("surfaces an affected-ticker pill deep-linking to the instrument page", () => {
    render(<BriefCatalystPreview sections={SECTIONS} mentions={MENTIONS} />);

    // "Apple Inc." in the first bullet → AAPL pill → /instruments/AAPL.
    const pill = screen.getByText("AAPL").closest("a");
    expect(pill).toHaveAttribute("href", "/instruments/AAPL");
  });

  it("returns null when no section has bullets", () => {
    const { container } = render(
      <BriefCatalystPreview
        sections={[{ title: "Empty", bullets: [] }]}
        mentions={[]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});

// ── MorningBriefCard integration tests ───────────────────────────────────────

describe("MorningBriefCard — cited structured collapsed view (#8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the structured catalyst preview in the COLLAPSED view (no expand)", async () => {
    mockGetMorningBrief.mockResolvedValue(structuredBrief());
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    // The structured preview renders without clicking "Read more".
    await waitFor(() => {
      expect(screen.getByTestId("brief-catalyst-preview")).toBeInTheDocument();
    });
    // Section header + a cited bullet + a source chip are all visible collapsed.
    expect(screen.getByText("Market Snapshot")).toBeInTheDocument();
    expect(screen.getByText(/Apple Inc\. rallied/)).toBeInTheDocument();
    expect(screen.getByText("bloomberg.com")).toBeInTheDocument();
  });

  it("renders the freshness dot in the loaded header", async () => {
    mockGetMorningBrief.mockResolvedValue(structuredBrief());
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      const dot = screen.getByTestId("brief-freshness-dot");
      expect(dot).toBeInTheDocument();
      // A brief generated "now" must read as Fresh (positive/green tier).
      expect(dot).toHaveClass("text-positive");
    });
  });

  it("falls back to the prose summary when sections are empty (v4.x reality)", async () => {
    mockGetMorningBrief.mockResolvedValue(sectionlessBrief());
    render(<MorningBriefCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/Markets opened mixed/)).toBeInTheDocument();
    });
    // No structured preview — the prose fallback is used instead.
    expect(screen.queryByTestId("brief-catalyst-preview")).not.toBeInTheDocument();
  });
});
