/**
 * scripts/generate-brand-assets.mjs — render brand raster assets from SVG.
 *
 * WHY THIS EXISTS (PLAN-0059 W0 fix F-004 — 2026-04-30):
 * Next.js 15 App Router serves SVG icons at /icon.svg + /apple-icon.svg, but
 * the PWA manifest + Twitter share + LinkedIn share + Slack-unfurl all want
 * raster PNGs. This script generates them once at build time from the
 * canonical 16x16 SVG mark, scaled to PWA-compliant sizes.
 *
 * OUTPUTS (in apps/worldview-web/public/):
 *   - icon-16.png, icon-32.png, icon-180.png, icon-192.png, icon-512.png
 *   - favicon.ico (multi-size)
 *   - og-image.png (1200x630, OpenGraph)
 *   - og-image-square.png (1200x1200, Slack/Discord)
 *   - twitter-card.png (1200x600, summary_large_image)
 *
 * RUN: `pnpm exec node scripts/generate-brand-assets.mjs`
 *      (also runs as a `prebuild` hook — see package.json scripts)
 */

import sharp from "sharp";
import { mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const PUBLIC_DIR = join(ROOT, "public");
const ICON_SVG = join(ROOT, "app/icon.svg");

mkdirSync(PUBLIC_DIR, { recursive: true });

// ── 1. Read source SVG ───────────────────────────────────────────────────────
const svgBuffer = readFileSync(ICON_SVG);

// ── 2. Generate raster icons at PWA-required sizes ───────────────────────────
const ICON_SIZES = [16, 32, 180, 192, 512];
for (const size of ICON_SIZES) {
  const outPath = join(PUBLIC_DIR, `icon-${size}.png`);
  await sharp(svgBuffer, { density: Math.max(72, size * 4) })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toFile(outPath);
  console.log(`  ✓ ${outPath}`);
}

// ── 3. favicon.ico ───────────────────────────────────────────────────────────
// sharp doesn't natively write .ico; fall back to a 32x32 PNG renamed.
// Modern browsers accept PNG-in-.ico (RFC-incompatible but universally tolerated).
// For full multi-size .ico, consider `to-ico` package; this 32x32 PNG fallback
// is the lightest path that satisfies bookmark + tab-bar rendering.
const ico32 = await sharp(svgBuffer, { density: 256 })
  .resize(32, 32)
  .png({ compressionLevel: 9 })
  .toBuffer();
writeFileSync(join(PUBLIC_DIR, "favicon.ico"), ico32);
console.log(`  ✓ ${join(PUBLIC_DIR, "favicon.ico")}`);

// ── 4. Open Graph image (1200x630) — for LinkedIn, Slack, Discord ───────────
// Layout: black background + centered yellow wordmark + tagline beneath.
// We compose via SVG overlay (sharp-friendly) instead of fully external assets.
const OG_BG = "#09090B";
const OG_YELLOW = "#FFD60A";
const OG_GRAY = "#83838A";

const ogSvg = (width, height) => Buffer.from(`
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <rect width="${width}" height="${height}" fill="${OG_BG}"/>
  <!-- 4x4 grid mark scaled at upper-left for brand recognition -->
  <g transform="translate(64, 64)">
    <rect width="80" height="80" fill="#27272A"/>
    <rect x="100" width="80" height="80" fill="#27272A"/>
    <rect x="200" width="80" height="80" fill="#27272A"/>
    <rect x="300" width="80" height="80" fill="${OG_YELLOW}"/>
  </g>
  <!-- Wordmark text -->
  <text x="${width / 2}" y="${height / 2}" font-family="-apple-system, BlinkMacSystemFont, 'IBM Plex Sans', sans-serif" font-size="120" font-weight="600" fill="#E4E4E7" text-anchor="middle" dominant-baseline="middle">
    worldview
  </text>
  <!-- Strapline -->
  <text x="${width / 2}" y="${height / 2 + 100}" font-family="-apple-system, BlinkMacSystemFont, 'IBM Plex Sans', sans-serif" font-size="36" font-weight="400" fill="${OG_GRAY}" text-anchor="middle" dominant-baseline="middle">
    Institutional market intelligence
  </text>
  <!-- Bottom-right yellow accent dot for brand consistency -->
  <circle cx="${width - 80}" cy="${height - 80}" r="20" fill="${OG_YELLOW}"/>
</svg>
`);

await sharp(ogSvg(1200, 630)).png({ compressionLevel: 9 }).toFile(join(PUBLIC_DIR, "og-image.png"));
console.log(`  ✓ ${join(PUBLIC_DIR, "og-image.png")}`);

await sharp(ogSvg(1200, 1200)).png({ compressionLevel: 9 }).toFile(join(PUBLIC_DIR, "og-image-square.png"));
console.log(`  ✓ ${join(PUBLIC_DIR, "og-image-square.png")}`);

// ── 5. Twitter summary_large_image (1200x600) ────────────────────────────────
await sharp(ogSvg(1200, 600)).png({ compressionLevel: 9 }).toFile(join(PUBLIC_DIR, "twitter-card.png"));
console.log(`  ✓ ${join(PUBLIC_DIR, "twitter-card.png")}`);

console.log("\nBrand assets generated successfully.");
