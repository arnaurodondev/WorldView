/**
 * RevisionsPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Even stub panels must render their section header so the
 * sidebar maintains its 7-panel structural contract.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RevisionsPanel } from "@/components/instrument/financials/sidebar/RevisionsPanel";

describe("RevisionsPanel", () => {
  it("renders section header", () => {
    render(<RevisionsPanel />);
    expect(screen.getByText("ESTIMATE REVISIONS")).toBeInTheDocument();
  });

  it("renders the stub footnote", () => {
    render(<RevisionsPanel />);
    expect(screen.getByText(/revisions history pending/i)).toBeInTheDocument();
  });
});
