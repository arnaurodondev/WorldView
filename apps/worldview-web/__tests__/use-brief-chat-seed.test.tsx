/**
 * __tests__/use-brief-chat-seed.test.tsx — useBriefChatSeed hook tests
 * (PLAN-0066 Wave F T-W10-F-02)
 *
 * WHY THESE TESTS:
 * The "Discuss in Chat" flow is a navigation-critical path: clicking the button
 * must POST to S8 and then navigate to /chat?thread={id}. If either step breaks,
 * the button appears to do nothing. These tests verify:
 *   1. Successful POST → router.push called with the correct /chat?thread= URL.
 *   2. Failed POST → error state set, no navigation.
 *
 * WHY MOCK next/navigation:
 * useRouter() from next/navigation requires the Next.js App Router context.
 * jsdom doesn't mount the App Router, so we mock the module and assert on
 * the mock function calls.
 *
 * WHY MOCK fetch:
 * postDiscussBrief calls apiFetch which calls globalThis.fetch. We stub fetch
 * to return a controlled response without real network calls.
 *
 * WHY renderHook:
 * useBriefChatSeed is a custom hook that can't be rendered as a component.
 * renderHook from @testing-library/react provides a React tree wrapper so
 * useState and useCallback work correctly.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();

// WHY mock next/navigation at module level: the mock must be registered before
// the hook module is imported (dynamic import won't work here because the module
// is already cached after the first test import).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useBriefChatSeed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("test_discuss_button_navigates_to_chat — successful POST triggers router.push", async () => {
    // WHY stub fetch here (not in beforeEach): this test verifies the success path.
    // The fetch mock returns a thread_id so we can assert the router.push URL.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        thread_id: "thread-uuid-123",
        seeded_with_brief_id: "brief-uuid-abc",
      }),
    }));

    const { useBriefChatSeed } = await import(
      "@/features/dashboard/hooks/useBriefChatSeed"
    );

    const { result } = renderHook(() => useBriefChatSeed("test-token"));

    // Call discuss() inside act() so React processes all state updates
    await act(async () => {
      await result.current.discuss();
    });

    // WHY check router.push: navigation is the success signal for this feature.
    // If push() isn't called, the user stays on the dashboard with no feedback.
    expect(mockPush).toHaveBeenCalledTimes(1);
    expect(mockPush).toHaveBeenCalledWith("/chat?thread=thread-uuid-123");

    // WHY check loading=false: loading must clear after success so the button
    // re-enables for future clicks (e.g. user navigates back and clicks again).
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("failed POST sets error and does NOT navigate", async () => {
    // WHY simulate a 422 failure: the most common real failure is "no brief available"
    // which S8 returns as 422. The user should see an error, not a blank navigation.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "No morning brief available to seed chat" }),
    }));

    const { useBriefChatSeed } = await import(
      "@/features/dashboard/hooks/useBriefChatSeed"
    );

    const { result } = renderHook(() => useBriefChatSeed("test-token"));

    await act(async () => {
      await result.current.discuss();
    });

    // WHY check no navigation: a failed POST must not navigate. The trader
    // should stay on the dashboard and see the error.
    expect(mockPush).not.toHaveBeenCalled();

    // WHY check error message: the trader needs a human-readable cue.
    expect(result.current.error).toBe("Could not open chat — please try again");
    expect(result.current.loading).toBe(false);
  });
});
