/**
 * F-008 — Pin `enableEdgeEvents: true` in SigmaContainer settings
 *
 * WHY THIS TEST EXISTS:
 * sigma 3.x defaults `enableEdgeEvents` to false. Without `enableEdgeEvents: true`
 * the enterEdge/leaveEdge sigma events never fire, making edge hover and the
 * edge-click InlineSelectionPanel permanently broken — a silent regression with
 * no visible error in the console.
 *
 * This test reads the EntityGraph.tsx source file and asserts the literal
 * string `enableEdgeEvents: true` is present. That approach is intentional:
 * we cannot render EntityGraph in jsdom (sigma.js requires WebGL), so a
 * source-text pin is the next best contract. If the setting is accidentally
 * removed or renamed, the test catches it immediately in CI.
 *
 * WHY source-text assertion (not a rendered test):
 *   - sigma.js uses a WebGL canvas — jsdom has no WebGL support.
 *   - Mocking SigmaContainer deeply enough to assert on its `settings` prop
 *     would make the test brittle and unreadable.
 *   - The source is stable (the setting lives in one place, one file) and the
 *     assertion is precise enough to catch the regression it guards against.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

describe("F-008 — EntityGraph enableEdgeEvents pin", () => {
  it("EntityGraph.tsx must contain `enableEdgeEvents: true` in its SigmaContainer settings", () => {
    // WHY resolve from project root: the test runner CWD can vary; using an
    // absolute path relative to this test file guarantees correctness.
    const entityGraphPath = resolve(
      __dirname,
      "../../EntityGraph.tsx",
    );
    const source = readFileSync(entityGraphPath, "utf-8");

    expect(source).toContain("enableEdgeEvents: true");
  });
});
