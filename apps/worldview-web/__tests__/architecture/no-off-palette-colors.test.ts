/**
 * Architecture regression test — PLAN-0087 D-F3-001/002 Terminal Dark token
 * sweep, extended in pass-2 HF-10 to also catch off-token corner radii and
 * unformatted currency literals.
 *
 * Locks in that no source file under app/, components/, lib/, hooks/,
 * features/, or contexts/ uses:
 *   1. Retired Bloomberg-Dark / Midnight-Pro palette hex codes (D-F3-001).
 *   2. Off-palette Tailwind shorthand colour classes (D-F3-002).
 *   3. Non-2px explicit `rounded-[Npx]` radii ≥ 3px (HF-10 1F).
 *      Sub-2px micro-indicators (rounded-[1px]) are allowed for sparkline
 *      bars and progress dots; 2px is the canonical token; ≥ 3px is drift.
 *   4. Hand-built currency literals `$${value.toFixed(N)}` (HF-10 1A).
 *      All visible USD must go through formatPrice / formatCompactCurrency
 *      which apply locale grouping ("$4,892.11" not "$4892.11").
 *
 * WHY this exists: D-F3-001/002 fixed 19 inline-style hex sites and 22 off-
 * palette Tailwind shorthand sites; HF-10 fixed 17 currency sites and 4
 * radius sites. Without a regression test, an analyst-ready PR could re-
 * introduce them through copy-paste from older code or design references.
 * This test runs in CI and fails any future drift.
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
  // createChartSeries MA200 line — lightweight-charts requires hex literals on
  // series config (cannot resolve CSS variables). The retired #0EA5E9 stays
  // as the canonical MA200 line colour by convention (blue distinguishes
  // from MA50 yellow). When lightweight-charts grows token support this
  // entry should move out of the allowlist.
  "components/instrument/chart/createChartSeries.ts",
]);

// Retired Bloomberg-Dark / Midnight-Pro hex codes (must never appear in code).
const FORBIDDEN_HEX = /(#1A2030|#6B7585|#0A0E14|#111820|#E0DDD4|#0EA5E9)\b/i;

// Off-palette Tailwind shorthand colour classes (must use design tokens).
// Prefix bg- / text- / border- / ring- / from- / to- / via- / divide-.
// Excluded by intent: rose-* (no occurrences), pink-* (no occurrences in our
// stack post-fix), gray-* (replaced project-wide), slate-* (replaced).
const FORBIDDEN_TW =
  /\b(text|bg|border|ring|from|to|via|divide)-(amber|green|red|blue|emerald|violet|cyan|orange|purple|zinc|sky|rose|pink|yellow|indigo|slate|gray)-[0-9]/;

// HF-10 (1F): non-canonical explicit corner radii. The design system uses
// rounded-[2px] as the single explicit-pixel token; rounded-[1px] is allowed
// for micro-indicators (sparkline bars, 3px progress slivers). Anything 3px
// or larger is drift — the canvas redesign is a sharp 2px terminal aesthetic.
//
// WHY a literal alternation (not a negative-lookahead): Node's RegExp engine
// supports lookaheads, but a literal alternation `\[(3|4|5|6|7|8|9|[1-9][0-9]+)px\]`
// is more transparent in error output and matches engine support across all
// our test runtimes (Vitest + jsdom + node:fs).
const FORBIDDEN_RADIUS = /rounded-\[(?:[3-9]|[1-9][0-9]+)px\]/;

// HF-10 (1A): hand-built USD currency literals — must go through formatPrice
// / formatCompactCurrency for locale grouping. Matches `$${anything.toFixed(`
// in template-literal syntax. Allowing one site per intentional exception via
// the file allowlist below. Note the double-`$` is the literal escape-then-
// interpolation pattern in TS template strings.
const FORBIDDEN_CURRENCY = /\$\$\{[^}]+\.toFixed\(/;

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
        // HF-10: combined detector — any one of the four checks triggers an
        // offence. Currency check skips the test file itself (which embeds
        // the forbidden pattern in regex string form to assert the rule).
        const isCurrencyOffence =
          FORBIDDEN_CURRENCY.test(codeLine) &&
          !rel.endsWith("no-off-palette-colors.test.ts");
        if (
          FORBIDDEN_HEX.test(codeLine) ||
          FORBIDDEN_TW.test(codeLine) ||
          FORBIDDEN_RADIUS.test(codeLine) ||
          isCurrencyOffence
        ) {
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

describe("architecture: no off-palette colors / radii / currency in source", () => {
  it("contains no retired hex codes, off-palette Tailwind, off-token radii, or hand-built currency", () => {
    const offences = findOffences();
    if (offences.length > 0) {
      // Print a readable failure so future drift is easy to spot.
      const detail = offences
        .map((o) => `${o.file}:${o.line}  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} architecture offences (palette / radius / currency):\n${detail}`,
      );
    }
    expect(offences).toEqual([]);
  });
});

// ────────────────────────────────────────────────────────────────────────
// PRD-0089 F1 — Bloomberg-grade visual contract lockdown
//
// The 8 forbidden patterns below back the terminal-grade design system. They
// land here as `describe.skip()` because the codebase has ~300 violations at
// the start of F1; the migration PRs C → G clean them up mechanically, and
// PR-G removes the `.skip` so the lockdown becomes enforced.
//
// Each constant is exported as documentation: per-page agents can grep for
// the symbol and understand what's off-limits without rereading the plan.
//
// SCOPE — same SCAN_ROOTS as the existing check.
// ────────────────────────────────────────────────────────────────────────

// Pattern 1+2: sharp-corners contract. Any rounded-{sm,md,lg,xl,2xl,3xl} or
// explicit rounded-[Npx] with N>0 is forbidden. `rounded-none` and
// `rounded-full` are allowed (dots, avatars).
const F1_FORBIDDEN_ROUNDED = /\brounded-(?:sm|md|lg|xl|2xl|3xl)\b/;
// Note: existing FORBIDDEN_RADIUS already covers rounded-[Npx] for N≥3.
// Sub-2px micro-indicators (rounded-[1px]) intentionally allowed.

// Pattern 3: typography ceiling. Body 11px max in narrative; 14px hero only.
// `text-sm` (14px) and `text-base` (16px) inside data rows are banned;
// `text-lg`+ everywhere are banned (page primaries are 14px even for hero).
// Allowlist will be added after PR-G cleanup measures the surviving ≤10 sites.
const F1_FORBIDDEN_TEXT_SIZE =
  /\btext-(?:sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl)\b/;

// Pattern 4: zero shadows on Terminal Dark.
const F1_FORBIDDEN_SHADOW = /\bshadow-(?:sm|md|lg|xl|2xl|inner)\b/;

// Pattern 5: focus-ring tier mismatch. `ring-2` on a `role="row"` element
// breaks the 3-tier focus contract (table rows must be Tier-1 hairline).
// The regex is intentionally line-local: same-line role="row" with ring-2.
const F1_FORBIDDEN_ROW_RING2 = /\bring-2\b[^"]*role=["']row["']/;

// Pattern 6: ban `transition-all` / `transition-transform` / `transition-shadow`.
// Must use the named tokens `transition-color-only` (Tier-1) or
// `transition-color-and-opacity` (Tier-2) introduced in PR-A's tailwind diff.
const F1_FORBIDDEN_TRANSITION = /\btransition-(?:all|transform|shadow)\b/;

// Pattern 7: Tier-2 ceiling 200ms — anything ≥300ms banned in arbitrary
// utilities. Reserved long durations belong to T3 indicators which use
// keyframes (animate-* utilities), not duration-*.
const F1_FORBIDDEN_DURATION =
  /\bduration-(?:300|500|700|1000)\b/;

// Pattern 8: spacing ceiling 16px (gap-4). Anything larger is consumer-app
// generosity and rejected.
const F1_FORBIDDEN_GAP = /\bgap-(?:6|8|10|12)\b/;

const F1_PATTERNS: Array<{ name: string; pattern: RegExp }> = [
  { name: "rounded-{sm|md|lg|xl|2xl|3xl}", pattern: F1_FORBIDDEN_ROUNDED },
  {
    name: "text-{sm|base|lg|xl|...}",
    pattern: F1_FORBIDDEN_TEXT_SIZE,
  },
  { name: "shadow-{sm|md|lg|xl|2xl|inner}", pattern: F1_FORBIDDEN_SHADOW },
  { name: "ring-2 on role=row", pattern: F1_FORBIDDEN_ROW_RING2 },
  {
    name: "transition-{all|transform|shadow}",
    pattern: F1_FORBIDDEN_TRANSITION,
  },
  { name: "duration-{300|500|700|1000}", pattern: F1_FORBIDDEN_DURATION },
  { name: "gap-{6|8|10|12}", pattern: F1_FORBIDDEN_GAP },
];

// Files explicitly allowed to keep certain patterns (filled in PR-G after
// measuring surviving violations). Format: relative path.
const F1_ALLOWED_FILES = new Set<string>([]);

function findF1Offences(): { pattern: string; file: string; line: number; text: string }[] {
  const offences: { pattern: string; file: string; line: number; text: string }[] = [];
  for (const root of SCAN_ROOTS) {
    let files: string[];
    try {
      files = walk(root);
    } catch {
      continue;
    }
    for (const file of files) {
      const rel = file;
      if (F1_ALLOWED_FILES.has(rel)) continue;
      const raw = readFileSync(file, "utf-8");
      const stripped = stripComments(raw);
      const rawLines = raw.split("\n");
      const strippedLines = stripped.split("\n");
      for (let i = 0; i < strippedLines.length; i++) {
        const codeLine = strippedLines[i] ?? "";
        if (codeLine.trim().length === 0) continue;
        for (const { name, pattern } of F1_PATTERNS) {
          if (pattern.test(codeLine)) {
            offences.push({
              pattern: name,
              file: rel,
              line: i + 1,
              text: (rawLines[i] ?? "").trim(),
            });
          }
        }
      }
    }
  }
  return offences;
}

// F1.1 amendment (2026-05-20): mechanical purges PR-H/I + arch-test additions
// closed every remaining offence — the lockdown is now enforcing.  Any future
// drift (text-sm, shadow-md, gap-6, transition-all, etc.) fails this test in
// CI and must be cleaned up before merge.
describe("PRD-0089 F1 lockdown: terminal-grade visual contract", () => {
  it("has zero violations of the 7 forbidden patterns post-cleanup", () => {
    const offences = findF1Offences();
    if (offences.length > 0) {
      const byPattern = new Map<string, number>();
      for (const o of offences) {
        byPattern.set(o.pattern, (byPattern.get(o.pattern) ?? 0) + 1);
      }
      const summary = [...byPattern.entries()]
        .map(([p, n]) => `  ${p}: ${n}`)
        .join("\n");
      const detail = offences
        .slice(0, 50)
        .map((o) => `${o.file}:${o.line}  [${o.pattern}]  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} F1-lockdown offences:\n${summary}\n\nFirst 50:\n${detail}`,
      );
    }
    expect(offences).toEqual([]);
  });
});

// Export the constants so other tests (animation-policy, data-table-grid-scope)
// can reuse the same regex catalogue.
export {
  F1_ALLOWED_FILES,
  F1_FORBIDDEN_DURATION,
  F1_FORBIDDEN_GAP,
  F1_FORBIDDEN_ROUNDED,
  F1_FORBIDDEN_ROW_RING2,
  F1_FORBIDDEN_SHADOW,
  F1_FORBIDDEN_TEXT_SIZE,
  F1_FORBIDDEN_TRANSITION,
  F1_PATTERNS,
};
