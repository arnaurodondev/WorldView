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

// PRD-0089 W1 §6.3 — two new forbidden patterns added to the architecture test:
//
// 1. `border-white/[` opacity literals (banned by F1 token rollout).
//    Components must use `border-border-subtle` (or other CSS token) instead.
//    The previous StatusBar used `border-white/[0.06]` which is an opacity-
//    based alias that doesn't respect theme overrides. F1 locked the token.
//    Exception: this test file itself and palette source files.
//
// 2. References to deleted deprecated shell components (TopBarMarquee,
//    MarqueeTickerChip, IndexTicker). Any post-deletion import of these files
//    indicates a stale import site that would cause a build error.
const FORBIDDEN_BORDER_WHITE_OPACITY = /border-white\/\[/;

// WHY string match (not import-path check): the forbidden pattern covers any
// className string that references the banned opacity literal. Import-path
// checks would only catch direct imports, not className strings.
const FORBIDDEN_DEPRECATED_SHELL =
  /\b(TopBarMarquee|MarqueeTickerChip|IndexTicker)\b/;

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
        // HF-10: combined detector — any one of the six checks triggers an
        // offence. Currency and deprecated-shell checks skip the test file
        // itself (which embeds the forbidden patterns to assert the rules).
        const isCurrencyOffence =
          FORBIDDEN_CURRENCY.test(codeLine) &&
          !rel.endsWith("no-off-palette-colors.test.ts");
        // WHY skip test file for border-white check: the test file contains
        // the regex pattern string as a literal — that's not a violation.
        const isBorderWhiteOffence =
          FORBIDDEN_BORDER_WHITE_OPACITY.test(codeLine) &&
          !rel.endsWith("no-off-palette-colors.test.ts");
        // WHY skip test file + deprecated component files themselves:
        // The deleted files won't exist post-W1. During the transition the
        // deprecated files are the source of truth (not violations). Any OTHER
        // file referencing these symbols post-deletion is a violation.
        const isDeprecatedShellOffence =
          FORBIDDEN_DEPRECATED_SHELL.test(codeLine) &&
          !rel.endsWith("no-off-palette-colors.test.ts") &&
          !rel.includes("components/shell/TopBarMarquee") &&
          !rel.includes("components/shell/MarqueeTickerChip") &&
          !rel.includes("components/shell/IndexTicker");
        if (
          FORBIDDEN_HEX.test(codeLine) ||
          FORBIDDEN_TW.test(codeLine) ||
          FORBIDDEN_RADIUS.test(codeLine) ||
          isCurrencyOffence ||
          isBorderWhiteOffence ||
          isDeprecatedShellOffence
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
