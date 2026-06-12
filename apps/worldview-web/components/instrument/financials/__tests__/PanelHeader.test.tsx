/**
 * PanelHeader.test.tsx — uniform 24px accent-bar panel header
 * (Wave-2 redesign, scope item 1 — net-new shared primitive for the tab).
 *
 * CONTRACTS:
 *   1. 24px band (h-6) with the primary accent bar + muted tint — the ONE
 *      header treatment every Financials panel now shares (drift in header
 *      chrome was a core "sloppy" signal this redesign kills).
 *   2. Label renders uppercase mono at 10px / 0.08em tracking.
 *   3. Optional meta sub-caption and right slot render when provided.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PanelHeader } from "@/components/instrument/financials/PanelHeader";

describe("PanelHeader", () => {
  it("renders the 24px accent-bar band", () => {
    const { container } = render(<PanelHeader label="PEER COMPARISON" />);
    const band = container.querySelector("[data-panel-header]") as HTMLElement;
    expect(band).not.toBeNull();
    // The locked chrome: 24px height + primary accent bar + muted tint.
    expect(band.className).toContain("h-6");
    expect(band.className).toContain("border-l-primary");
    expect(band.className).toContain("bg-muted/20");
  });

  it("renders the label with the locked typography", () => {
    render(<PanelHeader label="FUND HOLDERS" />);
    const label = screen.getByText("FUND HOLDERS");
    expect(label.className).toContain("font-mono");
    expect(label.className).toContain("text-[10px]");
    expect(label.className).toContain("tracking-[0.08em]");
    expect(label.className).toContain("uppercase");
  });

  it("renders meta and right-slot children when provided", () => {
    render(
      <PanelHeader label="EARNINGS" meta="annual EPS · actual vs estimate">
        <button>toggle</button>
      </PanelHeader>,
    );
    expect(screen.getByText("annual EPS · actual vs estimate")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "toggle" })).toBeInTheDocument();
  });
});
