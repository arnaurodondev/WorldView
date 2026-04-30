/**
 * __tests__/wave-a-config.test.ts — F-006/F-007/F-005 config regression guard.
 *
 * PLAN-0059 W0 fix F-009 (2026-04-30): asserts that Wave A's config-tightening
 * tasks stay applied. The original diff missed several flags; this test
 * catches a future revert.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

const ROOT = resolve(__dirname, "..");

describe("F-006 — next.config.ts experimental.reactCompiler enabled", () => {
  it("next.config.ts contains `reactCompiler: true`", () => {
    const src = readFileSync(resolve(ROOT, "next.config.ts"), "utf8");
    expect(src).toMatch(/reactCompiler:\s*true/);
  });

  it("next.config.ts has optimizePackageImports for lucide-react + tanstack", () => {
    const src = readFileSync(resolve(ROOT, "next.config.ts"), "utf8");
    expect(src).toContain("lucide-react");
    expect(src).toContain("@tanstack/react-query");
  });

  it("next.config.ts removeConsole keeps console.error and console.warn", () => {
    const src = readFileSync(resolve(ROOT, "next.config.ts"), "utf8");
    // The exclude list MUST contain "error" AND "warn" so security warnings
    // (CSP reports, F-020 AlertStream malformed-frame log) flow to Sentry.
    expect(src).toMatch(/exclude:\s*\[[^\]]*"error"[^\]]*"warn"/);
  });
});

describe("F-007 — tsconfig.json strict + verbatimModuleSyntax", () => {
  it("tsconfig.json has noImplicitOverride + noFallthroughCasesInSwitch + verbatimModuleSyntax", () => {
    const tsconfig = JSON.parse(readFileSync(resolve(ROOT, "tsconfig.json"), "utf8")) as {
      compilerOptions?: Record<string, unknown>;
    };
    const opts = tsconfig.compilerOptions ?? {};
    expect(opts.strict).toBe(true);
    expect(opts.noImplicitOverride).toBe(true);
    expect(opts.noFallthroughCasesInSwitch).toBe(true);
    // The flag the original Wave A diff missed:
    expect(opts.verbatimModuleSyntax).toBe(true);
  });
});

describe("F-005 — CI tooling installed", () => {
  it("package.json devDependencies include depcheck, knip, bundlewatch, @lhci/cli", () => {
    const pkg = JSON.parse(readFileSync(resolve(ROOT, "package.json"), "utf8")) as {
      devDependencies?: Record<string, string>;
    };
    const dev = pkg.devDependencies ?? {};
    expect(dev.depcheck).toBeDefined();
    expect(dev.knip).toBeDefined();
    expect(dev.bundlewatch).toBeDefined();
    expect(dev["@lhci/cli"]).toBeDefined();
  });

  it("CI config files exist (bundlewatch, lighthouse, knip, depcheck)", () => {
    const { existsSync } = require("fs") as typeof import("fs");
    expect(existsSync(resolve(ROOT, "bundlewatch.config.json"))).toBe(true);
    expect(existsSync(resolve(ROOT, ".lighthouserc.json"))).toBe(true);
    expect(existsSync(resolve(ROOT, "knip.json"))).toBe(true);
    expect(existsSync(resolve(ROOT, ".depcheckrc.json"))).toBe(true);
  });

  it("package.json scripts expose ci:depcheck / ci:knip / ci:bundlewatch / ci:lhci", () => {
    const pkg = JSON.parse(readFileSync(resolve(ROOT, "package.json"), "utf8")) as {
      scripts?: Record<string, string>;
    };
    const scripts = pkg.scripts ?? {};
    expect(scripts["ci:depcheck"]).toBeDefined();
    expect(scripts["ci:knip"]).toBeDefined();
    expect(scripts["ci:bundlewatch"]).toBeDefined();
    expect(scripts["ci:lhci"]).toBeDefined();
  });
});

describe("F-001 — ERROR_MESSAGES not exported from app/callback/page.tsx", () => {
  it("app/callback/page.tsx does NOT export ERROR_MESSAGES (Next.js page constraint)", () => {
    const src = readFileSync(resolve(ROOT, "app/callback/page.tsx"), "utf8");
    expect(src).not.toMatch(/^export\s+const\s+ERROR_MESSAGES/m);
  });

  it("app/callback/error-messages.ts is the canonical source", () => {
    const src = readFileSync(resolve(ROOT, "app/callback/error-messages.ts"), "utf8");
    expect(src).toMatch(/export\s+const\s+ERROR_MESSAGES/);
    expect(src).toMatch(/export\s+const\s+ERROR_COPY/);
  });
});
