/**
 * __tests__/server-component-audit.test.ts — PLAN-0059-G Wave G-4 regression guard
 *
 * WHY THIS TEST EXISTS: After removing "use client" from components verified to
 * be pure Server Components, this test prevents accidental re-introduction of
 * the directive. If a future developer adds a hook or browser API to one of these
 * files, they MUST also remove it from PURE_SERVER_COMPONENTS below — forcing an
 * explicit acknowledgment that the component is no longer a Server Component.
 *
 * HOW IT WORKS: reads each file at test-time and asserts the string '"use client"'
 * is absent. Fast, zero dependencies, zero mocking.
 *
 * PLAN-0059-G WAVE G-4: 4 components converted (175 total audited).
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, it, expect } from "vitest";

// Root of the worldview-web app — resolved relative to this test file.
// __dirname is `apps/worldview-web/__tests__/`.
const APP_ROOT = join(__dirname, "..");

/**
 * Pure Server Components — verified to have NO hooks, browser APIs,
 * or direct event handlers at the time of PLAN-0059-G Wave G-4.
 *
 * If you need to add "use client" back to any file here, remove it from this
 * list and add a comment explaining which hook / API required the promotion.
 */
const PURE_SERVER_COMPONENTS = [
  // ── features/chat ─────────────────────────────────────────────────────────
  // CitationList + MessageBubble were deleted in PLAN-0089 K Block I (T-22) —
  // their Wave-K replacements (CitationStrip / MessageTurn) are Client
  // Components by design (hover state, click handlers). Entries removed
  // because walk() throws ENOENT on missing files.
  // SlashTurnBlock: pure layout wrapper around SlashCommandCard (a Client Component).
  "features/chat/components/SlashTurnBlock.tsx",

  // ── features/dashboard ────────────────────────────────────────────────────
  // WatchlistSummaryStrip: pure data formatting + static JSX, no interactivity.
  "features/dashboard/components/WatchlistSummaryStrip.tsx",
];

describe("Server Component regression guard (PLAN-0059-G Wave G-4)", () => {
  it('pure server components must not have "use client" directive', () => {
    // Check each file in the list
    for (const relPath of PURE_SERVER_COMPONENTS) {
      const absPath = join(APP_ROOT, relPath);
      let content: string;

      try {
        content = readFileSync(absPath, "utf-8");
      } catch {
        // If the file doesn't exist, fail with a clear message rather than
        // a confusing ENOENT — this usually means the file was renamed/moved.
        throw new Error(
          `server-component-audit: file not found — ${absPath}\n` +
            `Update PURE_SERVER_COMPONENTS in __tests__/server-component-audit.test.ts ` +
            `if the file was renamed or deleted.`,
        );
      }

      // The directive must not appear as the actual code directive.
      // We check for the exact quoted form to avoid flagging comments like
      // // WHY no "use client": ...
      // The directive is always on its own line: ^"use client"
      const hasDirective = /^"use client"/.test(content);

      expect(hasDirective, `${relPath} must NOT have "use client" directive`).toBe(false);
    }
  });
});
