/**
 * lib/api/__tests__/evidence-article-meta.test.ts
 *
 * useEvidenceArticleMetadata (QA Wave-3 closeout, 2026-06-11) — resolves
 * relation-evidence document_ids → article {title, url} via
 * GET /v1/articles/{document_id}.
 *
 * CONTRACTS UNDER TEST:
 *  1. Happy path  — each unique doc id is fetched once; the returned map keys
 *     resolved ids to their metadata.
 *  2. Dedup       — duplicate ids in the input fire exactly ONE request.
 *  3. 404 path    — a missing article yields NO map entry (named empty state,
 *     not an error) while other ids still resolve.
 *  4. No token    — queries stay disabled; zero fetches.
 *
 * MOCKED: useAccessToken (auth), global fetch (apiFetch's primitive).
 * REAL:   @tanstack/react-query — the dedup/enabled/cache behaviour IS the
 *         thing being tested (same rationale as useHoldingsSeries.test.ts).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";

// ── Auth stub ────────────────────────────────────────────────────────────────
// The hook only consumes useAccessToken — stub it directly. mutable holder so
// the "no token" test can flip it to null.
const tokenHolder = vi.hoisted(() => ({ token: "test-token" as string | null }));
vi.mock("@/lib/api-client", () => ({
  useAccessToken: () => tokenHolder.token,
}));

import { useEvidenceArticleMetadata } from "../intelligence";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeWrapper() {
  // retry: false — the 404 test must settle immediately (hook sets retry: 1).
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // Named function component (not an arrow) — react/display-name lint rule.
  function QueryWrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  }
  return QueryWrapper;
}

/** One fake S9 article-metadata payload for a doc id. */
function articleJson(docId: string) {
  return {
    document_id: docId,
    title: `Title for ${docId}`,
    url: `https://example.com/${docId}`,
    source: "yahoo",
    source_type: "eodhd_ticker_news",
    published_at: "2026-06-10T00:00:00Z",
    word_count: 100,
  };
}

const fetchMock = vi.fn();

beforeEach(() => {
  tokenHolder.token = "test-token";
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

// ── Tests ────────────────────────────────────────────────────────────────────

describe("useEvidenceArticleMetadata", () => {
  it("resolves each unique document id and maps it to metadata", async () => {
    fetchMock.mockImplementation((url: string) => {
      const docId = String(url).split("/").pop() as string;
      return Promise.resolve(
        new Response(JSON.stringify(articleJson(docId)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    const { result } = renderHook(() => useEvidenceArticleMetadata(["doc-a", "doc-b"]), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.size).toBe(2));
    expect(result.current.get("doc-a")?.title).toBe("Title for doc-a");
    expect(result.current.get("doc-b")?.url).toBe("https://example.com/doc-b");
  });

  it("dedupes duplicate document ids into a single request", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(articleJson("doc-a")), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { result } = renderHook(
      () => useEvidenceArticleMetadata(["doc-a", "doc-a", "doc-a"]),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.size).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("omits 404 (tombstoned) documents from the map without erroring", async () => {
    fetchMock.mockImplementation((url: string) => {
      const docId = String(url).split("/").pop() as string;
      if (docId === "doc-missing") {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "not found" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(articleJson(docId)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    const { result } = renderHook(
      () => useEvidenceArticleMetadata(["doc-a", "doc-missing"]),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.size).toBe(1));
    expect(result.current.has("doc-missing")).toBe(false);
    expect(result.current.get("doc-a")?.title).toBe("Title for doc-a");
  });

  it("fires no requests when there is no access token", async () => {
    tokenHolder.token = null;
    const { result } = renderHook(() => useEvidenceArticleMetadata(["doc-a"]), {
      wrapper: makeWrapper(),
    });
    // Give the (disabled) queries a tick to prove they stay idle.
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.size).toBe(0);
  });
});
