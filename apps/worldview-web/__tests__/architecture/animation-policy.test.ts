/**
 * Architecture test — PRD-0089 F1 four-tier animation policy
 *
 * WHY THIS EXISTS: F1 §16.2 codifies the only transition utilities that may
 * appear in source: `transition-color-only` (T1, ≤100ms),
 * `transition-color-and-opacity` (T2, ≤200ms), `transition-colors` /
 * `transition-opacity` (Tailwind built-ins compatible with the policy), and
 * `animate-*` keyframes (T3 indicators).  `transition-all`,
 * `transition-transform`, and `transition-shadow` are banned because they
 * either animate layout properties (Tier-0 violation) or animate properties
 * that no longer exist in our token system (shadow → none).
 *
 * Long durations (≥300ms) outside of keyframe `animate-*` utilities also
 * fail — they signal someone reaching for consumer-app polish on top of a
 * terminal aesthetic.
 *
 * SCOPE: walks the same SCAN_ROOTS as no-off-palette-colors and reuses the
 * F1_FORBIDDEN_TRANSITION / F1_FORBIDDEN_DURATION regex constants exported
 * from there to keep a single source of truth for the policy.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  F1_ALLOWED_FILES,
  F1_FORBIDDEN_DURATION,
  F1_FORBIDDEN_TRANSITION,
} from "./no-off-palette-colors.test";

// Same SCAN_ROOTS as no-off-palette-colors — the four app surface roots.
const SCAN_ROOTS = ["app", "components", "lib", "hooks", "features", "contexts"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

// Same comment-stripping logic — keeps line numbers stable but ignores
// historical references in `// WHY transition-[width] not transition-all`
// style comments.
function stripComments(content: string): string {
  let s = content;
  s = s.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
  return s;
}

function findAnimationOffences(): {
  rule: string;
  file: string;
  line: number;
  text: string;
}[] {
  const offences: { rule: string; file: string; line: number; text: string }[] = [];
  for (const root of SCAN_ROOTS) {
    let files: string[];
    try {
      files = walk(root);
    } catch {
      continue;
    }
    for (const file of files) {
      if (F1_ALLOWED_FILES.has(file)) continue;
      const raw = readFileSync(file, "utf-8");
      const stripped = stripComments(raw);
      const rawLines = raw.split("\n");
      const strippedLines = stripped.split("\n");
      for (let i = 0; i < strippedLines.length; i++) {
        const codeLine = strippedLines[i] ?? "";
        if (codeLine.trim().length === 0) continue;
        if (F1_FORBIDDEN_TRANSITION.test(codeLine)) {
          offences.push({
            rule: "transition-{all|transform|shadow}",
            file,
            line: i + 1,
            text: (rawLines[i] ?? "").trim(),
          });
        }
        if (F1_FORBIDDEN_DURATION.test(codeLine)) {
          offences.push({
            rule: "duration-{300|500|700|1000}",
            file,
            line: i + 1,
            text: (rawLines[i] ?? "").trim(),
          });
        }
      }
    }
  }
  return offences;
}

describe("architecture: PRD-0089 F1 animation policy", () => {
  it("contains no banned transition utilities or off-tier durations", () => {
    const offences = findAnimationOffences();
    if (offences.length > 0) {
      const detail = offences
        .slice(0, 50)
        .map((o) => `${o.file}:${o.line}  [${o.rule}]  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} animation-policy offences:\n${detail}`,
      );
    }
    expect(offences).toEqual([]);
  });
});
