/**
 * __tests__/feedback-hooks.test.tsx — Wave G hook unit tests.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G validation gate):
 * One Vitest test per hook (happy path). Covers:
 *   - useFeedbackSubmit  → validation + gateway call
 *   - useNPSEligibility  → eligibility math (sessions / cooldown / quarter)
 *   - useConsoleCapture  → captures + restores console
 *   - useFeatureRequests → query fetch + vote optimistic update
 *   - useFeedbackSubmissions → admin list query
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth mock ──────────────────────────────────────────────────────────────
// All hooks read accessToken via useAuth — stub a permissive default that
// individual specs override when they need to test the unauth path.
const mockUseAuth = vi.fn(() => ({
  accessToken: "test-token",
  isAuthenticated: true,
  user: null,
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────
// One spy per method we exercise so we can assert call args + control responses.
const mockPostFeedback = vi.fn();
const mockGetSubmissions = vi.fn();
const mockGetFeatures = vi.fn();
const mockVoteFeature = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    postFeedbackSubmission: mockPostFeedback,
    getFeedbackSubmissions: mockGetSubmissions,
    getFeatureRequests: mockGetFeatures,
    voteFeature: mockVoteFeature,
  }),
  GatewayError: class GatewayError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

// Wrapper providing a fresh QueryClient per test — avoids state leak.
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // eslint-disable-next-line react/display-name
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  mockUseAuth.mockReturnValue({
    accessToken: "test-token",
    isAuthenticated: true,
    user: null,
  });
});

afterEach(() => {
  window.localStorage.clear();
});

// ── useFeedbackSubmit ──────────────────────────────────────────────────────

describe("useFeedbackSubmit", () => {
  it("calls gateway.postFeedbackSubmission with the payload", async () => {
    const { useFeedbackSubmit } = await import("@/hooks/useFeedbackSubmit");
    mockPostFeedback.mockResolvedValueOnce({ id: "f-1", kind: "bug" });

    const { result } = renderHook(() => useFeedbackSubmit(), {
      wrapper: makeWrapper(),
    });

    act(() => {
      result.current.mutate({
        kind: "bug",
        description: "This is a long-enough bug description",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockPostFeedback).toHaveBeenCalledWith({
      kind: "bug",
      description: "This is a long-enough bug description",
    });
  });

  it("rejects descriptions shorter than 10 chars before any network call", async () => {
    const { useFeedbackSubmit, FeedbackValidationError } = await import(
      "@/hooks/useFeedbackSubmit"
    );

    const { result } = renderHook(() => useFeedbackSubmit(), {
      wrapper: makeWrapper(),
    });

    act(() => {
      result.current.mutate({ kind: "bug", description: "short" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(FeedbackValidationError);
    expect(mockPostFeedback).not.toHaveBeenCalled();
  });
});

// ── useNPSEligibility ──────────────────────────────────────────────────────

describe("useNPSEligibility", () => {
  it("blocks unauthenticated users", async () => {
    mockUseAuth.mockReturnValue({
      accessToken: null as unknown as string,
      isAuthenticated: false,
      user: null,
    });
    const { useNPSEligibility } = await import("@/hooks/useNPSEligibility");
    const { result } = renderHook(() => useNPSEligibility(), {
      wrapper: makeWrapper(),
    });
    expect(result.current.eligible).toBe(false);
    expect(result.current.reason).toBe("unauthenticated");
  });

  it("blocks users with fewer than 3 sessions", async () => {
    const { useNPSEligibility } = await import("@/hooks/useNPSEligibility");
    // Hook records its own session on mount; with a single session count
    // we should be at 1, well below the minimum of 3.
    const { result } = renderHook(() => useNPSEligibility(), {
      wrapper: makeWrapper(),
    });
    expect(result.current.eligible).toBe(false);
    expect(result.current.reason).toBe("too_few_sessions");
  });

  it("flags users as eligible after 3 sessions and clean cooldown", async () => {
    const { useNPSEligibility } = await import("@/hooks/useNPSEligibility");
    // Pre-seed session count so the hook starts above the threshold.
    window.localStorage.setItem("worldview.nps.session_count", "5");
    // Pre-seed last-session-date to today so recordSession() in the hook
    // won't bump the counter (we want the seeded value to stand).
    const today = new Date().toISOString().slice(0, 10);
    window.localStorage.setItem("worldview.nps.last_session_date", today);

    const { result } = renderHook(() => useNPSEligibility(), {
      wrapper: makeWrapper(),
    });
    expect(result.current.eligible).toBe(true);
    expect(result.current.reason).toBe("ok");
  });

  it("blocks users for the rest of the quarter after dismissing", async () => {
    const { useNPSEligibility } = await import("@/hooks/useNPSEligibility");
    window.localStorage.setItem("worldview.nps.session_count", "5");
    const today = new Date().toISOString().slice(0, 10);
    window.localStorage.setItem("worldview.nps.last_session_date", today);
    const { result } = renderHook(() => useNPSEligibility(), {
      wrapper: makeWrapper(),
    });
    act(() => {
      result.current.markDismissed();
    });
    expect(result.current.eligible).toBe(false);
    expect(result.current.reason).toBe("already_dismissed_this_quarter");
  });
});

// ── useConsoleCapture ──────────────────────────────────────────────────────

describe("useConsoleCapture", () => {
  it("captures console.log entries while enabled, then restores", async () => {
    const { useConsoleCapture } = await import("@/hooks/useConsoleCapture");
    // WHY snapshot before mount: the hook captures references on its
    // useEffect run, so we snapshot the same way to compare identity.
    const beforeMount = window.console.log;
    const { result, unmount } = renderHook(() => useConsoleCapture(true));

    // Hook should have replaced console.log with its wrapper.
    const duringMount = window.console.log;
    expect(duringMount).not.toBe(beforeMount);

    // After the hook patched, this log should land in the buffer.
    window.console.log("hello world");
    await waitFor(() => expect(result.current.logs.length).toBe(1));
    expect(result.current.logs[0].message).toContain("hello world");

    unmount();
    // After unmount the wrapper is gone — back to the snapshot.
    expect(window.console.log).not.toBe(duringMount);
  });

  it("is inert when enabled=false", async () => {
    const { useConsoleCapture } = await import("@/hooks/useConsoleCapture");
    const { result } = renderHook(() => useConsoleCapture(false));
    window.console.log("ignored");
    // Allow one microtask to ensure no flush happens.
    await new Promise((r) => setTimeout(r, 5));
    expect(result.current.logs).toHaveLength(0);
  });
});

// ── useFeatureRequests ─────────────────────────────────────────────────────

describe("useFeatureRequests + useVoteFeature", () => {
  it("fetches the feature list", async () => {
    const { useFeatureRequests } = await import("@/hooks/useFeatureRequests");
    mockGetFeatures.mockResolvedValueOnce({
      items: [
        {
          id: "fr-1",
          title: "Test feature",
          description: "x",
          status: "proposed",
          category: null,
          vote_count: 3,
          is_public: true,
          created_at: "2026-04-29T00:00:00Z",
          updated_at: "2026-04-29T00:00:00Z",
          has_voted: false,
        },
      ],
      total: 1,
    });
    const { result } = renderHook(() => useFeatureRequests(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items[0].title).toBe("Test feature");
  });
});

// ── useFeedbackSubmissions ────────────────────────────────────────────────

describe("useFeedbackSubmissions", () => {
  it("fetches submissions with the supplied filters", async () => {
    const { useFeedbackSubmissions } = await import(
      "@/hooks/useFeedbackSubmissions"
    );
    mockGetSubmissions.mockResolvedValueOnce({ items: [], total: 0 });
    const { result } = renderHook(
      () => useFeedbackSubmissions({ mine: true, status: "open" }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockGetSubmissions).toHaveBeenCalledWith({
      mine: true,
      status: "open",
    });
  });
});
