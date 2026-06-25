/**
 * __tests__/active-portfolio-provider-mount.test.ts — source-contract test.
 *
 * WHY (bug 2026-06-10): ActivePortfolioProvider was implemented in W1.1
 * (F-002) but NEVER MOUNTED anywhere in the app tree. Every consumer
 * (PortfolioSwitcher, usePortfolioMetrics, useResolvedPortfolioId) silently
 * received the noop fallback context — the TopBar "All Portfolios ▾" chip
 * looked alive but selecting a portfolio did nothing. No unit test caught it
 * because each test mounts its own provider.
 *
 * This pins the mount the same way query-client-defaults.test.ts pins cache
 * policy: read the providers source and assert the provider is in the tree.
 * Rendering app/providers.tsx in jsdom would drag in Sentry + every context;
 * a source-contract check is the established cheap alternative.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("ActivePortfolioProvider mount (source contract)", () => {
  const source = readFileSync(
    resolve(__dirname, "../app/providers.tsx"),
    "utf-8",
  );

  it("app/providers.tsx imports ActivePortfolioProvider", () => {
    expect(source).toMatch(
      /import\s*\{\s*ActivePortfolioProvider\s*\}\s*from\s*"@\/contexts\/ActivePortfolioContext"/,
    );
  });

  it("app/providers.tsx mounts <ActivePortfolioProvider> around children", () => {
    // Opening AND closing tags must both be present — an import alone (or a
    // self-closing render with no children) would not provide the context to
    // the app tree.
    expect(source).toContain("<ActivePortfolioProvider>");
    expect(source).toContain("</ActivePortfolioProvider>");
  });
});
