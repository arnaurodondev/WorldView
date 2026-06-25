/**
 * components/screener/__tests__/ScreenerFilterBar.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: this file pins the parts of the OQ-10 sector→industry cascading
 * that ship in Wave I-A. The current FilterState exposes a single
 * `sector: string` (not multi-select sectors + industries); the multi-
 * select + interactive cascading combobox land in Wave I-B once
 * FilterState grows the new fields (plan §5.1 T-IA-05 explicitly stages
 * this). Today we assert:
 *
 *   1. The bar renders and exposes the sector single-select combobox.
 *   2. The static GICS helper used by the cascade returns sane outputs
 *      for the canonical "Information Technology" sector — pairs with
 *      lib/screener/__tests__/gics-hierarchy.test.ts as an integration
 *      smoke test from the FilterBar consumer's perspective.
 *
 * The interactive "switch from Tech to Energy resets industries" spec
 * called out by the plan is moved to I-B and tracked there because the
 * industries combobox does not yet exist in the rendered tree. Deleting
 * the spec would violate R19 — we therefore `test.skip` it with a clear
 * TODO so the intent stays visible in the test report.
 */

import { describe, expect, it, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ScreenerFilterBar } from "@/components/screener/ScreenerFilterBar";
import { industriesForSectors } from "@/lib/screener/gics-hierarchy";

describe("ScreenerFilterBar — sector controls", () => {
  it("renders the sector single-select combobox when open", () => {
    // WHY: smoke test — the bar's primary surface is the sector combobox.
    // If it stops rendering, every cascading test downstream is moot.
    render(
      <ScreenerFilterBar
        isOpen
        onToggle={() => {}}
        onApply={() => {}}
        totalResults={0}
        loadedCount={0}
        isLoading={false}
      />,
    );
    // The bar labels the combobox "Filter by GICS sector".
    expect(
      screen.getByLabelText(/Filter by GICS sector/i),
    ).toBeInTheDocument();
  });

  it("integration smoke: industriesForSectors returns IT industries for the IT sector", () => {
    // WHY: the cascade helper is wired inside ScreenerFilterBar but the
    // industries combobox itself does not yet exist on the FilterState
    // shape (plan §5.1 T-IA-05). We assert the helper integration so the
    // future I-B work has a confirmed-correct upstream contract to mount
    // its combobox against.
    const industries = industriesForSectors(["Information Technology"]);
    expect(industries.length).toBeGreaterThan(0);
    expect(
      industries.some((i) => /software|technology|semiconductors/i.test(i)),
    ).toBe(true);
  });

  // R19 — never delete tests. This spec belongs to the interactive
  // cascade that ships once FilterState grows `sectors: string[]` +
  // `industries: string[]`. Skipping (not deleting) keeps the intent
  // visible in test output until I-B mounts the multi-select.
  test.skip("switching sector from Tech to Energy resets industry chips (Wave I-B)", () => {
    // TODO(plan-0089-wi-b): unskip when FilterState gains multi-select
    // sectors + industries fields and ScreenerFilterBar mounts the
    // industries combobox. The expected behaviour is documented in
    // plan §5.1 T-IA-05 ("silently drop the now-invalid industry
    // selections and emit a transient toast").
  });
});

// ── Round-4 item 3b: slider changes must NOT fire server queries ─────────────
//
// WHY THIS BLOCK: a dual-thumb slider emits a value on EVERY step of a drag
// (tens of events per second). If each emission reached `onApply`, every drag
// would hammer S9 with POST /v1/fundamentals/screen calls. The screener's
// architecture already prevents this AT THE SOURCE — slider events write only
// the bar's LOCAL form state, and nothing crosses the network until the
// explicit Apply click (an even stronger guarantee than a ~300ms query-layer
// debounce, which would still send one POST per drag-pause). These tests pin
// that gate so a future "make sliders live" change must consciously add a
// debounce instead of inheriting an accidental query storm. (The chip strip's
// 250ms debounce path is pinned separately in FilterChipStrip.test.tsx.)

describe("ScreenerFilterBar — sliders are Apply-gated, never live (Round 4)", () => {
  function renderBar() {
    const onApply = vi.fn();
    render(
      <ScreenerFilterBar
        isOpen
        onToggle={() => {}}
        onApply={onApply}
        totalResults={0}
        loadedCount={0}
        isLoading={false}
      />,
    );
    return { onApply };
  }

  it("rapid slider nudges do not call onApply (no POST per slider event)", () => {
    const { onApply } = renderBar();

    // The P/E slider lives in the default-open Valuation section.
    const lowThumb = screen.getByLabelText(/P\/E \(TTM\) lower bound slider thumb/i);
    // WHY focus first: Radix routes keyboard input to the focused thumb.
    fireEvent.focus(lowThumb);
    // Simulate a rapid drag: 5 keyboard steps back-to-back.
    for (let i = 0; i < 5; i++) {
      fireEvent.keyDown(lowThumb, { key: "ArrowRight" });
    }

    // Local form state moved (the readout reflects it) but the parent —
    // and therefore the network — saw NOTHING.
    expect(onApply).not.toHaveBeenCalled();
  });

  it("Apply commits the slider-set value exactly once", () => {
    const { onApply } = renderBar();

    const lowThumb = screen.getByLabelText(/P\/E \(TTM\) lower bound slider thumb/i);
    fireEvent.focus(lowThumb);
    // One step on the PE_SCALE (linear 0–100 over 200 steps) = 0.5 P/E.
    fireEvent.keyDown(lowThumb, { key: "ArrowRight" });

    fireEvent.click(screen.getByRole("button", { name: /apply filters/i }));

    // One commit, carrying the slider-set bound — the entire drag session
    // costs exactly one server round-trip.
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toMatchObject({ peMin: 0.5 });
  });
});
