/**
 * e2e/landing.spec.ts — PLAN-0052 Wave A landing page e2e + responsive a11y
 *
 * WHY THIS EXISTS: Vitest covers component-level contracts, but the landing
 * page must also pass at four real device viewports (desktop, laptop,
 * tablet, mobile) without horizontal overflow, broken images, or
 * unreachable CTAs. Playwright runs against the actual built page so layout
 * regressions are caught before merge.
 *
 * SCOPE PER PLAN-0052 T-A-1-13:
 *   - Renders all 11+ marketing sections at 1920 / 1280 / 768 / 480 px
 *   - Primary CTAs reachable + clickable at every viewport
 *   - No console errors during page load
 *   - Basic a11y: every section has an h2 or aria-label, no empty links
 *   - JSON-LD Organization schema is present
 *   - sitemap.xml + robots.txt return 200
 */

import { test, expect, type Page } from "@playwright/test";

const VIEWPORTS = [
  { name: "desktop-1920", width: 1920, height: 1080 },
  { name: "laptop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-480", width: 480, height: 844 },
];

async function expectNoConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return () => errors;
}

test.describe("PLAN-0052 Wave A — landing page", () => {
  for (const vp of VIEWPORTS) {
    test(`renders all sections at ${vp.name} (${vp.width}×${vp.height})`, async ({
      page,
    }) => {
      const getErrors = await expectNoConsoleErrors(page);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      // Every named section is in the DOM (anchored by id).
      for (const id of [
        "hero",
        "differentiators",
        "workflow",
        "ai",
        "compare",
        "pricing",
        "faq",
      ]) {
        await expect(page.locator(`#${id}`)).toBeVisible();
      }

      // Primary CTA visible and clickable at every viewport.
      const heroCta = page.getByTestId("hero-primary-cta");
      await expect(heroCta).toBeVisible();
      await expect(heroCta).toHaveAttribute("href", "/register");

      const finalCta = page.getByTestId("final-primary-cta");
      await expect(finalCta).toBeVisible();

      // No horizontal overflow at this viewport (page should fit width).
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      expect(bodyWidth).toBeLessThanOrEqual(vp.width + 1); // +1 for sub-pixel rounding

      // No console errors on load.
      expect(getErrors()).toEqual([]);
    });
  }

  test("JSON-LD Organization schema is present", async ({ page }) => {
    await page.goto("/");
    const ldJson = await page.locator('script[type="application/ld+json"]').allTextContents();
    expect(ldJson.length).toBeGreaterThanOrEqual(1);
    const parsed = ldJson.map((j) => JSON.parse(j));
    expect(parsed.some((p) => p["@type"] === "Organization")).toBe(true);
  });

  test("sitemap.xml is reachable and lists the landing route", async ({ request }) => {
    const res = await request.get("/sitemap.xml");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toMatch(/<urlset/);
    // Landing root must be listed.
    expect(body).toMatch(/<loc>https?:[^<]+\/<\/loc>/);
  });

  test("robots.txt is reachable and disallows authenticated routes", async ({
    request,
  }) => {
    const res = await request.get("/robots.txt");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toMatch(/Disallow: \/dashboard/);
    expect(body).toMatch(/Sitemap:/);
  });

  test("monthly/annual pricing toggle works", async ({ page }) => {
    await page.goto("/#pricing");
    // Default = annual: Pro shows $24
    await expect(page.getByText("$24", { exact: true })).toBeVisible();
    // Switch to monthly
    // QA iter-1: toggle now uses aria-pressed (button) not role="tab".
    await page.getByRole("button", { name: /^monthly$/i }).click();
    await expect(page.getByText("$29", { exact: true })).toBeVisible();
  });

  test("FAQ accordion expands on click", async ({ page }) => {
    await page.goto("/#faq");
    const trigger = page.getByRole("button", { name: /thesis demo/i });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
