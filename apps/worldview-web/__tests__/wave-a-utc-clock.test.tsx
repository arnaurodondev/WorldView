/**
 * __tests__/wave-a-utc-clock.test.tsx — F-CODE-NEW-004 hydration-mismatch guard.
 *
 * PLAN-0059 W0 fix F-009 (2026-04-30): the original UtcClock fix removed the
 * `useState(() => formatUtcTime(new Date()))` lazy initializer that guarantees
 * an SSR/client mismatch. This test fails if a future refactor reintroduces
 * the pattern.
 */

import { describe, expect, it } from "vitest";
import { render, act } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { UtcClock } from "@/components/shell/UtcClock";
import { readFileSync } from "fs";
import { resolve } from "path";

describe("F-CODE-NEW-004 — UtcClock hydration safety", () => {
  it("source uses empty-string SSR + useEffect populate (no lazy initializer)", () => {
    let src = readFileSync(
      resolve(__dirname, "../components/shell/UtcClock.tsx"),
      "utf8",
    );
    // Strip block comments and line comments so the BP-pattern reference in
    // the file's own jsdoc doesn't trigger a false positive on `not.toMatch`.
    src = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    // Forbid the bad pattern (in real code, not in comments)
    expect(src).not.toMatch(/useState[^(]*\(\s*\(\)\s*=>\s*formatUtcTime/);
    // Require the safe pattern
    expect(src).toMatch(/useState<string>\(""\)/);
    expect(src).toMatch(/useEffect\(/);
  });

  it("SSR render produces an empty span (no clock value, no hydration mismatch)", () => {
    // PLAN-0059 W1 fix (2026-04-30): the previous version used RTL's render()
    // which flushes useEffect synchronously, so the post-mount populated state
    // was visible immediately and the "empty initial" assertion failed. The
    // intent of this test is to prove that DURING SSR (before any effect runs)
    // the span renders empty — that's the contract that prevents hydration
    // mismatch. renderToString runs only the initial render, no effects.
    const html = renderToString(<UtcClock />);
    // The span exists, has the expected classes, and is empty between the tags.
    expect(html).toMatch(/<span[^>]*>\s*<\/span>/);
    // Also assert the canonical class shape (font-mono + tabular-nums + min-w)
    // so future refactors don't accidentally lose the layout-stable container.
    expect(html).toMatch(/min-w-\[80px\]/);
    expect(html).toMatch(/font-mono/);
    expect(html).toMatch(/tabular-nums/);
  });

  it("client-side render populates the span after mount via useEffect", () => {
    // Companion to the SSR test above — proves the effect actually runs on
    // the client. RTL's render() flushes useEffect, so by the time we read
    // textContent the effect has populated it with HH:MM:SS UTC.
    const { container } = render(<UtcClock />);
    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    return act(async () => {
      await new Promise((r) => setTimeout(r, 50));
      expect(span?.textContent).toMatch(/^\d{2}:\d{2}:\d{2} UTC$/);
    });
  });
});
