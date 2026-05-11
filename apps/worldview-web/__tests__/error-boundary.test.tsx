/**
 * __tests__/error-boundary.test.tsx — Sentry ErrorBoundary integration tests
 *
 * WHY THESE TESTS:
 *   1. GlobalErrorFallback must render the right message and a working Reload button.
 *   2. The Sentry.ErrorBoundary must render GlobalErrorFallback when a child throws.
 *   3. Sentry.captureException must be called — otherwise errors are invisible.
 *   4. The dev-tools/sentry-test route must 404 in production.
 *
 * WHY WE MOCK @sentry/nextjs:
 * The real SDK calls Sentry.init() which makes network requests and requires a DSN.
 * We provide a MockErrorBoundary that mirrors the real contract (catches errors,
 * calls captureException, renders fallback) so tests stay fast and isolated.
 *
 * VITEST HOISTING — THE DEFINITIVE EXPLANATION:
 *
 * 1. vi.mock() calls are hoisted to the TOP of the compiled file — before imports
 *    and before any module-level code runs.
 *
 * 2. Variables named `mock…` are ALSO hoisted by Vitest's babel transform, BUT
 *    only their DECLARATION is moved — NOT the initializer (= vi.fn()). So when
 *    the factory runs, a `const mockFoo = vi.fn()` variable exists in scope but
 *    is still in the Temporal Dead Zone (TDZ). Accessing it → ReferenceError.
 *
 * 3. `vi.hoisted(() => value)` is the CORRECT solution: it runs the callback
 *    SYNCHRONOUSLY before ANY mocks or imports, so the returned value is
 *    available (already initialized) when vi.mock() factories execute.
 *    This is the canonical Vitest API for exactly this pattern.
 *
 * 4. Classes that extend React.Component cannot be declared at module level
 *    and referenced in a factory, because React is an ES import — not yet bound
 *    during hoisting. Define them INSIDE the factory using require("react").
 *
 * PLAN-0065 T-D-02, PRD-0034 §3 FR-T3-1
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ─── Step 1: vi.hoisted — runs before vi.mock() factories ────────────────────
//
// WHY vi.hoisted: Vitest guarantees that vi.hoisted callbacks execute before
// the module mock factories fire. This creates a fully-initialized vi.fn() spy
// that can be safely referenced in the @sentry/nextjs factory below.
// Without vi.hoisted, the spy would be in TDZ when the factory tries to use it.
const mockCaptureException = vi.hoisted(() => vi.fn());

// ─── Step 2: vi.mock factories ───────────────────────────────────────────────

// Replace @sentry/nextjs with a minimal test double.
//
// WHY require("react") instead of import: the factory runs before ES imports
// are evaluated. CJS require() is synchronous and resolves the already-cached
// module, so React is available inside the factory body.
//
// WHY a class component: React's error boundary API (getDerivedStateFromError +
// componentDidCatch) only works in class components — hooks cannot catch render errors.
vi.mock("@sentry/nextjs", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const R = require("react") as typeof import("react");

  class MockErrorBoundary extends R.Component<
    { children: React.ReactNode; fallback: React.ReactNode },
    { hasError: boolean }
  > {
    // React.Component declares `state` in its type — noImplicitOverride requires `override` here.
    override state = { hasError: false };

    // getDerivedStateFromError is NOT declared in React.Component types (static lifecycle
    // looked up by React at runtime, not TypeScript-typed) — no `override` allowed.
    static getDerivedStateFromError() {
      return { hasError: true };
    }

    // componentDidCatch IS in React.Component → requires `override` (noImplicitOverride).
    override componentDidCatch(error: Error) {
      // vi.hoisted spy — guaranteed initialized before this factory ran.
      mockCaptureException(error);
    }

    override render() {
      if (this.state.hasError) return this.props.fallback;
      return this.props.children;
    }
  }

  return {
    ErrorBoundary: MockErrorBoundary,
    captureException: mockCaptureException,
  };
});

// Mock next/navigation: notFound() throws a Next.js internal error in real runtime.
// In Vitest/jsdom there is no Next.js router, so we spy instead of letting it throw.
vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  redirect: vi.fn(),
}));

// ─── Static imports (resolved after mocks) ───────────────────────────────────

import React from "react";
import * as Sentry from "@sentry/nextjs";
import { notFound } from "next/navigation";
import { GlobalErrorFallback } from "@/components/sentry/GlobalErrorFallback";
import SentryTestPage from "@/app/(app)/dev-tools/sentry-test/page";

// ─── Test infrastructure ─────────────────────────────────────────────────────

// Suppress React's caught-error console.error output (expected in these tests).
let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  mockCaptureException.mockClear();
  vi.mocked(notFound).mockClear();
});
afterEach(() => {
  consoleErrorSpy.mockRestore();
});

// Thin wrapper that mirrors how providers.tsx wires the boundary.
// WHY NOT use the full <Providers>: Providers needs QueryClient, NuqsAdapter,
// AuthProvider, AlertStreamProvider — each with their own deps and mocks.
// We only need to verify ErrorBoundary catches errors and renders GlobalErrorFallback;
// the provider stack is irrelevant to that assertion.
function BoundaryWrapper({ children }: { children: React.ReactNode }) {
  return (
    // Sentry.ErrorBoundary here resolves to MockErrorBoundary
    <Sentry.ErrorBoundary fallback={<GlobalErrorFallback />}>
      {children}
    </Sentry.ErrorBoundary>
  );
}

// A child that conditionally throws during render — simulates a crash.
function MaybeThrow({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("simulated render crash");
  return <div data-testid="child-ok">rendered fine</div>;
}

// ─── Test: GlobalErrorFallback renders correctly ──────────────────────────────

describe("GlobalErrorFallback", () => {
  it("renders the error message and a Reload button", () => {
    // WHY role="alert": the fallback must announce itself to screen readers
    // immediately when it mounts — WCAG 2.1 requirement for dynamic content.
    render(<GlobalErrorFallback />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/something went wrong.*the error has been reported/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  });

  it("calls window.location.reload when the Reload button is clicked", () => {
    // A broken Reload button would leave Sam stuck on the error screen.
    const reloadMock = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { reload: reloadMock },
    });

    render(<GlobalErrorFallback />);
    fireEvent.click(screen.getByRole("button", { name: /reload/i }));

    expect(reloadMock).toHaveBeenCalledOnce();
  });
});

// ─── Test: ErrorBoundary catches render errors ────────────────────────────────

describe("Sentry.ErrorBoundary", () => {
  it("renders the fallback when a child throws", () => {
    // Crash in a child → Sentry.ErrorBoundary catches it → GlobalErrorFallback shown.
    render(
      <BoundaryWrapper>
        <MaybeThrow shouldThrow />
      </BoundaryWrapper>,
    );

    // Fallback must be visible
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
    // Broken child must NOT be in the DOM
    expect(screen.queryByTestId("child-ok")).not.toBeInTheDocument();
  });

  it("calls Sentry.captureException with the thrown error", () => {
    // The primary purpose of the boundary is error capture — without this,
    // Sam sees the fallback but we have no signal to investigate the crash.
    render(
      <BoundaryWrapper>
        <MaybeThrow shouldThrow />
      </BoundaryWrapper>,
    );

    // componentDidCatch must have fired the captureException spy
    expect(mockCaptureException).toHaveBeenCalledOnce();

    const captured = mockCaptureException.mock.calls[0]?.[0] as Error | undefined;
    expect(captured).toBeInstanceOf(Error);
    expect(captured?.message).toBe("simulated render crash");
  });

  it("renders children normally when no error is thrown", () => {
    // Happy path: no fallback, no captureException.
    render(
      <BoundaryWrapper>
        <MaybeThrow shouldThrow={false} />
      </BoundaryWrapper>,
    );

    expect(screen.getByTestId("child-ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mockCaptureException).not.toHaveBeenCalled();
  });
});

// ─── Test: dev-tools/sentry-test page 404s in production ─────────────────────

describe("sentry-test dev route", () => {
  it("calls notFound() when NODE_ENV is production", () => {
    // WHY: the route must be inaccessible in production.
    // In the client component, `process.env.NODE_ENV` is evaluated at runtime
    // in Vitest (unlike the Next.js bundle where it is replaced at build time).
    // Overriding it here triggers the notFound() call during render.
    const originalEnv = process.env.NODE_ENV;
    // @ts-expect-error — NODE_ENV is typed readonly; override is intentional for this test
    process.env.NODE_ENV = "production";

    try {
      render(<SentryTestPage />);
      // notFound() must have been called — the mocked version doesn't throw
      // so render completes, and we can assert on the spy.
      expect(notFound).toHaveBeenCalled();
    } finally {
      // Restore — other tests must see the original value
      // @ts-expect-error — same readonly override as above
      process.env.NODE_ENV = originalEnv;
    }
  });
});
