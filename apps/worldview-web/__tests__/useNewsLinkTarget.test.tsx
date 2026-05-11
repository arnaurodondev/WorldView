/**
 * __tests__/useNewsLinkTarget.test.tsx — news-article tab preference contract.
 *
 * Pins the contract that:
 *   - Default value is "new-tab" (existing-user-safe)
 *   - localStorage write-through persists the choice
 *   - newsLinkAttrs() returns the right target+rel pair
 *   - Cross-tab `storage` event syncs the value
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import {
  useNewsLinkTarget,
  getNewsLinkTarget,
  newsLinkAttrs,
  isSafeNewsUrl,
} from "@/hooks/useNewsLinkTarget";

const KEY = "worldview.prefs.news_link_target";

// vitest.setup.ts globally installs a Map-backed Storage polyfill (see PLAN-0050
// T-F-6-20 setup change). We just clean up the namespaced key between specs.
beforeEach(() => {
  window.localStorage.removeItem(KEY);
});
afterEach(() => {
  window.localStorage.removeItem(KEY);
});

describe("useNewsLinkTarget", () => {
  it("defaults to new-tab when no preference is stored", () => {
    const { result } = renderHook(() => useNewsLinkTarget());
    expect(result.current[0]).toBe("new-tab");
  });

  it("reads the stored preference on mount", () => {
    window.localStorage.setItem(KEY, "same-tab");
    const { result } = renderHook(() => useNewsLinkTarget());
    expect(result.current[0]).toBe("same-tab");
  });

  it("persists the new value through the setter", () => {
    const { result } = renderHook(() => useNewsLinkTarget());
    act(() => {
      result.current[1]("same-tab");
    });
    expect(result.current[0]).toBe("same-tab");
    expect(window.localStorage.getItem(KEY)).toBe("same-tab");
  });

  it("getNewsLinkTarget() returns the up-to-date stored value", () => {
    window.localStorage.setItem(KEY, "same-tab");
    expect(getNewsLinkTarget()).toBe("same-tab");
    window.localStorage.setItem(KEY, "new-tab");
    expect(getNewsLinkTarget()).toBe("new-tab");
  });

  it("newsLinkAttrs() returns the right target+rel pair", () => {
    expect(newsLinkAttrs("new-tab")).toEqual({
      target: "_blank",
      rel: "noopener noreferrer",
    });
    expect(newsLinkAttrs("same-tab")).toEqual({
      target: "_self",
      rel: "noreferrer",
    });
  });

  // F-QA-02 fix coverage: every safe-URL classification path.
  describe("isSafeNewsUrl (F-QA-02)", () => {
    it("accepts http and https absolute URLs", () => {
      expect(isSafeNewsUrl("https://example.com/article")).toBe(true);
      expect(isSafeNewsUrl("http://news.example.com/x?a=1")).toBe(true);
    });

    it("rejects javascript: URLs (XSS attempt)", () => {
      expect(isSafeNewsUrl("javascript:alert(1)")).toBe(false);
    });

    it("rejects data:, file:, vbscript: schemes", () => {
      expect(isSafeNewsUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
      expect(isSafeNewsUrl("file:///etc/passwd")).toBe(false);
      expect(isSafeNewsUrl("vbscript:msgbox")).toBe(false);
    });

    it("rejects relative URLs and malformed input", () => {
      expect(isSafeNewsUrl("/relative/path")).toBe(false);
      expect(isSafeNewsUrl("not a url")).toBe(false);
      expect(isSafeNewsUrl("")).toBe(false);
      expect(isSafeNewsUrl(null)).toBe(false);
      expect(isSafeNewsUrl(undefined)).toBe(false);
    });
  });

  // F-QA-03 fix coverage: same-tab same-instant sync.
  it("syncs same-tab consumers via synthetic storage event (F-QA-03)", async () => {
    // Mount two independent hook instances in the same tab.
    const a = renderHook(() => useNewsLinkTarget());
    const b = renderHook(() => useNewsLinkTarget());
    expect(a.result.current[0]).toBe("new-tab");
    expect(b.result.current[0]).toBe("new-tab");

    act(() => {
      a.result.current[1]("same-tab");
    });

    // The persist() call dispatches a synthetic StorageEvent so b's listener
    // picks up the change without re-mount. waitFor handles React's async
    // commit of b's setValue (the storage handler is sync but React batches
    // the state update into the next tick).
    expect(a.result.current[0]).toBe("same-tab");
    expect(getNewsLinkTarget()).toBe("same-tab");
    await waitFor(() => {
      expect(b.result.current[0]).toBe("same-tab");
    });
  });

  it("syncs across tabs via the storage event", () => {
    const { result } = renderHook(() => useNewsLinkTarget());
    expect(result.current[0]).toBe("new-tab");

    // Simulate another tab writing to localStorage.
    act(() => {
      window.localStorage.setItem(KEY, "same-tab");
      window.dispatchEvent(
        new StorageEvent("storage", { key: KEY, newValue: "same-tab" }),
      );
    });

    expect(result.current[0]).toBe("same-tab");
  });
});
