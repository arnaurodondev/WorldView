/**
 * components/instrument/hooks/__tests__/useEntityNewsInfinite.test.ts
 *
 * WHY THIS EXISTS (filter BUG FIX 2026-06-15): the Intelligence-tab news
 * time-range tabs (ALL / TODAY / 3D / 1W) were a visual no-op — they flowed
 * ONLY into the TanStack query key, never into the request, so every
 * "filtered" fetch returned the SAME rows. The fix maps the time-range token
 * to an ISO-8601 `start_date` query param (S6-supported: verified live that
 * start_date narrows the feed). `resolveStartDate` is the pure mapping
 * function at the heart of that fix; testing it in isolation pins the
 * token→bound contract without QueryClient / network plumbing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { resolveStartDate } from "../useEntityNewsInfinite";

describe("resolveStartDate — news time-range → start_date mapping", () => {
  // Pin "now" so the relative bounds are deterministic.
  const NOW = new Date("2026-06-15T12:00:00.000Z").getTime();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns undefined for 'all' (no lower bound — widest backend window)", () => {
    expect(resolveStartDate("all")).toBeUndefined();
  });

  it("returns undefined for an unknown / missing token (fail-open to show all)", () => {
    expect(resolveStartDate(undefined)).toBeUndefined();
    expect(resolveStartDate("bogus")).toBeUndefined();
  });

  it("maps 'day' to now − 24h as ISO-8601 UTC", () => {
    // 2026-06-15T12:00 − 24h = 2026-06-14T12:00.
    expect(resolveStartDate("day")).toBe("2026-06-14T12:00:00.000Z");
  });

  it("maps '3d' to now − 72h", () => {
    expect(resolveStartDate("3d")).toBe("2026-06-12T12:00:00.000Z");
  });

  it("maps '1w' to now − 7 days", () => {
    expect(resolveStartDate("1w")).toBe("2026-06-08T12:00:00.000Z");
  });
});
