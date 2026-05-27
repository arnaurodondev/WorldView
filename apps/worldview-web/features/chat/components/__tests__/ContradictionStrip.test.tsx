/**
 * ContradictionStrip.test.tsx — PLAN-0089 K Block I T-22 case 6.
 *
 * WHAT THIS GUARDS:
 *   - Severity colour ramps at the 0.7 (HIGH) / 0.4 (MEDIUM) thresholds.
 *     Below 0.4 → LOW. These thresholds must stay in lockstep with
 *     EntityHealthDot (T-15) — if they drift, the visual language across
 *     the rail loses coherence.
 *   - Returns null on empty arrays (no empty bordered box).
 *   - Each row carries `data-cell` so the density e2e (T-23) counts it.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import { ContradictionStrip } from "../ContradictionStrip";

describe("ContradictionStrip (Wave K T-11)", () => {
  it("returns null on empty arrays", () => {
    const { container } = render(<ContradictionStrip contradictions={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders HIGH severity (red) when strength >= 0.7", () => {
    const { container } = render(
      <ContradictionStrip
        contradictions={[{ claim_type: "founding_year", strength: 0.85 }]}
      />,
    );
    // The severity label is uppercase in the row.
    expect(container.textContent).toContain("HIGH");
    // Colour class — text-negative is the warning palette token for red.
    expect(container.querySelector(".text-negative")).not.toBeNull();
  });

  it("renders MEDIUM severity (warning) at 0.4 <= strength < 0.7", () => {
    const { container } = render(
      <ContradictionStrip
        contradictions={[{ claim_type: "outlook", strength: 0.5 }]}
      />,
    );
    expect(container.textContent).toContain("MEDIUM");
    expect(container.querySelector(".text-warning")).not.toBeNull();
  });

  it("renders LOW severity when strength < 0.4 (or missing)", () => {
    const { container } = render(
      <ContradictionStrip
        contradictions={[{ claim_type: "minor", strength: 0.1 }]}
      />,
    );
    expect(container.textContent).toContain("LOW");
  });

  it("tags each row with [data-cell] for the density gate", () => {
    // WHY: the density e2e counts visible [data-cell] elements. If a future
    // refactor drops this attribute, the gate would silently fail.
    const { container } = render(
      <ContradictionStrip
        contradictions={[
          { claim_type: "a", strength: 0.8 },
          { claim_type: "b", strength: 0.3 },
        ]}
      />,
    );
    const cells = container.querySelectorAll("[data-cell]");
    expect(cells.length).toBeGreaterThanOrEqual(2);
  });
});
