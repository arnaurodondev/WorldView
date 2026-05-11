/**
 * __tests__/brief-feedback.test.tsx — BulletFeedback + BriefRating component tests
 * (PLAN-0066 Wave F T-W10-F-03)
 *
 * WHY THESE TESTS:
 * Feedback components post to sensitive endpoints (creating DB rows tied to a brief).
 * These tests verify:
 *   1. ThumbsUp click → fetch called with the correct body (section_idx, bullet_idx,
 *      reaction="helpful", brief_id).
 *   2. 5-star click → fetch called with reaction="5" and the brief_id.
 *
 * WHY MOCK FETCH (not useQuery):
 * BulletFeedback and BriefRating use raw fetch (via postBulletFeedback /
 * postBriefRating from lib/api/briefing.ts) rather than useQuery — they are
 * fire-and-forget mutations, not cache-read queries. We mock globalThis.fetch
 * so we can assert on the request body without network calls.
 *
 * WHY NOT CHECK OPTIMISTIC UPDATE IN TESTS:
 * The optimistic fill (icon changes to filled immediately) is a pure UI side-effect
 * of setSelected() — it fires synchronously before the fetch. Testing it would
 * require waitFor + DOM assertions on class names, which is brittle. The fetch
 * body is the load-bearing contract.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

describe("BulletFeedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // WHY mock fetch: postBulletFeedback calls apiFetch which calls globalThis.fetch.
    // We intercept at fetch level so we don't have to mock the entire lib/api/briefing module.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "feedback-uuid-1", created_at: "2026-05-08T07:00:00Z" }),
    }));
  });

  // Import inside describe to ensure mocks are registered first
  it("test_bullet_thumbs_up_posts_feedback — ThumbsUp click posts correct body", async () => {
    const { BulletFeedback } = await import(
      "@/features/dashboard/components/BulletFeedback"
    );

    render(
      <BulletFeedback
        token="test-token"
        briefId="brief-uuid-abc"
        sectionIdx={1}
        bulletIdx={2}
      />,
    );

    // WHY exact label match: /helpful/i also matches "unhelpful". Use the exact
    // aria-label text to unambiguously select the thumbs-up button.
    const thumbsUp = screen.getByRole("button", { name: "Mark this bullet as helpful" });
    fireEvent.click(thumbsUp);

    // WHY waitFor: the click triggers an async fetch call.
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    // WHY check fetch call arguments: verify the body matches what S8 expects.
    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/briefings/feedback/bullet");
    // WHY JSON.parse: the body is passed as a JSON string by apiFetch.
    const body = JSON.parse(options.body as string);
    expect(body).toEqual({
      brief_id: "brief-uuid-abc",
      section_idx: 1,
      bullet_idx: 2,
      reaction: "helpful",
    });
  });

  it("thumbs down posts reaction=unhelpful", async () => {
    const { BulletFeedback } = await import(
      "@/features/dashboard/components/BulletFeedback"
    );

    render(
      <BulletFeedback
        token="test-token"
        briefId="brief-uuid-abc"
        sectionIdx={0}
        bulletIdx={0}
      />,
    );

    const thumbsDown = screen.getByRole("button", { name: /unhelpful/i });
    fireEvent.click(thumbsDown);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.reaction).toBe("unhelpful");
  });
});

describe("BriefRating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "rating-uuid-1", created_at: "2026-05-08T07:00:00Z" }),
    }));
  });

  it("test_brief_rating_posts_5_stars — clicking 5 stars posts reaction='5'", async () => {
    const { BriefRating } = await import(
      "@/features/dashboard/components/BriefRating"
    );

    render(<BriefRating token="test-token" briefId="brief-uuid-xyz" />);

    // WHY getByLabelText: each star button has aria-label="Rate brief N star(s)"
    const star5 = screen.getByRole("button", { name: /rate brief 5 star/i });
    fireEvent.click(star5);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/briefings/feedback/brief");
    const body = JSON.parse(options.body as string);
    expect(body).toEqual({
      brief_id: "brief-uuid-xyz",
      reaction: "5",
    });
  });

  it("clicking 3 stars posts reaction='3'", async () => {
    const { BriefRating } = await import(
      "@/features/dashboard/components/BriefRating"
    );

    render(<BriefRating token="test-token" briefId="brief-uuid-xyz" />);

    const star3 = screen.getByRole("button", { name: /rate brief 3 star/i });
    fireEvent.click(star3);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.reaction).toBe("3");
  });
});
