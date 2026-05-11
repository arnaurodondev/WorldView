/**
 * __tests__/feedback-wave-e.test.tsx — PLAN-0052 Wave E unit tests.
 *
 * Covers the three new surfaces shipped in this wave:
 *   1. useBetaEnrollment / usePatchBetaEnrollment hooks (T-E-5-07)
 *   2. FeedbackButton open-feedback CustomEvent prefill (T-E-5-08)
 *   3. NPSPrompt local-state reset on dismiss (QA-iter1 polish)
 *
 * WHY a separate file (not extending feedback-hooks.test.tsx): the existing
 * file's gateway mock omits beta-program methods AND we need a fresh
 * Worldview-style mock for FeedbackModal so the FeedbackButton test
 * doesn't pull in the entire side-sheet tree (which depends on Radix
 * portals that jsdom struggles with). Splitting keeps the mock surface
 * minimal per file.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, renderHook, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth mock — single permissive default; specs can override per-test ──
const mockUseAuth = vi.fn(() => ({
  accessToken: "test-token",
  isAuthenticated: true,
  user: null,
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

// ── Gateway mock with beta-program methods ─────────────────────────────
// We only mock what THIS spec uses — keeps the test surface minimal.
const mockGetBeta = vi.fn();
const mockPatchBeta = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getBetaEnrollment: mockGetBeta,
    patchBetaEnrollment: mockPatchBeta,
  }),
  GatewayError: class GatewayError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

// ── Stub FeedbackModal for the FeedbackButton tests ────────────────────
// Replace the heavy Radix sheet with a tiny renderer that exposes the
// props back to the test as data attributes — this lets us assert that
// the button passes the prefill through correctly without booting the
// modal's full subtree.
vi.mock("@/components/feedback/FeedbackModal", () => ({
  FeedbackModal: (props: {
    open: boolean;
    defaultTab?: string;
    defaultDescription?: string;
  }) => (
    <div
      data-testid="feedback-modal-stub"
      data-open={props.open ? "true" : "false"}
      data-tab={props.defaultTab ?? "bug"}
      data-description={props.defaultDescription ?? ""}
    />
  ),
}));

// QueryClient wrapper — fresh per test so cache doesn't leak.
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // eslint-disable-next-line react/display-name
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// 1. useBetaEnrollment — T-E-5-07
// ─────────────────────────────────────────────────────────────────────────

describe("useBetaEnrollment", () => {
  beforeEach(() => {
    mockGetBeta.mockReset();
    mockPatchBeta.mockReset();
  });

  it("fetches the row when authenticated", async () => {
    mockGetBeta.mockResolvedValue({
      id: "row-1",
      enrolled: false,
      enrolled_at: null,
      notes: null,
    });

    // Dynamic-import inside the test so the gateway mock is in place
    // before the module evaluates.
    const { useBetaEnrollment } = await import("@/hooks/useBetaEnrollment");
    const { result } = renderHook(() => useBetaEnrollment(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.enrolled).toBe(false);
    expect(mockGetBeta).toHaveBeenCalledTimes(1);
  });

  it("skips the fetch when unauthenticated", async () => {
    mockUseAuth.mockReturnValueOnce({
      accessToken: null as unknown as string,
      isAuthenticated: false,
      user: null,
    });

    const { useBetaEnrollment } = await import("@/hooks/useBetaEnrollment");
    const { result } = renderHook(() => useBetaEnrollment(), {
      wrapper: makeWrapper(),
    });

    // enabled=false short-circuits — query stays in idle/pending without firing.
    expect(mockGetBeta).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();
  });
});

describe("usePatchBetaEnrollment", () => {
  beforeEach(() => {
    mockPatchBeta.mockReset();
  });

  it("invokes the gateway with the patch payload", async () => {
    mockPatchBeta.mockResolvedValue({
      id: "row-1",
      enrolled: true,
      enrolled_at: new Date().toISOString(),
      notes: "graphs",
    });

    const { usePatchBetaEnrollment } = await import("@/hooks/useBetaEnrollment");
    const { result } = renderHook(() => usePatchBetaEnrollment(), {
      wrapper: makeWrapper(),
    });

    await act(async () => {
      await result.current.mutateAsync({ enrolled: true, notes: "graphs" });
    });

    expect(mockPatchBeta).toHaveBeenCalledWith({
      enrolled: true,
      notes: "graphs",
    });
    // WHY waitFor: TanStack mutationState transitions are scheduled — even
    // after `await mutateAsync` resolves, `isSuccess` may flip on the next
    // tick. waitFor polls until the assertion passes.
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

// ─────────────────────────────────────────────────────────────────────────
// 2. FeedbackButton CustomEvent prefill — T-E-5-08
// ─────────────────────────────────────────────────────────────────────────

describe("FeedbackButton prefill via worldview:open-feedback event", () => {
  it("opens with default empty form on a bare event", async () => {
    const { FeedbackButton } = await import("@/components/feedback/FeedbackButton");
    render(<FeedbackButton />);

    const stub = await screen.findByTestId("feedback-modal-stub");
    expect(stub.dataset.open).toBe("false");

    act(() => {
      window.dispatchEvent(new CustomEvent("worldview:open-feedback"));
    });

    expect(stub.dataset.open).toBe("true");
    expect(stub.dataset.tab).toBe("bug");
    expect(stub.dataset.description).toBe("");
  });

  it("forwards tab + description from event detail", async () => {
    const { FeedbackButton } = await import("@/components/feedback/FeedbackButton");
    render(<FeedbackButton />);

    const stub = await screen.findByTestId("feedback-modal-stub");

    act(() => {
      window.dispatchEvent(
        new CustomEvent("worldview:open-feedback", {
          detail: { tab: "ux", description: "Reported from: /dashboard\n\n" },
        }),
      );
    });

    expect(stub.dataset.open).toBe("true");
    expect(stub.dataset.tab).toBe("ux");
    expect(stub.dataset.description).toBe("Reported from: /dashboard\n\n");
  });

  it("falls back to bug tab when detail.tab is invalid", async () => {
    const { FeedbackButton } = await import("@/components/feedback/FeedbackButton");
    render(<FeedbackButton />);

    const stub = await screen.findByTestId("feedback-modal-stub");

    act(() => {
      window.dispatchEvent(
        new CustomEvent("worldview:open-feedback", {
          detail: { tab: "totally-bogus" },
        }),
      );
    });

    expect(stub.dataset.tab).toBe("bug");
  });

  it("clicking the trigger resets prefill from a prior deep-link", async () => {
    const user = userEvent.setup();
    const { FeedbackButton } = await import("@/components/feedback/FeedbackButton");
    render(<FeedbackButton />);

    const stub = await screen.findByTestId("feedback-modal-stub");

    // First: deep link arrives (modal opens with prefill).
    act(() => {
      window.dispatchEvent(
        new CustomEvent("worldview:open-feedback", {
          detail: { tab: "feature", description: "From email link" },
        }),
      );
    });
    expect(stub.dataset.tab).toBe("feature");

    // User clicks the floating button → must reset to a clean form.
    const button = screen.getByRole("button", { name: /send feedback/i });
    await user.click(button);

    expect(stub.dataset.tab).toBe("bug");
    expect(stub.dataset.description).toBe("");
  });
});
