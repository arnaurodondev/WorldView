/**
 * dossier/__tests__/EntityDossier.test.tsx — PLAN-0099 Wave 2.
 *
 * Pins the left-rail dossier contracts. PORTED ASSERTIONS from the retired
 * ContextPanel.test.tsx (the dossier absorbed the entity-overview mode):
 *   - "Updated <date>" renders from entity.enriched_at
 *   - missing enriched_at renders "Updated —" (named, not hidden)
 *   - missing entity entirely renders the NAMED empty state (icon + headline,
 *     role=status, registry copy "has not been enriched yet")
 *
 * NEW WAVE-2 CONTRACTS:
 *   - aliases render as chips (capped)
 *   - health badge renders from the Wave-1 enriched detail payload
 *   - top-relation rows fire onSelectRelation(relation_id) — the list-first
 *     path to the edge inspector
 *   - "Discuss" fires onDiscuss
 *   - detail fetch failure renders the NAMED per-section error with Retry
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { type ReactNode } from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// RelatedEntitiesPanel child navigates company chips via useRouter — stub it.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    logout: vi.fn(),
  })),
}));

const mockGetEntityDetail = vi.hoisted(() => vi.fn());
const mockGetInstrumentBrief = vi.hoisted(() => vi.fn());
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getEntityDetail: mockGetEntityDetail,
    getInstrumentBrief: mockGetInstrumentBrief,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// Health-fallback hook — not under test here (detail payload carries health).
vi.mock("@/lib/api/intelligence", () => ({
  useEntityIntelligence: vi.fn(() => ({ data: null, isLoading: false })),
}));

import { EntityDossier } from "@/components/instrument/intelligence/dossier/EntityDossier";

const ENTITY = {
  entity_id: "ent-001",
  canonical_name: "Apple Inc.",
  entity_type: "financial_instrument",
  ticker: "AAPL",
  exchange: "US",
  description: "Designs and sells consumer electronics.",
  enriched_at: "2026-06-05T03:00:00Z",
  metadata: {},
  health_score: 0.82,
  aliases: [
    { alias_text: "Apple Inc.", alias_type: "EXACT" },
    { alias_text: "AAPL", alias_type: "TICKER" },
  ],
  relation_count: 4,
  top_relations: [
    {
      relation_id: "rel-1",
      canonical_type: "is_in_sector",
      direction: "outbound",
      other_entity_id: "ent-sector",
      other_entity_name: "Information Technology",
      other_entity_type: "sector",
      confidence: 0.95,
      evidence_count: 11,
      relation_summary: "EODHD classifies the entity in the IT sector.",
    },
  ],
};

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderDossier(overrides: Partial<React.ComponentProps<typeof EntityDossier>> = {}) {
  return render(
    <Wrapper>
      <EntityDossier
        entityId="ent-001"
        onSelectRelation={vi.fn()}
        onSelectNode={vi.fn()}
        onDiscuss={vi.fn()}
        {...overrides}
      />
    </Wrapper>,
  );
}

beforeEach(() => {
  mockGetEntityDetail.mockReset();
  mockGetInstrumentBrief.mockReset();
  // Brief 404s by default — the brief block is tested separately.
  mockGetInstrumentBrief.mockResolvedValue(null);
});

afterEach(() => cleanup());

describe("EntityDossier last-updated timestamp (ported from ContextPanel)", () => {
  it("renders 'Updated <date>' from entity.enriched_at", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier();
    await waitFor(() => {
      // WHY getByRole heading: "Apple Inc." also appears as an alias chip —
      // the heading query pins the identity header specifically.
      expect(screen.getByRole("heading", { name: "Apple Inc." })).toBeInTheDocument();
    });
    expect(screen.getByText(/Updated/i)).toBeInTheDocument();
    // formatDate renders UTC "Jun 5, 2026".
    expect(screen.getByText("Jun 5, 2026")).toBeInTheDocument();
  });

  it("renders 'Updated —' when the entity was never enriched", async () => {
    mockGetEntityDetail.mockResolvedValue({ ...ENTITY, enriched_at: null });
    renderDossier();
    await waitFor(() => {
      expect(screen.getByText(/Updated/i)).toBeInTheDocument();
    });
    // The timestamp slot stays mounted with an explicit dash (named state).
    const updated = screen.getByText(/Updated/i);
    expect(updated.textContent).toContain("—");
  });
});

describe("EntityDossier named no-entity state (ported from ContextPanel)", () => {
  it("renders the icon+headline empty state when the entity detail is null", async () => {
    // getEntityDetail returns null for 404 (entity not enriched yet).
    mockGetEntityDetail.mockResolvedValue(null);
    renderDossier();
    await waitFor(() => {
      expect(screen.getByText("No entity context")).toBeInTheDocument();
    });
    // Shared primitive announces via role="status" with an inline <svg> icon.
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.querySelector("svg")).not.toBeNull();
    expect(screen.getByText(/has not been enriched yet/i)).toBeInTheDocument();
  });
});

describe("EntityDossier Wave-2 enrichment surface", () => {
  it("renders the health badge from the enriched detail payload", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier();
    await waitFor(() => {
      // 0.82 → "82%" (Math.round to integer percent).
      expect(screen.getByText("82%")).toBeInTheDocument();
    });
  });

  it("renders alias chips", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier();
    await waitFor(() => {
      expect(screen.getByTestId("dossier-aliases")).toBeInTheDocument();
    });
    const aliases = screen.getByTestId("dossier-aliases");
    expect(aliases.textContent).toContain("Apple Inc.");
    expect(aliases.textContent).toContain("AAPL");
  });

  it("fires onSelectRelation(relation_id) when a top-relation row is clicked", async () => {
    const onSelectRelation = vi.fn();
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier({ onSelectRelation });
    await waitFor(() => {
      expect(screen.getByTestId("dossier-relation-rel-1")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("dossier-relation-rel-1"));
    expect(onSelectRelation).toHaveBeenCalledWith("rel-1");
  });

  it("shows the relation_count badge next to the Top Relations header", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier();
    await waitFor(() => {
      expect(screen.getByText("4")).toBeInTheDocument();
    });
  });

  it("fires onDiscuss when the Discuss button is clicked", async () => {
    const onDiscuss = vi.fn();
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    renderDossier({ onDiscuss });
    await waitFor(() => {
      expect(screen.getByTestId("dossier-discuss")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("dossier-discuss"));
    expect(onDiscuss).toHaveBeenCalledTimes(1);
  });
});

describe("EntityDossier AI brief block", () => {
  it("renders the structured brief when the brief query returns content", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    mockGetInstrumentBrief.mockResolvedValue({
      narrative: "Apple remains dominant.",
      lead: "Apple remains dominant.",
      // BriefSection shape: { title, bullets: BriefBullet[] } (types/api.ts).
      sections: [{ title: "Outlook", bullets: [] }],
      confidence: 0.8,
    });
    renderDossier();
    await waitFor(() => {
      expect(screen.getByText(/Apple remains dominant/)).toBeInTheDocument();
    });
  });

  it("renders the named brief-empty line when no brief exists", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    mockGetInstrumentBrief.mockResolvedValue(null);
    renderDossier();
    await waitFor(() => {
      expect(screen.getByTestId("dossier-brief-empty")).toBeInTheDocument();
    });
  });
});

describe("EntityDossier error state", () => {
  it("renders the NAMED per-section error with Retry when the detail fetch fails", async () => {
    mockGetEntityDetail.mockRejectedValue(new Error("boom"));
    renderDossier();
    // WHY 4s timeout: the component's useQuery sets retry:1 (overriding the
    // test client's retry:false default), so the error state only lands after
    // one ~1s-backoff retry round-trip.
    await waitFor(
      () => {
        expect(screen.getByTestId("dossier-fetch-error")).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
    expect(screen.getByText(/Couldn't load the entity dossier/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
