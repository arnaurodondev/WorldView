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
