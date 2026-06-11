/**
 * MessageMetaStrip.test.tsx — PLAN-0089 K Block I T-22 case 3.
 *
 * WHAT THIS GUARDS:
 *   - The strip renders intent / provider / model / latency / created-at
 *     fragments when present.
 *   - When EVERY fragment is absent the component returns null (no empty
 *     grid row that would inflate vertical space).
 *   - When latency is null AND isStreaming is true, the "streaming…" label
 *     substitutes. The Wave K design relies on this signal to communicate
 *     in-flight state alongside the accent rail.
 *   - Latency formatting: <1000ms renders as "Xms"; ≥1000ms as "X.Xs".
 *
 * WAVE-2 UPDATE (frontend-rework sprint): user turns now render a strip too
 * — but ONLY the timestamp fragment (the empty-guard still collapses a
 * prop-less user turn to null, preserving the original contract below).
 * New citationCount prop renders an "N sources" fragment on assistant turns.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import { MessageMetaStrip } from "../MessageMetaStrip";

describe("MessageMetaStrip (Wave K T-09)", () => {
  it("returns null for user turns (no fields to show)", () => {
    const { container } = render(<MessageMetaStrip role="user" />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null for assistant when every fragment is absent", () => {
    // No intent, no provider, no model, no latency, no createdAt, no
    // fallback. Component must NOT render an empty <div>.
    const { container } = render(<MessageMetaStrip role="assistant" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the REASONING intent variant", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" intent="REASONING" />,
    );
    expect(container.textContent).toContain("REASONING");
  });

  it("renders provider and model fragments when supplied", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" provider="DeepInfra" model="deepseek-r1" />,
    );
    expect(container.textContent).toContain("DeepInfra");
    expect(container.textContent).toContain("deepseek-r1");
  });

  it("formats latency under 1s as Xms", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" latencyMs={420} />,
    );
    expect(container.textContent).toContain("420ms");
  });

  it("formats latency >=1s as X.Xs", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" latencyMs={1400} />,
    );
    expect(container.textContent).toContain("1.4s");
  });

  it("substitutes 'streaming…' when latency is null and isStreaming is true", () => {
    // WHY this matters: the streaming label is the second visual signal
    // (alongside the accent rail) that the turn is still in-flight. If it
    // regresses, history-reloaded turns would look identical to streaming
    // ones.
    const { container } = render(
      <MessageMetaStrip role="assistant" intent="REASONING" isStreaming />,
    );
    expect(container.textContent).toContain("streaming");
  });

  it("renders the fallback chip when isFallback is true", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" intent="REASONING" isFallback />,
    );
    expect(container.textContent).toContain("fallback");
  });

  // ── Wave 2 (frontend-rework sprint) — per-message strip additions ──────────

  it("renders ONLY the timestamp for user turns (no assistant fragments)", () => {
    const { container } = render(
      <MessageMetaStrip
        role="user"
        createdAt="2026-06-11T14:01:24Z"
        // Assistant-only props supplied on a user turn must be IGNORED —
        // a user bubble claiming a provider/latency would be nonsense.
        intent="REASONING"
        provider="DeepInfra"
        latencyMs={420}
        citationCount={3}
      />,
    );
    expect(container.firstChild).not.toBeNull();
    expect(container.textContent).not.toContain("REASONING");
    expect(container.textContent).not.toContain("DeepInfra");
    expect(container.textContent).not.toContain("420ms");
    expect(container.textContent).not.toContain("sources");
    // The clock fragment is present (exact rendering is locale-dependent —
    // we assert the strip is non-empty and free of assistant fragments).
    expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
  });

  it("renders the citation count fragment on assistant turns", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" citationCount={3} />,
    );
    expect(container.textContent).toContain("3 sources");
  });

  it("uses the singular 'source' for exactly one citation", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" citationCount={1} />,
    );
    expect(container.textContent).toContain("1 source");
    expect(container.textContent).not.toContain("1 sources");
  });

  it("renders NO citation fragment for zero citations (ungrounded ≠ anomaly)", () => {
    const { container } = render(
      <MessageMetaStrip role="assistant" intent="CHITCHAT" citationCount={0} />,
    );
    expect(container.textContent).not.toContain("source");
  });
});
