/**
 * __tests__/tailwind-content-coverage.test.ts — Tailwind JIT scan coverage guard.
 *
 * WHY THIS EXISTS (2026-06-11, Wave 3 portfolio layout bug): tailwind.config.ts
 * listed `./components/**`, `./app/**`, `./lib/**`, `./hooks/**` — but NOT
 * `./features/**`. Tailwind's JIT compiler only emits CSS for class strings it
 * finds in the `content` globs, so every utility class used EXCLUSIVELY inside
 * features/ silently produced NO CSS:
 *
 *   - features/portfolio/components/HoldingsTab.tsx `xl:grid-cols-3` →
 *     the 3-panel overview band rendered as three STACKED full-width sections
 *     ("huge black spaces" — user screenshot 7).
 *   - features/portfolio/components/AnalyticsTab.tsx `lg:col-span-9` /
 *     `lg:col-span-3` / `md:col-span-6` → the Analytics grid stacked too.
 *
 * The failure mode is invisible to unit tests (jsdom never applies real CSS)
 * and to TypeScript — it only appears as broken layout in a browser. This
 * test closes the gap structurally: it walks the repo for .tsx/.ts files that
 * contain `className` and asserts every such file is matched by at least one
 * content glob. Adding a new top-level UI directory without registering it in
 * tailwind.config.ts fails this test immediately.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import tailwindConfig from "../tailwind.config";

// Directories that never contain rendered JSX (no Tailwind classes possible)
// or are build/tooling artifacts. node_modules/.next are excluded for speed;
// __tests__/e2e are excluded because test-only classNames never need CSS.
const IGNORED_DIRS = new Set([
  "node_modules",
  ".next",
  ".turbo",
  "coverage",
  "dist",
  "build",
  "public",
  "e2e",
  "__tests__",
  "__mocks__",
  "test-results",
  "playwright-report",
  "scripts",
]);

const ROOT = join(__dirname, "..");

/** Recursively collect .ts/.tsx files, skipping ignored + test dirs. */
function collectSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (IGNORED_DIRS.has(entry) || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      collectSourceFiles(full, out);
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.(test|spec)\.(ts|tsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Minimal glob matcher for the config's `"./dir/**\/*.{ts,tsx}"` shape.
 * WHY hand-rolled (not minimatch): the config uses exactly one glob shape;
 * a dependency-free matcher keeps this guard runnable in any environment.
 */
function globMatches(glob: string, relPath: string): boolean {
  // "./features/**/*.{ts,tsx}" → prefix "features/"
  const m = glob.match(/^\.\/([^*]+)\/\*\*\/\*\.\{ts,tsx\}$/);
  if (!m) return false;
  return relPath.startsWith(`${m[1]}/`);
}

describe("tailwind.config content coverage", () => {
  const content = tailwindConfig.content as string[];

  it("explicitly scans ./features/** (regression: portfolio overview band stacked full-width)", () => {
    // Direct pin on the 2026-06-11 fix: the band's `xl:grid-cols-3` lives in
    // features/portfolio/components/HoldingsTab.tsx and is generated ONLY if
    // this glob is present.
    expect(content).toContain("./features/**/*.{ts,tsx}");
  });

  it("every source file using className is matched by a content glob", () => {
    const offenders: string[] = [];
    for (const file of collectSourceFiles(ROOT)) {
      const rel = relative(ROOT, file);
      // Root-level config files (tailwind.config.ts, next.config.ts, …) can
      // mention the WORD "className" in comments without rendering JSX —
      // only files inside a directory can be component sources.
      if (!rel.includes("/")) continue;
      // Only files that can contribute class strings matter.
      const src = readFileSync(file, "utf8");
      if (!src.includes("className")) continue;
      const covered = content.some((g) => globMatches(g, rel));
      if (!covered) offenders.push(rel);
    }
    // Empty offender list = every styled file is JIT-scanned. A failure here
    // means a class used only in the offending file emits NO CSS in the build.
    expect(offenders).toEqual([]);
  });
});
