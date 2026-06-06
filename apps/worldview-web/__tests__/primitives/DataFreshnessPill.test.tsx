/**
 * __tests__/primitives/DataFreshnessPill.test.tsx
 *
 * PRD-0089 F1: pins the relative-display + absolute-UTC tooltip contract.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataFreshnessPill } from "@/components/primitives/DataFreshnessPill";

describe("DataFreshnessPill", () => {
  it("renders em-dash when timestamp is invalid", () => {
    render(<DataFreshnessPill lastUpdated="not-a-date" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders an absolute UTC tooltip when format='relative'", () => {
    const past = new Date(Date.now() - 5 * 60_000); // 5 minutes ago
    render(<DataFreshnessPill lastUpdated={past} />);
    const el = screen.getByText(/m ago/);
    expect(el.getAttribute("title")).toMatch(/UTC$/);
  });

  it("renders the absolute UTC string when format='absolute'", () => {
    render(<DataFreshnessPill lastUpdated="2026-05-20T14:21:08Z" format="absolute" />);
    expect(screen.getByText(/2026-05-20 14:21:08 UTC/)).toBeInTheDocument();
  });
});
