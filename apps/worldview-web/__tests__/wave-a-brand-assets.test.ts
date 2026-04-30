/**
 * __tests__/wave-a-brand-assets.test.ts — F-VISUAL-NEW-C / fix F-004 regression guard.
 *
 * WHY THIS EXISTS (PLAN-0059 W0 fix F-009 — 2026-04-30):
 * The brand identity package was 30% complete in the original Wave A diff
 * (only SVG icons + manifest shipped; rasters + OG/Twitter cards absent).
 * Wave A-completion patch fills the gap. This test guards against future
 * regressions where the asset-generation script breaks silently or assets
 * get deleted from `public/`.
 */

import { describe, expect, it } from "vitest";
import { existsSync, statSync, readFileSync } from "fs";
import { resolve } from "path";

const ROOT = resolve(__dirname, "..");

describe("F-VISUAL-NEW-C — brand identity package present", () => {
  const required = [
    "public/icon-16.png",
    "public/icon-32.png",
    "public/icon-180.png",
    "public/icon-192.png",
    "public/icon-512.png",
    "public/favicon.ico",
    "public/og-image.png",
    "public/og-image-square.png",
    "public/twitter-card.png",
    "app/icon.svg",
    "app/apple-icon.svg",
    "app/manifest.webmanifest",
  ];

  for (const rel of required) {
    it(`${rel} exists and is non-empty`, () => {
      const abs = resolve(ROOT, rel);
      expect(existsSync(abs), `${rel} is missing`).toBe(true);
      expect(statSync(abs).size).toBeGreaterThan(0);
    });
  }
});

describe("F-VISUAL-NEW-C — manifest.webmanifest contract", () => {
  it("declares brand-yellow theme_color and PWA-required raster icons", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(ROOT, "app/manifest.webmanifest"), "utf8"),
    ) as {
      theme_color?: string;
      icons?: Array<{ src: string; sizes?: string; type?: string; purpose?: string }>;
    };
    expect(manifest.theme_color).toBe("#FFD60A");
    // PWA install prompt requires at least one PNG ≥192px
    const has192 = manifest.icons?.some(
      (i) => i.type === "image/png" && (i.sizes ?? "").includes("192"),
    );
    expect(has192, "manifest must include a 192x192 PNG icon for PWA install").toBe(true);
  });
});

describe("F-VISUAL-NEW-C — layout.tsx wires OG + Twitter image arrays", () => {
  it("layout.tsx metadata.openGraph.images is set", () => {
    const layoutSrc = readFileSync(resolve(ROOT, "app/layout.tsx"), "utf8");
    expect(layoutSrc).toMatch(/openGraph:[\s\S]*?images:\s*\[/);
    expect(layoutSrc).toContain("/og-image.png");
  });

  it("layout.tsx metadata.twitter.images is set", () => {
    const layoutSrc = readFileSync(resolve(ROOT, "app/layout.tsx"), "utf8");
    expect(layoutSrc).toMatch(/twitter:[\s\S]*?images:\s*\[/);
    expect(layoutSrc).toContain("/twitter-card.png");
  });
});

describe("F-VISUAL-NEW-C — icon.svg has dark/light media query", () => {
  it("icon.svg includes prefers-color-scheme: light variant", () => {
    const svg = readFileSync(resolve(ROOT, "app/icon.svg"), "utf8");
    expect(svg).toContain("prefers-color-scheme: light");
  });
});
