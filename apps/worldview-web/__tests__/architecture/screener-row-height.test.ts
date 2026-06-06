/**
 * __tests__/architecture/screener-row-height.test.ts
 * (PRD-0089 Wave I-A · Block D · T-IA-14)
 *
 * WHY THIS EXISTS:
 *   The screener is the ONE platform surface that uses 20px AG-Grid rows
 *   (per the Terminal-Dark density spec). Other surfaces use 22 or 24.
 *   A regression that bumps the screener back to 22 silently drops it
 *   below the "≥240 cells above the fold at 1440×900" acceptance gate.
 *
 *   The portfolio components already have a parallel guard
 *   (`no-off-palette-colors.test.ts` § "rowHeight=22 regression guard").
 *   This file extends the same idea to the screener scope so a single
 *   ag-grid prop change in either folder fails CI with a precise error.
 *
 * SCOPE:
 *   components/screener/**
 *   app/(app)/screener/**
 *
 * FORBIDDEN PATTERN:
 *   `rowHeight: 22`, `rowHeight={22}`, `rowHeight=22` — matches all three
 *   common JSX / object-literal / attribute syntaxes used in this repo.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// The two roots that ship the screener UI. The portfolio guard lives in
// the existing palette test; this file is screener-only by design.
const SCAN_ROOTS = ["components/screener", "app/(app)/screener"];

function walk(dir: string, out: string[] = []): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    // Root missing on some commits — return what we have.
    return out;
  }
  for (const entry of entries) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) {
      // Skip node_modules / .next for cheap walks (we never hit them under
      // the scoped roots, but guard anyway in case of symlinks).
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

// WHY this exact regex: matches the three real JSX / TS patterns the
// codebase uses for AG-Grid props:
//   rowHeight=22         (rare — only seen in older code)
//   rowHeight={22}       (canonical JSX prop)
//   rowHeight: 22        (object-literal in AG-Grid config)
// The \b on the trailing side prevents `rowHeight=220` etc. false-positives.
const FORBIDDEN = /rowHeight\s*[=:{]\s*\{?\s*22\s*\}?\b/;

function stripComments(content: string): string {
  // Same comment stripper used by the palette test — preserves newlines
  // so any reported line number maps back to the offending source.
  let s = content;
  s = s.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
  return s;
}

describe("architecture: PRD-0089 Wave I-A screener row-height guard", () => {
  it("forbids rowHeight=22 inside the screener scope (locks 20px)", () => {
    const offences: { file: string; line: number; text: string }[] = [];
    for (const root of SCAN_ROOTS) {
      const files = walk(root);
      for (const file of files) {
        const raw = readFileSync(file, "utf-8");
        const stripped = stripComments(raw);
        const rawLines = raw.split("\n");
        const strippedLines = stripped.split("\n");
        for (let i = 0; i < strippedLines.length; i++) {
          const codeLine = strippedLines[i] ?? "";
          if (codeLine.trim().length === 0) continue;
          if (FORBIDDEN.test(codeLine)) {
            offences.push({
              file,
              line: i + 1,
              text: (rawLines[i] ?? "").trim(),
            });
          }
        }
      }
    }
    if (offences.length > 0) {
      const detail = offences
        .map((o) => `${o.file}:${o.line}  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} rowHeight=22 regression(s) in the screener scope.\n` +
          `Wave I-A locks the screener AG-Grid rowHeight to 20 (Terminal-Dark density spec).\n` +
          `Revert these or update the test with a deliberate exception:\n` +
          detail,
      );
    }
    expect(offences).toEqual([]);
  });
});
