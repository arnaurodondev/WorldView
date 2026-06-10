/**
 * components/primitives/__tests__/RouteErrorFallback.test.tsx
 *
 * Round-4 hardening: pins the shared route-level error boundary body
 * (DESIGN_SYSTEM.md §6.7.1). The contract under test:
 *
 *   1. Named state — the routeLabel renders as the uppercase micro-label so
 *      a screenshot identifies the broken surface.
 *   2. "Try again" calls the Next.js reset() callback (segment re-render).
 *   3. The error digest renders (small, mono) when present, and the line is
 *      absent when Next.js didn't attach one.
 *   4. error.message is NEVER rendered — generic copy only (info-leak hygiene).
 *
 * Also smoke-tests the two route wrappers that compose the primitive
 * (app/(app)/error.tsx group fallback + app/(app)/indices/error.tsx) so a
 * refactor that breaks their prop plumbing fails here, not in production.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { RouteErrorFallback } from "@/components/primitives/RouteErrorFallback";
import AppGroupError from "@/app/(app)/error";
import IndicesError from "@/app/(app)/indices/error";

// WHY suppress console.error: the component intentionally logs the real error
// to the console (its UI shows generic copy). Letting that hit the test output
// would look like a failure; spying also lets us assert the logging happens.
function makeError(digest?: string): Error & { digest?: string } {
  const err = new Error("S9 returned 502 for /v1/instruments") as Error & {
    digest?: string;
  };
  if (digest) err.digest = digest;
  return err;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RouteErrorFallback", () => {
  it("renders the named state, generic copy, and the digest when present", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteErrorFallback
        error={makeError("NEXT-abc123")}
        reset={vi.fn()}
        routeLabel="Indices"
      />,
    );

    // Named state — surface label is visible (role=alert announces it too).
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/indices — error/i)).toBeInTheDocument();

    // Generic heading + recovery copy.
    expect(screen.getByText("This panel failed to render")).toBeInTheDocument();

    // Digest visible, small debugging handle.
    expect(screen.getByText(/digest: NEXT-abc123/)).toBeInTheDocument();

    // Escape hatch link points home.
    expect(
      screen.getByRole("link", { name: /back to dashboard/i }),
    ).toHaveAttribute("href", "/dashboard");
  });

  it("calls reset() when 'Try again' is clicked", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reset = vi.fn();
    render(
      <RouteErrorFallback error={makeError()} reset={reset} routeLabel="App" />,
    );

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("omits the digest line when Next.js attached no digest", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteErrorFallback error={makeError()} reset={vi.fn()} routeLabel="App" />,
    );
    expect(screen.queryByText(/digest:/)).not.toBeInTheDocument();
  });

  it("never renders the raw error message (info-leak hygiene)", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteErrorFallback error={makeError()} reset={vi.fn()} routeLabel="App" />,
    );
    // The raw message must only go to console.error, never the DOM.
    expect(
      screen.queryByText(/S9 returned 502/),
    ).not.toBeInTheDocument();
  });

  it("logs the real error to the console for developers", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const err = makeError();
    render(<RouteErrorFallback error={err} reset={vi.fn()} routeLabel="News" />);
    expect(spy).toHaveBeenCalledWith("[RouteErrorBoundary:News]", err);
  });
});

describe("route error.tsx wrappers compose the primitive", () => {
  it("app/(app)/error.tsx renders the group fallback with the App label and working reset", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reset = vi.fn();
    render(<AppGroupError error={makeError("NEXT-grp")} reset={reset} />);

    expect(screen.getByText(/app — error/i)).toBeInTheDocument();
    expect(screen.getByText(/digest: NEXT-grp/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("app/(app)/indices/error.tsx names the Indices surface", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<IndicesError error={makeError()} reset={vi.fn()} />);
    expect(screen.getByText(/indices — error/i)).toBeInTheDocument();
  });
});
