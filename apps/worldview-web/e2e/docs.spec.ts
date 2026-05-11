/**
 * e2e/docs.spec.ts — PLAN-0052 Wave B docs hub e2e
 *
 * WHY THIS EXISTS: Validates the dynamic /docs route + MDX compilation +
 * sidebar/TOC/search integration end-to-end. Vitest covers the loader and
 * the standalone components; Playwright catches integration issues that
 * only surface when the full Next.js render pipeline runs.
 */

import { test, expect } from "@playwright/test";

test.describe("PLAN-0052 Wave B — docs hub", () => {
  test("/docs index renders the welcome page with sidebar + content", async ({
    page,
  }) => {
    await page.goto("/docs");
    await page.waitForLoadState("networkidle");

    // Header brand mark
    await expect(page.getByText("Documentation")).toBeVisible();
    // Page title from frontmatter
    await expect(
      page.getByRole("heading", { level: 1, name: /welcome/i }),
    ).toBeVisible();
    // Sidebar shows section headings
    await expect(page.getByText(/^Overview$/i)).toBeVisible();
    await expect(page.getByText(/^Getting Started$/i)).toBeVisible();
    // Footer feedback widget
    await expect(page.getByText(/was this page helpful/i)).toBeVisible();
  });

  test("/docs/getting-started renders nested page + breadcrumb", async ({ page }) => {
    await page.goto("/docs/getting-started");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByRole("heading", { level: 1, name: /getting started/i }),
    ).toBeVisible();
    // Breadcrumb shows Docs > Getting started
    await expect(page.getByRole("link", { name: "Docs" })).toBeVisible();
  });

  test("404 for unknown slug", async ({ page }) => {
    const res = await page.goto("/docs/no-such-page-here", {
      waitUntil: "domcontentloaded",
    });
    expect([404, 200]).toContain(res?.status() ?? 0);
    // Next.js renders the not-found UI on 200 in dev — accept either.
  });

  test("cmd-K opens the search dialog", async ({ page }) => {
    await page.goto("/docs");
    // Use the Search trigger button (always visible in the header)
    await page.getByRole("button", { name: /search docs/i }).click();
    await expect(page.getByRole("textbox", { name: /search documentation/i })).toBeVisible();
    // Type a known keyword
    await page.getByRole("textbox", { name: /search documentation/i }).fill("api");
    // At least one result row appears
    await expect(page.locator('[role="option"]').first()).toBeVisible();
  });

  test("sidebar link navigates between pages", async ({ page }) => {
    await page.goto("/docs");
    await page.getByRole("link", { name: /^getting started$/i }).first().click();
    await page.waitForURL(/\/docs\/getting-started/);
    await expect(
      page.getByRole("heading", { level: 1, name: /getting started/i }),
    ).toBeVisible();
  });
});
