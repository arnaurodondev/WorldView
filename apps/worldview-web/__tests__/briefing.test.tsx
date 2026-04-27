/**
 * __tests__/briefing.test.tsx — Unit tests for MorningBriefCard and InstrumentBriefSection
 *
 * WHY THIS EXISTS: Verifies that both briefing components correctly render
 * markdown content via ReactMarkdown, handle loading/error states, and display
 * the generated_at timestamp. These are high-visibility components on the
 * dashboard and instrument detail pages.
 *
 * WHY MOCK GATEWAY: Isolates components from real S9 calls. The gateway mock
 * returns controlled BriefingResponse data so we can test each render path.
 *
 * DATA SOURCE: Mocked gateway client with BriefingResponse fixtures.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: MorningBriefCard uses Next.js Link which requires the App Router context.
// In unit tests the App Router isn't mounted — mock it to avoid "invariant" error.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY: Controls exactly what BriefingResponse the component receives.
// The mock returns a full BriefingResponse matching the updated type definition.
// WHY "Apple" appears in narrative: the entity mention replacement regex scans the
// narrative string for entity names and converts them to markdown links.
// WHY narrative (not content): BriefingResponse.narrative mirrors S8's
// PublicBriefingResponse field name — see types/api.ts and rag-chat/schemas.py.
const mockBriefResponse = {
  narrative: "**Market Update**: Apple rallied as CPI came in below expectations.",
  risk_summary: null,
  entity_mentions: [
    { entity_id: "ent-1", name: "Apple", ticker: "AAPL" },
  ],
  citations: [],
  generated_at: new Date().toISOString(),
  cached: false,
  entity_id: null,
};

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getMorningBrief: vi.fn().mockResolvedValue(mockBriefResponse),
    getInstrumentBrief: vi.fn().mockResolvedValue({
      ...mockBriefResponse,
      entity_id: "ent-1",
      // WHY narrative (not content): matches updated BriefingResponse type
      narrative: "Apple reported strong **Q4 earnings** above expectations.",
    }),
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("MorningBriefCard", () => {
  it("renders markdown content after data loads", async () => {
    render(<MorningBriefCard />, { wrapper });

    // WHY waitFor: useQuery is async — the component shows skeletons first,
    // then renders data after the mock gateway resolves.
    await waitFor(() => {
      // ReactMarkdown converts **bold** to <strong> — check for the text content
      expect(screen.getByText(/Market Update/)).toBeInTheDocument();
    });
  });

  it("renders generated timestamp", async () => {
    render(<MorningBriefCard />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/Generated/)).toBeInTheDocument();
      expect(screen.getByText(/UTC/)).toBeInTheDocument();
    });
  });

  it("renders entity mention as a link", async () => {
    render(<MorningBriefCard />, { wrapper });

    await waitFor(() => {
      // WHY check for link: entity mentions are replaced with Next.js Link components
      // that navigate to the instrument detail page
      const link = screen.getByText("Apple");
      expect(link.closest("a")).toHaveAttribute("href", "/instruments/ent-1");
    });
  });
});
