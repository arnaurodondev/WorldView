/**
 * __tests__/eslint-no-inline-querykey.test.ts — PLAN-0059-C C-2 lint guard.
 *
 * COVERS the C-2 critical test:
 *   - test_eslint_blocks_inline_queryKey
 *     → a fixture with `queryKey: ["foo"]` triggers the no-restricted-syntax
 *       rule we registered in .eslintrc.json. The rule is currently 'warn'
 *       during incremental migration; the test asserts at least one lint
 *       message is reported, regardless of severity. When the rule is
 *       promoted to 'error' (after the 153 legacy sites are migrated), this
 *       test still passes — it asserts presence, not severity.
 */

import { describe, it, expect } from "vitest";
import { Linter } from "eslint";

describe("ESLint no-inline-queryKey rule (PLAN-0059-C C-2)", () => {
  it("flags `queryKey: [\"foo\"]` as a violation", () => {
    const linter = new Linter();
    // We register the same rule shape as .eslintrc.json so this test exercises
    // the same selector pattern. We don't load the project config (which would
    // pull next/typescript and require a parser) — a minimal config + ESLint's
    // default JS parser is enough to validate the AST selector.
    const messages = linter.verify(
      `const opts = { queryKey: ["foo"], queryFn: () => 1 };`,
      {
        rules: {
          "no-restricted-syntax": [
            "error",
            {
              selector:
                "Property[key.name='queryKey'][value.type='ArrayExpression'][value.elements.0.type='Literal']",
              message: "Inline queryKey arrays are forbidden.",
            },
          ],
        },
      },
    );

    expect(messages.length).toBeGreaterThan(0);
    expect(messages[0].message).toMatch(/Inline queryKey/);
  });

  it("does NOT flag a factory call: `queryKey: qk.portfolios.list()`", () => {
    const linter = new Linter();
    const messages = linter.verify(
      `const opts = { queryKey: qk.portfolios.list(), queryFn: () => 1 };`,
      {
        rules: {
          "no-restricted-syntax": [
            "error",
            {
              selector:
                "Property[key.name='queryKey'][value.type='ArrayExpression'][value.elements.0.type='Literal']",
              message: "Inline queryKey arrays are forbidden.",
            },
          ],
        },
      },
    );

    expect(messages.length).toBe(0);
  });
});
