/**
 * Architecture test — PRD-0089 F1 empty-state copy dictionary
 *
 * WHY THIS EXISTS: F1 §3.2 + §16.4 — every empty state in the platform reads
 * its copy from `lib/copy/empty-states.ts` via the `<EmptyState copyKey="X">`
 * primitive.  A typo like `copyKey="portfolio.no_holdings"` (underscore vs
 * hyphen) silently renders the generic fallback in production, which looks
 * fine in development but degrades the institutional polish at runtime.
 *
 * This test scans every .tsx file for `<EmptyState copyKey="..."/>` literal-
 * string usages and asserts each key resolves to an entry in the dictionary.
 *
 * SCOPE: literal-string copyKey only.  Dynamic-expression copyKey values
 * (e.g. `copyKey={someVar}`) are skipped — the TypeScript type
 * `EmptyCopyKey` already guards those at compile time via the EmptyState
 * prop signature.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EMPTY_COPY } from "@/lib/copy/empty-states";

const SCAN_ROOTS = ["app", "components", "lib", "hooks", "features", "contexts"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (entry.endsWith(".tsx")) {
      // Only .tsx — copyKey is a JSX prop, never appears in pure .ts.
      out.push(path);
    }
  }
  return out;
}

// Match `copyKey="some.key"` or `copyKey='some.key'` JSX-prop usages.
// Does NOT match `copyKey={expr}` (dynamic — guarded by TS types).
const COPY_KEY_LITERAL = /\bcopyKey=["']([^"']+)["']/g;

function findUnresolvedKeys(): {
  file: string;
  line: number;
  key: string;
}[] {
  const offences: { file: string; line: number; key: string }[] = [];
  const validKeys = new Set(Object.keys(EMPTY_COPY));

  for (const root of SCAN_ROOTS) {
    let files: string[];
    try {
      files = walk(root);
    } catch {
      continue;
    }
    for (const file of files) {
      const content = readFileSync(file, "utf-8");
      const lines = content.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i] ?? "";
        // Multiple copyKey props on the same line are possible (rare) — use
        // global regex with matchAll.
        for (const match of line.matchAll(COPY_KEY_LITERAL)) {
          const key = match[1];
          if (key && !validKeys.has(key)) {
            offences.push({ file, line: i + 1, key });
          }
        }
      }
    }
  }
  return offences;
}

describe("architecture: PRD-0089 F1 EmptyState copyKey dictionary", () => {
  it("every <EmptyState copyKey=\"X\"> resolves to a key in EMPTY_COPY", () => {
    const offences = findUnresolvedKeys();
    if (offences.length > 0) {
      const detail = offences
        .map((o) => `${o.file}:${o.line}  copyKey="${o.key}"  (missing from EMPTY_COPY)`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} unresolved EmptyState copyKey values:\n${detail}\n\n` +
          `Add the missing keys to apps/worldview-web/lib/copy/empty-states.ts.`,
      );
    }
    expect(offences).toEqual([]);
  });

  it("EMPTY_COPY contains the 6 generic canonical conditions", () => {
    // FU-10.11: every condition catalogued in the plan must remain exported,
    // even if currently unused — they are the contract per-page agents extend.
    const required = [
      "generic.loading",
      "generic.empty-cold-start",
      "generic.empty-no-data",
      "generic.error",
      "generic.permission",
      "generic.coming-soon",
    ];
    for (const key of required) {
      expect(EMPTY_COPY).toHaveProperty(key);
    }
  });
});
