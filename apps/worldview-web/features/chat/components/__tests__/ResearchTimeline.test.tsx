/**
 * features/chat/components/__tests__/ResearchTimeline.test.tsx
 *
 * Phase-1 Part C — the always-visible, human-readable agent-step trace.
 *
 * These tests pin the contract the whole effort exists to deliver:
 *   1. It renders the agent's steps as legible HUMAN lines (from resultLabel),
 *      grouped by loop iteration, with per-tool result counts.
 *   2. It shows a "Verifying answer…" line when the verifying flag is true.
 *   3. On stream completion (mode="done") it COLLAPSES to a one-line summary
 *      and expands the full list on click.
 *   4. It is a pure prop-driven component — it renders WITHOUT any ?debug gate
 *      (the gating problem this effort fixes lived in the PAGE; the component
 *      itself has no debug awareness, which these tests document).
 *
 * Pure-render component (no hooks beyond local collapse state, no SSE) — unit
 * tests with @testing-library/react fully cover it.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchTimeline } from "../ResearchTimeline";
import type { ToolTraceEntry } from "../../lib/types";

/**
 * A two-step research trace: step 0 searches news (ok, 12 articles) + queries
 * the KG (empty); step 1 fetches a quote (still running). Mirrors the real
 * shape useChatStream produces — `resultLabel` is the input-aware human label.
 */
const TRACE: ToolTraceEntry[] = [
  {
    tool: "search_news",
    label: "Searching news…",
    args: { entity: "NVIDIA" },
    status: "ok",
    result: { item_count: 12 },
    latencyMs: 240,
    latencySource: "server",
    iteration: 0,
    resultLabel: "Searching news for NVIDIA",
  },
  {
    tool: "query_kg",
    label: "Querying knowledge graph…",
    args: { entity: "NVIDIA" },
    status: "empty",
    result: { item_count: 0 },
    latencyMs: 90,
    latencySource: "server",
    iteration: 0,
    resultLabel: "Querying knowledge graph for NVIDIA",
  },
  {
    tool: "get_quote",
    label: "Fetching quote…",
    args: { ticker: "NVDA" },
    status: "running",
    result: null,
    latencyMs: null,
    latencySource: null,
    iteration: 1,
    resultLabel: "Fetching quote…",
  },
];

describe("ResearchTimeline — live mode", () => {
  it("renders each step as a human-readable line from resultLabel", () => {
    render(<ResearchTimeline trace={TRACE} verifying={false} />);

    // Completed lines show the input-aware label with the trailing ellipsis
    // stripped (settled state). The running line keeps its ellipsis.
    expect(screen.getByText("Searching news for NVIDIA")).toBeDefined();
    expect(screen.getByText("Querying knowledge graph for NVIDIA")).toBeDefined();
    expect(screen.getByText("Fetching quote…")).toBeDefined();
  });

  it("groups multi-step traces under Step dividers and shows result counts", () => {
    render(<ResearchTimeline trace={TRACE} verifying={false} />);

    // Two distinct iterations → two "Step" headers (1-indexed for humans).
    expect(screen.getByText("Step 1")).toBeDefined();
    expect(screen.getByText("Step 2")).toBeDefined();

    // The "ok" tool surfaces its item_count as a compact "· 12" suffix.
    expect(screen.getByText(/· 12/)).toBeDefined();
  });

  it("does NOT render a lone Step divider for a single-iteration trace", () => {
    render(<ResearchTimeline trace={[TRACE[0]]} verifying={false} />);
    // A single implicit step folds in unlabelled — no noisy "Step 1" header.
    expect(screen.queryByText("Step 1")).toBeNull();
    expect(screen.getByText("Searching news for NVIDIA")).toBeDefined();
  });

  it("shows the verifying line when verifying is true", () => {
    render(<ResearchTimeline trace={TRACE} verifying={true} />);
    expect(screen.getByText("Verifying answer against sources…")).toBeDefined();
  });

  it("renders the live region (aria-live) so progress is announced", () => {
    render(<ResearchTimeline trace={TRACE} verifying={false} />);
    const region = screen.getByTestId("research-timeline");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.getAttribute("role")).toBe("status");
  });

  it("renders nothing before any activity (empty trace, not verifying)", () => {
    const { container } = render(<ResearchTimeline trace={[]} verifying={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders even when verifying with no tools (verify-only turn)", () => {
    render(<ResearchTimeline trace={[]} verifying={true} />);
    expect(screen.getByText("Verifying answer against sources…")).toBeDefined();
  });

  it("is visible WITHOUT any debug flag — it takes no debug prop at all", () => {
    // The component has no ?debug awareness: passing only the data renders the
    // full timeline. This documents the ungating fix (the gate lived in the
    // page; the timeline itself is unconditionally first-class).
    render(<ResearchTimeline trace={TRACE} verifying={false} />);
    expect(screen.getByTestId("research-timeline")).toBeDefined();
  });
});

describe("ResearchTimeline — done mode (collapse-to-summary)", () => {
  it("collapses to a one-line summary of sources and steps", () => {
    render(<ResearchTimeline trace={TRACE} verifying={false} mode="done" />);

    // 3 tool invocations across 2 distinct iterations.
    expect(screen.getByText(/Researched 3 sources across 2 steps/)).toBeDefined();
    // Collapsed by default: the individual step lines are NOT shown yet.
    expect(screen.queryByText("Searching news for NVIDIA")).toBeNull();
  });

  it("expands the full step list when the summary is clicked", () => {
    render(<ResearchTimeline trace={TRACE} verifying={false} mode="done" />);

    const toggle = screen.getByRole("button", { name: /Researched 3 sources/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // Now the human lines are visible.
    expect(screen.getByText("Searching news for NVIDIA")).toBeDefined();
    expect(screen.getByText("Fetching quote…")).toBeDefined();
  });

  it("uses singular nouns for a single source / single step", () => {
    render(<ResearchTimeline trace={[TRACE[0]]} verifying={false} mode="done" />);
    expect(screen.getByText(/Researched 1 source across 1 step/)).toBeDefined();
  });
});
