/**
 * __tests__/toast-config.test.ts — Toast standardization contract (Round-3 polish).
 *
 * WHY THIS EXISTS: toast behavior must be centralized in the ONE sonner
 * <Toaster> mounted in app/providers.tsx (DESIGN_SYSTEM.md §6.16). The locked
 * configuration is:
 *
 *   - position="top-right"   (FU-10.3 locked decision — above shell chrome)
 *   - visibleToasts={3}      (max 3 visible; older toasts collapse)
 *   - duration: 4000         (auto-dismiss 4s, pinned — not the library default)
 *   - theme="dark" + font-mono text-[11px] tabular-nums (Terminal Dark density)
 *
 * Call sites import { toast } from "sonner" and never re-mount a Toaster or
 * override position. A second Toaster would double-render every toast; a
 * per-call position override would scatter notifications across the screen.
 *
 * WHY a source-contract test (reading files, not rendering): the Toaster's
 * props are not introspectable from the DOM in jsdom without brittle
 * data-attribute spelunking into sonner internals, and rendering the full
 * Providers tree drags in Sentry/Auth/WebSocket providers. Grepping the
 * source is the repo's established pattern for config pins (see
 * no-disabled-opacity-50.test.ts, server-component-audit.test.ts).
 */

import { describe, expect, it } from "vitest";
import { execSync } from "child_process";
import { readFileSync } from "fs";
import * as path from "path";

const APP_ROOT = path.resolve(__dirname, "..");

describe("Toast standardization — single sonner Toaster, locked config", () => {
  it("exactly one <Toaster mount exists, in app/providers.tsx", () => {
    // grep for JSX mounts of <Toaster (sonner). `|| true` keeps grep's exit-1
    // (no matches) from throwing — we assert on the output instead.
    const output = execSync(
      `grep -rln "<Toaster" app/ components/ features/ hooks/ lib/ --include="*.tsx" 2>/dev/null || true`,
      { cwd: APP_ROOT, encoding: "utf8" },
    );
    const files = output.split("\n").filter(Boolean);
    expect(files).toEqual(["app/providers.tsx"]);
  });

  it("providers.tsx pins position=top-right, visibleToasts=3, duration=4000", () => {
    const src = readFileSync(path.join(APP_ROOT, "app/providers.tsx"), "utf8");
    expect(src).toContain('position="top-right"');
    expect(src).toContain("visibleToasts={3}");
    // duration lives inside toastOptions — assert the key/value pair exists.
    expect(src).toMatch(/duration:\s*4000/);
    // Terminal Dark density: mono font + 11px + tabular numerals on every toast.
    expect(src).toContain("font-mono text-[11px] tabular-nums");
    expect(src).toContain('theme="dark"');
  });

  it("no call site overrides toast position (centralized-config rule)", () => {
    // Per-call `position:` options would scatter toasts across the viewport.
    // We scan for the sonner option key in files that import from "sonner".
    // Durations are allowed ONLY in hooks/useConfirmable.tsx (the Undo window
    // is a functional timer, not styling) — checked separately below.
    const output = execSync(
      `grep -rln 'from "sonner"' app/ components/ features/ hooks/ lib/ --include="*.tsx" --include="*.ts" 2>/dev/null || true`,
      { cwd: APP_ROOT, encoding: "utf8" },
    );
    const sonnerFiles = output.split("\n").filter(Boolean);
    const violators: string[] = [];
    for (const file of sonnerFiles) {
      if (file === "app/providers.tsx") continue; // the Toaster mount itself
      const src = readFileSync(path.join(APP_ROOT, file), "utf8");
      // `position:` as a toast() option (string keys in object literals).
      if (/toast[^\n]*\(\s*[\s\S]{0,200}?position\s*:/.test(src)) {
        violators.push(`${file}: per-call position override`);
      }
      // duration overrides — allowed only in useConfirmable (undo window).
      if (file !== "hooks/useConfirmable.tsx" && /duration\s*:/.test(src)) {
        violators.push(`${file}: per-call duration override`);
      }
    }
    expect(violators).toEqual([]);
  });
});
