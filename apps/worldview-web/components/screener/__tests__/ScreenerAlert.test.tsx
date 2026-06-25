/**
 * components/screener/__tests__/ScreenerAlert.test.tsx
 *
 * WHY THIS FILE EXISTS (roadmap #6b / A3):
 *   ScreenerAlert is the designed replacement for the NL search's bare red text.
 *   The load-bearing contract is its a11y role (error = assertive "alert",
 *   warning = polite "status") and that it renders the message — both are easy
 *   to regress when restyling. These tests pin that contract.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScreenerAlert } from "@/components/screener/ScreenerAlert";

describe("ScreenerAlert", () => {
  it("renders an error variant with role='alert' and the message", () => {
    render(<ScreenerAlert variant="error">Backend exploded</ScreenerAlert>);
    const el = screen.getByRole("alert");
    expect(el).toHaveTextContent("Backend exploded");
  });

  it("renders a warning variant with role='status' (polite, not a failure)", () => {
    render(<ScreenerAlert variant="warning">Try naming a metric</ScreenerAlert>);
    const el = screen.getByRole("status");
    expect(el).toHaveTextContent("Try naming a metric");
  });

  it("defaults to the error variant", () => {
    render(<ScreenerAlert>Default is error</ScreenerAlert>);
    expect(screen.getByRole("alert")).toHaveTextContent("Default is error");
  });

  it("carries a bordered tinted surface (designed, not bare text)", () => {
    render(<ScreenerAlert variant="error">x</ScreenerAlert>);
    // The bordered/tinted container is what distinguishes this from a raw <p>.
    expect(screen.getByRole("alert").className).toMatch(/border/);
  });
});
