/**
 * __tests__/no-disabled-opacity-50.test.ts — Regression guard for F-002
 *
 * WHY THIS EXISTS (PLAN-0059 W0 fix F-002 — 2026-04-30):
 * The blanket `disabled:opacity-50` Tailwind utility halves contrast of
 * disabled UI, yielding ~3.5:1 on `text-foreground` and ~2.7:1 on
 * `text-muted-foreground` — both fail WCAG AA. Wave A added explicit
 * `--disabled-foreground/--disabled-bg/--disabled-border` tokens that
 * desaturate disabled UI but maintain ≥4.5:1 contrast.
 *
 * This regression test fails if any future commit reintroduces
 * `disabled:opacity-50` in `components/` or `app/` source files. The
 * `globals.css` comment-block self-reference is allowed.
 *
 * Plan §T-A-1-05 specified this guard; original Wave A diff omitted it,
 * which is how the codemod reached only `button.tsx` without anyone noticing.
 */

import { describe, expect, it } from "vitest";
import { execSync } from "child_process";
import * as path from "path";

describe("F-002 — no `disabled:opacity-50` regression", () => {
  it("does not appear in any component or page TSX/JSX file", () => {
    // WHY shell out: Vitest's fs.readdirSync scan is slow over hundreds of
    // files; ripgrep / grep walks the tree in milliseconds. We exclude:
    //   - globals.css (comment-block self-reference is intentional)
    //   - this very test file
    //   - any node_modules/.next
    const cwd = path.resolve(__dirname, "..");
    let output = "";
    try {
      // grep returns exit 1 if no matches — `|| true` keeps the build green.
      // We DO want zero matches; if there are any we'll fail below.
      output = execSync(
        `grep -rn "disabled:opacity-50" components/ app/ --include="*.tsx" --include="*.ts" --include="*.jsx" --include="*.js" 2>/dev/null || true`,
        { cwd, encoding: "utf8" },
      );
    } catch (e) {
      // If grep is unavailable, skip the test rather than fail spuriously.
      // (CI image always has grep; local dev on Windows might not.)
      console.warn("grep unavailable; skipping F-002 regression scan");
      return;
    }
    const violations = output
      .split("\n")
      .filter(Boolean)
      // Allow this file itself (references the literal string for the assertion)
      .filter((line) => !line.includes("__tests__/no-disabled-opacity-50.test.ts"))
      // Allow JS/TS comment lines that document the migration. Real className
      // usages are JSX attribute strings, never preceded by `//` or `/*`.
      // The grep output format is `path:line:content` — strip path:line: and
      // check whether the content begins with a comment marker.
      .filter((line) => {
        const colonIdx = line.indexOf(":", line.indexOf(":") + 1);
        if (colonIdx === -1) return true;
        const content = line.slice(colonIdx + 1).trim();
        // Skip JS/TS comment lines (//, /*, *) — they're documentation, not className
        if (content.startsWith("//") || content.startsWith("/*") || content.startsWith("*")) {
          return false;
        }
        return true;
      });

    if (violations.length > 0) {
      const msg =
        `Found ${violations.length} disabled:opacity-50 site(s). ` +
        `Replace with the explicit disabled-* tokens (see globals.css §--disabled-*).\n` +
        violations.join("\n");
      throw new Error(msg);
    }
    expect(violations).toEqual([]);
  });
});
