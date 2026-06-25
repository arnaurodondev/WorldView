/**
 * __tests__/top-bar-marquee.test.tsx — DEPRECATED (PRD-0089 W1 §4.10)
 *
 * TopBarMarquee has been replaced by IndexStrip.tsx (static 10-cell strip).
 * This test file is retained as a placeholder to avoid a "missing test" gap
 * in coverage history. The actual IndexStrip tests live at:
 *   __tests__/shell/IndexStrip.test.tsx
 *
 * WHY empty (not deleted): keeping the file lets git blame trace the
 * deprecation history. The file will be git rm'd when the deprecated
 * component files are permanently removed.
 */

import { describe, it } from "vitest";

describe("TopBarMarquee (deprecated — replaced by IndexStrip)", () => {
  it("is superseded by IndexStrip — see __tests__/shell/IndexStrip.test.tsx", () => {
    // No assertions — this test documents the deprecation.
    // IndexStrip tests cover the equivalent behaviour contract.
  });
});
