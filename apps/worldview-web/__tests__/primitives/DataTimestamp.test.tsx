/**
 * __tests__/primitives/DataTimestamp.test.tsx
 *
 * PRD-0089 F1: pins the null → "Data not yet available" fallback contract.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTimestamp } from "@/components/primitives/DataTimestamp";

describe("DataTimestamp", () => {
  it("renders the not-yet-available message when updatedAt is null", () => {
    render(<DataTimestamp updatedAt={null} />);
    expect(screen.getByText("Data not yet available")).toBeInTheDocument();
  });

  it("renders the formatted date when updatedAt is an ISO string", () => {
    render(<DataTimestamp updatedAt="2026-05-20T14:21:08Z" />);
    expect(screen.getByText(/Data as of/)).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });
});
