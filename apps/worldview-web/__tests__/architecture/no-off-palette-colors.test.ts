/**
 * Architecture regression test — PLAN-0087 D-F3-001/002 Terminal Dark token
 * sweep. Locks in that no source file under app/, components/, lib/, hooks/,
 * features/, or contexts/ uses retired Bloomberg-Dark / Midnight-Pro palette
 * hex codes inline OR off-palette Tailwind shorthand colour classes.
 *
 * WHY this exists: D-F3-001/002 fixed 19 inline-style hex sites and 22 off-
 * palette Tailwind shorthand sites. Without a regression test, an analyst-
 * ready PR could re-introduce them through copy-paste from older code or
 * design references. This test runs in CI and fails any future drift.
 *
 * SCOPE: scans the four app surface roots only — never node_modules,
 * .next, public/, scripts/. Avoids the architecture-test cost of walking
 * vendor trees.
 *
 * ALLOWLIST: tailwind.config.ts and app/globals.css define the palette and
 * legitimately reference token hex/HSL values; tests legitimately reference
 * the forbidden values to assert the function never returns them. Comments
 * documenting the migration history are intentionally allowed (the regex
 * targets only code-bearing lines, not pure-comment lines).
 *
 * BOUNDARY: this is a tight allowlist on purpose — adding entries should
 * be a deliberate review decision (not a default-allow).
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Roots scanned for the regression — relative to apps/worldview-web/.
const SCAN_ROOTS = ["app", "components", "lib", "hooks", "features", "contexts"];

// Files allowed to keep retired hex values (palette source files + tests +
// chart-library config). Each entry below is a deliberate review decision.
const ALLOWED_FILES = new Set<string>([
  // entity-types.ts holds canonical hex values consumed by sigma WebGL — those
  // are the design tokens for graph rendering; the file is the single source
  // and never references retired Bloomberg-Dark / Midnight-Pro palette.
  "lib/entity-types.ts",
  // OHLCVChart MA200 line — lightweight-charts requires hex literals on
  // series config (cannot resolve CSS variables). The retired #0EA5E9 stays
  // as the canonical MA200 line colour by convention (blue distinguishes
  // from MA50 yellow). When lightweight-charts grows token support this
  // entry should move out of the allowlist.
  "components/instrument/OHLCVChart.tsx",
]);

// Retired Bloomberg-Dark / Midnight-Pro hex codes (must never appear in code).
const FORBIDDEN_HEX = /(#1A2030|#6B7585|#0A0E14|#111820|#E0DDD4|#0EA5E9)\b/i;

// Off-palette Tailwind shorthand colour classes (must use design tokens).
// Prefix bg- / text- / border- / ring- / from- / to- / via- / divide-.
// Excluded by intent: rose-* (no occurrences), pink-* (no occurrences in our
// stack post-fix), gray-* (replaced project-wide), slate-* (replaced).
const FORBIDDEN_TW =
  /\b(text|bg|border|ring|from|to|via|divide)-(amber|green|red|blue|emerald|violet|cyan|orange|purple|zinc|sky|rose|pink|yellow|indigo|slate|gray)-[0-9]/;

// ── Helpers ───────────────────────────────────────────────────────────────

/** Recursively list all .ts/.tsx files under a directory. */
function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) {
      // Skip nested test-fixture or generated dirs cheaply.
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

/**
 * Erase comments from full file content but preserve newline positions so
 * line numbers stay correct in error reports. Handles:
 *   • TS/JS line comments:    `// ...` (replaced with spaces to end of line)
 *   • TS/JS block comments:   `/* ... *​/` (single OR multi line)
 *   • JSX block comments:     `{/* ... *​/}` (single OR multi line)
 *
 * The strategy: replace every comment character with a space, except newlines
 * which we keep so the line number of any remaining offence is unchanged.
 * This is far more robust than per-line stripping for multi-line comments.
 *
 * NOTE: does not handle strings that look like comments. False positives on
 * weird quoting are rare; if they arise, prefer adding the file to the
 * allowlist over weakening the regex.
 */
function stripComments(content: string): string {
  let s = content;
  // 1. Replace JSX block comments `{/* ... */}` (single or multi line).
  //    Preserve newlines inside the comment to keep line numbers stable.
  s = s.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, (m) =>
    m.replace(/[^\n]/g, " "),
  );
  // 2. Replace remaining block comments `/* ... */` (single or multi line).
  s = s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  // 3. Replace line comments `// ...` to end of line (per-line, preserves \n).
  s = s.replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
  return s;
}

// Collect all source lines that violate either pattern (excluding allowlist).
function findOffences(): { file: string; line: number; text: string }[] {
  const offences: { file: string; line: number; text: string }[] = [];
  for (const root of SCAN_ROOTS) {
    let files: string[];
    try {
      files = walk(root);
    } catch {
      // Root may not exist on some commits — skip silently.
      continue;
    }
    for (const file of files) {
      const rel = file;
      if (ALLOWED_FILES.has(rel)) continue;
      const raw = readFileSync(file, "utf-8");
      const stripped = stripComments(raw);
      const rawLines = raw.split("\n");
      const strippedLines = stripped.split("\n");
      for (let i = 0; i < strippedLines.length; i++) {
        const codeLine = strippedLines[i] ?? "";
        if (codeLine.trim().length === 0) continue;
        if (FORBIDDEN_HEX.test(codeLine) || FORBIDDEN_TW.test(codeLine)) {
          offences.push({
            file: rel,
            line: i + 1,
            // Show the original line in the error so devs see the real text.
            text: (rawLines[i] ?? "").trim(),
          });
        }
      }
    }
  }
  return offences;
}

// ── Test ─────────────────────────────────────────────────────────────────

describe("architecture: no off-palette colors in source", () => {
  it("contains no retired hex codes or off-palette Tailwind shorthand", () => {
    const offences = findOffences();
    if (offences.length > 0) {
      // Print a readable failure so future drift is easy to spot.
      const detail = offences
        .map((o) => `${o.file}:${o.line}  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} off-palette colour offences:\n${detail}`,
      );
    }
    expect(offences).toEqual([]);
  });
});
