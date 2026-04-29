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
import { renderHook, act } from "@testing-library/react";
import { useNewsLinkTarget, getNewsLinkTarget, newsLinkAttrs } from "@/hooks/useNewsLinkTarget";

const KEY = "worldview.prefs.news_link_target";

// jsdom in this project's vitest config doesn't ship a working localStorage
// stub (clear/removeItem/getItem are all absent from the prototype). Polyfill
// a minimal Map-backed Storage so the hook + tests behave like a real browser.
const _store = new Map<string, string>();
const _storage: Storage = {
  get length() {
    return _store.size;
  },
  clear: () => _store.clear(),
  getItem: (k) => _store.get(k) ?? null,
  key: (i) => Array.from(_store.keys())[i] ?? null,
  removeItem: (k) => {
    _store.delete(k);
  },
  setItem: (k, v) => {
    _store.set(k, String(v));
  },
};

beforeEach(() => {
  vi.stubGlobal("localStorage", _storage);
  // window.localStorage in jsdom is a getter; restubbing the global suffices
  // because the hook reads `window.localStorage` which resolves via the same
  // global namespace under jsdom.
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: _storage,
  });
  _store.clear();
});
afterEach(() => {
  _store.clear();
  vi.unstubAllGlobals();
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
