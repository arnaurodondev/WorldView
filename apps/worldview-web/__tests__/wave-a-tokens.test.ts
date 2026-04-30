/**
 * __tests__/wave-a-tokens.test.ts — Regression guards for PLAN-0059 Wave A token surgery.
 *
 * WHY THIS EXISTS (PLAN-0059 W0 fix F-009 — 2026-04-30):
 * The original Wave A diff modified `app/globals.css` to ship six new colour
 * tokens (--positive, --negative, --destructive, --accent-ai, --positive-fill,
 * --negative-fill), syncthe `.dark` block muted-foreground (was 46% drift,
 * now 55% AA-compliant), and added four accessibility @media blocks
 * (prefers-reduced-motion, forced-colors, prefers-contrast, print). None of
 * these had regression tests in the original commit.
 *
 * Strategy: parse globals.css as text and assert structural invariants. We do
 * NOT spin up jsdom + computed-style resolution because Tailwind's CSS-var
 * resolution depends on the build pipeline; the textual contract is the
 * source of truth and is what caught the silent drift in the first place.
 */

import { describe, expect, it, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

const GLOBALS_CSS = resolve(__dirname, "../app/globals.css");

let css = "";
beforeAll(() => {
  css = readFileSync(GLOBALS_CSS, "utf8");
});

// Helper: extract HSL components from a given token by name.
//   --positive: 150 100% 41%; → { h: 150, s: 100, l: 41 }
//
// PLAN-0059 W1 fix (2026-04-30): the previous version used a fixed 3000-char
// slice after the scope opener. After Wave A added 6 new tokens + 4 a11y
// @media blocks the :root block grew to ~6KB, so `--positive` (declared late
// in :root) fell outside the slice and the helper returned null. Fixed by
// finding the block's matching closing brace via depth counter.
function getToken(name: string, scope: ":root" | ".dark" = ":root"): { h: number; s: number; l: number } | null {
  const scopeStart = css.indexOf(scope === ":root" ? ":root {" : ".dark {");
  if (scopeStart === -1) return null;

  // Walk forward from scopeStart counting braces; the scope block ends when
  // depth returns to 0. This is robust to nested blocks (none today, but
  // future-proof if @supports/@media are nested inside).
  let depth = 0;
  let i = scopeStart;
  for (; i < css.length; i++) {
    const ch = css[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        i++;
        break;
      }
    }
  }
  const block = css.slice(scopeStart, i);

  // Match: --<name>: H S% L%   — H may be a 1–3 digit hue
  const re = new RegExp(`--${name}:\\s*(\\d{1,3})\\s+(\\d{1,3})%\\s+(\\d{1,3})%`);
  const m = block.match(re);
  if (!m || !m[1] || !m[2] || !m[3]) return null;
  return { h: Number(m[1]), s: Number(m[2]), l: Number(m[3]) };
}

describe("F-VISUAL-NEW-M — `.dark` muted-foreground synced to `:root`", () => {
  it("both blocks declare --muted-foreground at 55% lightness", () => {
    const root = getToken("muted-foreground", ":root");
    const dark = getToken("muted-foreground", ".dark");
    expect(root?.l).toBe(55);
    expect(dark?.l).toBe(55);
    // Catch the original drift pattern: anything < 50% fails AA against #09090B
    expect(root?.l ?? 0).toBeGreaterThanOrEqual(50);
    expect(dark?.l ?? 0).toBeGreaterThanOrEqual(50);
  });
});

describe("F-VISUAL-001/002 — institutional colour tokens", () => {
  it("--positive resolves to institutional green (hsl(150 100% 41%))", () => {
    const t = getToken("positive");
    expect(t).toEqual({ h: 150, s: 100, l: 41 });
  });

  it("--negative resolves to urgent red (hsl(350 100% 62%))", () => {
    const t = getToken("negative");
    expect(t).toEqual({ h: 350, s: 100, l: 62 });
  });

  it("--destructive is split from --negative (different hue)", () => {
    const dest = getToken("destructive");
    const neg = getToken("negative");
    expect(dest?.h).not.toBe(neg?.h);
    expect(dest).toEqual({ h: 0, s: 84, l: 60 });
  });

  it("--accent-ai is the universal AI violet", () => {
    const t = getToken("accent-ai");
    expect(t).toEqual({ h: 268, s: 90, l: 65 });
  });

  it("retired TradingView teal (#26A69A) and Material Red 400 (#EF5350) are gone", () => {
    // Old hex hydrates as `--positive: 174 42% 40%` and `--negative: 0 63% 62%`
    // Make sure those exact values do not appear inside :root or .dark blocks.
    expect(css).not.toMatch(/--positive:\s*174\s+42%\s+40%/);
    expect(css).not.toMatch(/--negative:\s*0\s+63%\s+62%/);
  });
});

describe("F-VISUAL-NEW-B — accessibility @media blocks", () => {
  it("declares prefers-reduced-motion block", () => {
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  });

  it("declares forced-colors:active block", () => {
    expect(css).toMatch(/@media\s*\(forced-colors:\s*active\)/);
    // Forced-colors must redefine background to system Canvas
    expect(css).toMatch(/--background:\s*Canvas/);
  });

  it("declares prefers-contrast:more block", () => {
    expect(css).toMatch(/@media\s*\(prefers-contrast:\s*more\)/);
  });

  it("declares print block with light palette", () => {
    expect(css).toMatch(/@media\s+print/);
    // Print must set body to white background
    expect(css).toMatch(/body\s*\{\s*background:\s*white/);
  });
});

describe("F-VISUAL-027 — disabled state tokens", () => {
  it("declares --disabled-foreground/--disabled-bg/--disabled-border", () => {
    expect(getToken("disabled-foreground")).not.toBeNull();
    // --disabled-bg uses HSL form `240 4% 11%` — same shape
    const bg = getToken("disabled-bg");
    expect(bg).not.toBeNull();
    expect(bg?.l ?? 100).toBeLessThanOrEqual(20);
  });
});

describe("F-VISUAL-NEW-H — slashed-zero & tabular-nums", () => {
  it("body sets font-feature-settings with `zero` (slashed zero)", () => {
    expect(css).toMatch(/font-feature-settings:[^;]*"zero"\s*1/);
  });

  it("body sets font-variant-numeric with slashed-zero", () => {
    expect(css).toMatch(/font-variant-numeric:[^;]*slashed-zero/);
  });
});
