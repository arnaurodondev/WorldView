/**
 * __tests__/structured-brief-parity.test.tsx — OBSOLETE after PLAN-0090 T-E-01.
 *
 * WHY THIS FILE IS A SKIP STUB: The original test asserted StructuredBrief
 * parity across 4 surfaces — one of them was the now-deleted
 * `InstrumentBriefPanel`. PRD-0088 replaced that surface with the
 * AiBriefBanner under `components/instrument/brief/`.
 *
 * REPLACEMENT TEST: T-E-02 will cover AiBriefBanner parity with the dashboard,
 * workspace, and chat surfaces.
 *
 * WHY skip rather than delete: per R19 we never delete tests outright.
 */
import { describe, it, expect } from "vitest";

describe.skip("structured-brief-parity (obsolete — see PLAN-0090 T-E-02)", () => {
  it("placeholder", () => {
    expect(true).toBe(true);
  });
});
