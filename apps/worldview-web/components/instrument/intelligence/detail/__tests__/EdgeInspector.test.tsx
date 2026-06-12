/**
 * detail/__tests__/EdgeInspector.test.tsx — PLAN-0099 Wave 2.
 *
 * Pins the edge-dossier render against a mocked GET /v1/relations/{id}
 * response (useRelationDetail): subject→object header, classification chips,
 * confidence + STALE indicator, temporal validity, LLM summary provenance,
 * and the EVIDENCE LIST — each row showing the evidence_text chunk, polarity
 * dot, source name, date, and extraction confidence.
 *
 * Also pins the three non-loaded states: shape-matched skeleton (loading),
 * NAMED error with Retry, and the 404→null "relation no longer available"
 * named degradation.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

// Mock ONLY useRelationDetail — the inspector's single data dependency.
const mockUseRelationDetail = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/intelligence", () => ({
  useRelationDetail: mockUseRelationDetail,
}));

import { EdgeInspector } from "@/components/instrument/intelligence/detail/EdgeInspector";
import type { RelationDetail } from "@/lib/api/knowledge-graph";

const RELATION: RelationDetail = {
  relation_id: "rel-1",
  canonical_type: "is_in_sector",
  semantic_mode: "RELATION_STATE",
  decay_class: "PERMANENT",
  confidence: 0.95,
  confidence_stale: false,
  summary_authority: 2.36,
  evidence_count: 11,
  first_evidence_at: "2026-05-25T23:41:50Z",
  latest_evidence_at: "2026-06-06T19:29:44Z",
  valid_from: "2026-05-25T23:44:30Z",
  valid_to: null,
  relation_period_type: "ONGOING",
  strongest_contra_score: 0,
  latest_contra_at: null,
  relation_source: null,
  created_at: "2026-05-25T23:41:50Z",
  updated_at: "2026-05-25T23:41:50Z",
  relation_summary: "EODHD classifies the entity in the Information Technology sector.",
  summary_generated_at: "2026-06-01T04:02:09Z",
  summary_model_id: "kg-summary-v1",
  subject: {
    entity_id: "ent-aapl",
    canonical_name: "Apple Inc.",
    entity_type: "financial_instrument",
    isin: null,
    ticker: "AAPL",
    exchange: "US",
    description: "Apple designs consumer electronics.",
    sector: "Information Technology",
    industry: null,
    market_cap: null,
  },
  object: {
    entity_id: "ent-sector",
    canonical_name: "Information Technology",
    entity_type: "sector",
    isin: null,
    ticker: null,
    exchange: null,
    description: "The IT sector.",
    sector: null,
    industry: null,
    market_cap: null,
  },
  evidence: [
    {
      raw_id: "ev-1",
      evidence_text: "EODHD fundamentals: Information Technology sector classification.",
      document_id: "doc-1",
      source_name: "eodhd",
      source_type: "eodhd",
      polarity: "neutral",
      evidence_date: "2026-06-06T19:33:16Z",
      extraction_confidence: 0.9,
      source_trust_weight: 0.9,
      is_backfill: false,
      extracted_at: "2026-06-06T19:29:44Z",
    },
    {
      raw_id: "ev-2",
      evidence_text: "Apple was reclassified within the IT index in May.",
      document_id: "doc-2",
      source_name: "Reuters",
      source_type: "eodhd_ticker_news",
      polarity: "positive",
      evidence_date: "2026-05-30T08:00:00Z",
      extraction_confidence: 0.74,
      source_trust_weight: 0.8,
      is_backfill: false,
      extracted_at: "2026-05-30T09:00:00Z",
    },
  ],
};

function setHookState(state: {
  data?: RelationDetail | null;
  isLoading?: boolean;
  isError?: boolean;
  refetch?: () => void;
}) {
  mockUseRelationDetail.mockReturnValue({
    data: state.data,
    isLoading: state.isLoading ?? false,
    isError: state.isError ?? false,
    refetch: state.refetch ?? vi.fn(),
  });
}

beforeEach(() => mockUseRelationDetail.mockReset());
afterEach(() => cleanup());

describe("EdgeInspector loaded dossier", () => {
  it("renders the subject → relation type → object header", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("IS IN SECTOR")).toBeInTheDocument();
    expect(screen.getByText("Information Technology")).toBeInTheDocument();
  });

  it("renders semantic-mode + decay classification chips", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText("RELATION STATE")).toBeInTheDocument();
    expect(screen.getByText("PERMANENT")).toBeInTheDocument();
    expect(screen.getByText("ONGOING")).toBeInTheDocument();
  });

  it("renders the confidence bar value and hides STALE for fresh scores", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText("95 / 100")).toBeInTheDocument();
    expect(screen.queryByText("STALE")).not.toBeInTheDocument();
  });

  it("renders the STALE chip when confidence_stale is true", () => {
    setHookState({ data: { ...RELATION, confidence_stale: true } });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText("STALE")).toBeInTheDocument();
  });

  it("renders the temporal validity row ('ongoing' for open-ended relations)", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText(/Valid/)).toBeInTheDocument();
    expect(screen.getByText("ongoing")).toBeInTheDocument();
  });

  it("renders the LLM summary with model provenance", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    expect(
      screen.getByText(/EODHD classifies the entity in the Information Technology sector/),
    ).toBeInTheDocument();
    expect(screen.getByText(/kg-summary-v1/)).toBeInTheDocument();
  });

  it("renders EVERY evidence chunk as a quoted block with provenance", () => {
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" />);
    // The chunks themselves — the centrepiece of the inspector.
    expect(
      screen.getByText("EODHD fundamentals: Information Technology sector classification."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Apple was reclassified within the IT index in May."),
    ).toBeInTheDocument();
    // Source names (article title/url not available — graceful fallback).
    expect(screen.getByText("eodhd")).toBeInTheDocument();
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    // Extraction confidence, mono numerics.
    expect(screen.getByText("conf 0.90")).toBeInTheDocument();
    expect(screen.getByText("conf 0.74")).toBeInTheDocument();
    // One polarity dot per evidence row.
    expect(screen.getAllByTestId("evidence-polarity-dot")).toHaveLength(2);
  });

  it("shows 'shown of total' when evidence_count exceeds the fetched page", () => {
    setHookState({ data: RELATION }); // 2 fetched, evidence_count 11
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByText("2 of 11")).toBeInTheDocument();
  });

  it("renders the contradiction stats line when contra evidence exists", () => {
    setHookState({
      data: { ...RELATION, strongest_contra_score: 0.45, latest_contra_at: "2026-06-01T00:00:00Z" },
    });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByTestId("edge-contra-stats")).toBeInTheDocument();
    expect(screen.getByText(/0\.45/)).toBeInTheDocument();
  });

  it("fires onSelectNode with the endpoint entity id when a pill is clicked", () => {
    const onSelectNode = vi.fn();
    setHookState({ data: RELATION });
    render(<EdgeInspector relationId="rel-1" onSelectNode={onSelectNode} />);
    // The pill's accessible name is its visible content ("Apple Inc. AAPL");
    // the title attribute carries the "Inspect …" hint — query by title.
    fireEvent.click(screen.getByTitle("Inspect Apple Inc."));
    expect(onSelectNode).toHaveBeenCalledWith("ent-aapl");
  });
});

describe("EdgeInspector non-loaded states", () => {
  it("renders the shape-matched skeleton while loading", () => {
    setHookState({ isLoading: true });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByTestId("edge-inspector-skeleton")).toBeInTheDocument();
  });

  it("renders the NAMED error with a working Retry", () => {
    const refetch = vi.fn();
    setHookState({ isError: true, refetch });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByTestId("edge-inspector-error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders the named 'relation no longer available' state for 404→null", () => {
    setHookState({ data: null });
    render(<EdgeInspector relationId="rel-1" />);
    expect(screen.getByTestId("edge-inspector-gone")).toBeInTheDocument();
    expect(screen.getByText(/Relation no longer available/)).toBeInTheDocument();
  });
});
