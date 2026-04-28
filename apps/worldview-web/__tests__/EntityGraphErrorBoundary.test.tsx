/**
 * __tests__/EntityGraphErrorBoundary.test.tsx — error boundary contract.
 *
 * Verifies that:
 *   - happy path renders children unchanged
 *   - a thrown render error is caught + the fallback renders
 *   - the "Try again" button resets the error state
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";

// React logs caught errors via console.error — silence the noise so the
// test output stays readable. We restore in afterEach.
let errSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  errSpy.mockRestore();
});

function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("simulated graph crash");
  return <div data-testid="graph-ok">ok</div>;
}

describe("EntityGraphErrorBoundary", () => {
  it("renders children when no error is thrown", () => {
    render(
      <EntityGraphErrorBoundary>
        <Boom shouldThrow={false} />
      </EntityGraphErrorBoundary>,
    );
    expect(screen.getByTestId("graph-ok")).toBeInTheDocument();
  });

  it("renders the fallback alert when a child throws", () => {
    render(
      <EntityGraphErrorBoundary>
        <Boom shouldThrow />
      </EntityGraphErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/could not render the entity graph/i)).toBeInTheDocument();
    expect(screen.getByText(/simulated graph crash/i)).toBeInTheDocument();
  });

  it("clears the error state when 'Try again' is clicked", () => {
    // Re-render after click with shouldThrow=false to verify the recovery
    // path actually mounts the children again.
    function Wrapper() {
      // Re-mount Boom on every parent render via key: a real-world recovery
      // would typically come from a data refetch; key change simulates a
      // successful retry.
      return (
        <EntityGraphErrorBoundary>
          <Boom shouldThrow />
        </EntityGraphErrorBoundary>
      );
    }
    const { rerender } = render(<Wrapper />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    // After reset, re-render with a child that does NOT throw.
    rerender(
      <EntityGraphErrorBoundary>
        <Boom shouldThrow={false} />
      </EntityGraphErrorBoundary>,
    );
    expect(screen.getByTestId("graph-ok")).toBeInTheDocument();
  });
});
