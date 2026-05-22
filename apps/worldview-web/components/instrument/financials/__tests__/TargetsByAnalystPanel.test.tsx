/**
 * TargetsByAnalystPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the section header contract for this stub panel.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TargetsByAnalystPanel } from "@/components/instrument/financials/sidebar/TargetsByAnalystPanel";

describe("TargetsByAnalystPanel", () => {
  it("renders section header", () => {
    render(<TargetsByAnalystPanel />);
    expect(screen.getByText("TARGETS BY ANALYST")).toBeInTheDocument();
  });

  it("renders the stub footnote", () => {
    render(<TargetsByAnalystPanel />);
    expect(screen.getByText(/per-firm targets pending/i)).toBeInTheDocument();
  });
});
