/**
 * Architecture regression — PLAN-0089 Wave K Q-10 (Block H / T-21).
 *
 * WHY: Q-10 staged the `Citation` → `CitationV2` migration. Legacy `Citation`
 * stays exported (JSDoc `@deprecated` in `types/api.ts`) so pre-Wave-K call
 * sites compile; the atomic rename is deferred to PLAN-0089-K-FU. Without
 * this gate, a NEW PR could quietly re-introduce bare `Citation` imports in
 * Wave-K chat surfaces and resurrect the "NaN%"/`undefined`-key type drift
 * Wave-K fixed.
 *
 * SCOPE: NEW Wave-K code only — `features/chat/**` and `components/chat/**`.
 * `types/api.ts` (the deprecated declaration site) is out of scope.
 *
 * EXCLUSIONS — three legacy renderers scheduled for atomic deletion in
 * Block I / T-22; once deleted the entries become inert (`walk()` skips
 * non-existent paths).
 *
 * DETECTION: regex `/\bCitation\b(?!V2)/` over comment-stripped source
 * (re-uses the `stripComments` pattern from `no-off-palette-colors.test.ts`).
 * Word boundaries skip `CitationV2`/`CitationStrip`/`DedupedCitation`/etc.;
 * comment stripping prevents narrative mentions of "legacy `Citation`" from
 * tripping the gate. Regex over text (not a TS AST parse) — small file set,
 * AST adds ~100ms/file with no precision win here.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SCAN_ROOTS = ["features/chat", "components/chat"];

const ALLOWED_FILES = new Set<string>([
  "features/chat/components/MessageBubble.tsx",
  "features/chat/components/CitationList.tsx",
  "components/chat/CitationBar.tsx",
]);

const FORBIDDEN_CITATION = /\bCitation\b(?!V2)/;

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) out.push(path);
  }
  return out;
}

// Preserve newline positions so reported line numbers stay correct.
function stripComments(content: string): string {
  return content
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
}

function scanFile(file: string, raw: string): { file: string; line: number; text: string }[] {
  const hits: { file: string; line: number; text: string }[] = [];
  const stripped = stripComments(raw).split("\n");
  const rawLines = raw.split("\n");
  for (let i = 0; i < stripped.length; i++) {
    const line = stripped[i] ?? "";
    if (line.trim().length === 0) continue;
    if (FORBIDDEN_CITATION.test(line)) {
      hits.push({ file, line: i + 1, text: (rawLines[i] ?? "").trim() });
    }
  }
  return hits;
}

describe("architecture: no legacy `Citation` in Wave-K chat surfaces (Q-10)", () => {
  it("contains no bare `Citation` (must use `CitationV2`)", () => {
    const offences: { file: string; line: number; text: string }[] = [];
    for (const root of SCAN_ROOTS) {
      for (const file of walk(root)) {
        if (ALLOWED_FILES.has(file)) continue;
        offences.push(...scanFile(file, readFileSync(file, "utf-8")));
      }
    }
    if (offences.length > 0) {
      const detail = offences.map((o) => `${o.file}:${o.line}  ${o.text}`).join("\n");
      throw new Error(
        `Found ${offences.length} legacy \`Citation\` reference(s) — use \`CitationV2\`:\n${detail}`,
      );
    }
    expect(offences).toEqual([]);
  });

  // Self-test: a regex typo (e.g. accidentally allowing all `Citation*`) would
  // make the main assertion pass vacuously. This POC keeps the gate honest.
  it("flags a synthetic bare `Citation` and ignores `CitationV2`", () => {
    const bad = `import { Citation } from "../../types/api";\nconst x: Citation[] = [];\n`;
    const good = `import { CitationV2 } from "../../types/api";\nconst x: CitationV2[] = [];\n`;
    expect(scanFile("synthetic.ts", bad).length).toBeGreaterThan(0);
    expect(scanFile("synthetic.ts", good)).toEqual([]);
  });
});
