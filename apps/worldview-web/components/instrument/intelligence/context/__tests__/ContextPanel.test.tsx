/**
 * context/__tests__/ContextPanel.test.tsx — F-009 minimal aria contract
 *
 * WHY THIS EXISTS:
 * ContextPanel is the Intelligence tab's right-rail section (col-span-5) that
 * is ALWAYS in entity-overview mode. It is an important landmark for screen-
 * reader users navigating the tab — the `aria-label="Entity overview"` on the
 * <section> root must be preserved so AT users can jump to it directly.
 *
 * These tests verify the minimum aria contract:
 *   1. Top-level container has `role="region"` (implicit on <section>) with a
 *      valid accessible name.
 *   2. No interactive buttons lack aria-labels (the close button in InlineSelectionPanel
 *      already has one — ContextPanel itself has no buttons at the panel level).
 *
 * WHY mock everything to loading state:
 * We only care about the panel-level accessibility contract — not the data
 * returned by child query hooks. All child components are mocked to minimal
 * stubs so the test does not depend on the API shape of any child.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// Mock all child blocks to lightweight stubs so this test focuses purely on
// ContextPanel's own markup (role, aria-label, structure).
vi.mock("@/components/instrument/intelligence/context/EntityOverviewBlock", () => ({
  EntityOverviewBlock: () => <div data-testid="entity-overview-stub" />,
}));

vi.mock("@/components/instrument/intelligence/context/TopRelationsBlock", () => ({
  TopRelationsBlock: ({ onNodeSelect }: { onNodeSelect: (id: string) => void }) => (
    <div data-testid="top-relations-stub">
      <button
        type="button"
        aria-label="Select relation node"
        onClick={() => onNodeSelect("stub-node")}
      >
        Relation row
      </button>
    </div>
  ),
}));

vi.mock("@/components/instrument/intelligence/context/PathInsightsBlock", () => ({
  PathInsightsBlock: () => <div data-testid="path-insights-stub" />,
}));

vi.mock("@/components/instrument/intelligence/context/ContradictionsBlock", () => ({
  ContradictionsBlock: () => <div data-testid="contradictions-stub" />,
}));

vi.mock("@/components/instrument/intelligence/context/NarrativeHistoryDisclosure", () => ({
  NarrativeHistoryDisclosure: () => <div data-testid="narrative-history-stub" />,
}));

vi.mock("@/components/primitives/SectionDivider", () => ({
  SectionDivider: () => <hr />,
}));

// WHY mock OpportunityPathsPanel: added in PLAN-0091 D-1, mounted inside
// ContextPanel. Without this mock, the component tries to call useEntityPaths
// → useAccessToken which requires ApiClientProvider (not present in this test).
// ContextPanel tests focus on ContextPanel's own aria contract, not child data.
vi.mock("@/components/instrument/intelligence/OpportunityPathsPanel", () => ({
  OpportunityPathsPanel: () => <div data-testid="opportunity-paths-stub" />,
}));

// ── Import AFTER mocks ────────────────────────────────────────────────────────

// eslint-disable-next-line import/first
import { ContextPanel } from "@/components/instrument/intelligence/context/ContextPanel";

// ── Helpers ───────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ContextPanel — aria contract (F-009)", () => {
  it("top-level container is a landmark region with aria-label 'Entity overview'", () => {
    // WHY getByRole("region"): <section> with aria-label becomes a landmark region.
    // Screen readers expose it as a navigation target ("Entity overview" region).
    // This is the A11y contract for the right-rail panel.
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" />
      </Wrapper>,
    );

    const region = screen.getByRole("region", { name: /entity overview/i });
    expect(region).toBeInTheDocument();
  });

  it("renders all child block stubs inside the region", () => {
    // WHY: ensures ContextPanel assembles all 5 blocks (EntityOverview, TopRelations,
    // PathInsights, Contradictions, NarrativeHistory). A missing block would break
    // the analyst's workflow silently.
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" />
      </Wrapper>,
    );

    expect(screen.getByTestId("entity-overview-stub")).toBeInTheDocument();
    expect(screen.getByTestId("top-relations-stub")).toBeInTheDocument();
    expect(screen.getByTestId("path-insights-stub")).toBeInTheDocument();
    expect(screen.getByTestId("contradictions-stub")).toBeInTheDocument();
    expect(screen.getByTestId("narrative-history-stub")).toBeInTheDocument();
  });

  it("all interactive buttons inside the panel have aria-labels", () => {
    // WHY: buttons without aria-labels are opaque to screen readers — an AT user
    // would hear "button" with no context. We assert that all <button> elements
    // within ContextPanel have a non-empty accessible name.
    // NOTE: the TopRelationsBlock stub above includes a button with aria-label
    // to simulate the real component's row buttons.
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" />
      </Wrapper>,
    );

    const buttons = screen.getAllByRole("button");
    for (const btn of buttons) {
      // aria-label OR aria-labelledby OR visible text — getByRole checks all.
      // Simply asserting the element exists with a role is sufficient here
      // because RTL's getAllByRole only finds buttons that are in the a11y tree.
      expect(btn).toBeInTheDocument();
      // Accessible name must be non-empty (RTL resolves from aria-label / text content).
      const accessibleName = btn.getAttribute("aria-label") ?? btn.textContent ?? "";
      expect(accessibleName.trim()).not.toBe("");
    }
  });
});
