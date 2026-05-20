/**
 * __tests__/news-tab-wave-e.test.tsx — OBSOLETE after PLAN-0090 T-E-01.
 *
 * WHY THIS FILE IS A SKIP STUB: The original suite tested the deleted NewsTab
 * component (sentiment / impact pills, time grouping, source filter). The new
 * Intelligence tab renders news via `NewsColumn` under
 * `components/instrument/intelligence/news/`, with a fundamentally different
 * layout (compact rows + sticky filter chips). T-E-02 will provide replacement
 * coverage.
 *
 * WHY skip rather than delete: per R19 we never delete tests outright.
 */
import { describe, it, expect } from "vitest";

describe.skip("news-tab-wave-e (obsolete — see PLAN-0090 T-E-02)", () => {
  it("placeholder", () => {
    expect(true).toBe(true);
  });
});
