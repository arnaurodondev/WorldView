/**
 * vitest.setup.ts — Global test setup
 *
 * WHY THIS EXISTS: Imports @testing-library/jest-dom which extends Vitest's
 * expect() with DOM-specific matchers like toBeInTheDocument(), toHaveValue(),
 * toBeVisible(), etc. Without this, React Testing Library tests would need to
 * use lower-level querySelector() checks which are more brittle.
 *
 * WHY scrollIntoView mock: jsdom (the DOM simulation used by Vitest) does not
 * implement layout APIs like scrollIntoView() — it throws "not a function".
 * Components that call el.scrollIntoView() for UX polish (auto-scroll to bottom
 * of message list) would break all tests in the file. The mock is a no-op that
 * satisfies jsdom without any side effects.
 */
import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView — stub it globally as a no-op
if (typeof window !== "undefined") {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}

// WHY ResizeObserver stub: jsdom does not implement ResizeObserver (a browser
// layout API). OHLCVChart uses ResizeObserver to resize the chart when the
// container changes. The stub is a no-op class that satisfies the constructor
// call without triggering layout operations.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// PLAN-0050 T-F-6-20: jsdom's `localStorage` shim in this project's vitest
// config does not expose getItem/setItem/clear on the prototype — every
// test that calls a hook backed by localStorage explodes with
// "X is not a function". Install a minimal Map-backed Storage on both
// `window.localStorage` and the global so every test sees a working
// implementation. Reset the contents in vitest's beforeEach below.
if (typeof window !== "undefined") {
  const storeMap = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return storeMap.size;
    },
    clear() {
      storeMap.clear();
    },
    getItem(k) {
      return storeMap.get(k) ?? null;
    },
    key(i) {
      return Array.from(storeMap.keys())[i] ?? null;
    },
    removeItem(k) {
      storeMap.delete(k);
    },
    setItem(k, v) {
      storeMap.set(k, String(v));
    },
  };
  // Some specs explicitly Object.defineProperty(window, "localStorage", ...)
  // — keep our shim configurable so they can replace it without erroring.
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
  // Also expose on the bare `globalThis` so non-DOM module code that calls
  // `localStorage` directly (no `window.` prefix) sees the same store.
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: storage,
  });
}
