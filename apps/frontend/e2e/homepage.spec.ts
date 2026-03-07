import { test, expect } from "@playwright/test";

test("homepage loads and shows navigation", async ({ page }) => {
  await page.goto("/");

  // Verify app shell renders
  await expect(page.locator("h1")).toContainText("Worldview");

  // Verify navigation links
  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Companies" })).toBeVisible();
  await expect(page.getByRole("link", { name: "News" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Chat" })).toBeVisible();
});

test("navigates to companies page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Companies" }).click();
  await expect(page.locator("h2")).toContainText("Companies");
});
