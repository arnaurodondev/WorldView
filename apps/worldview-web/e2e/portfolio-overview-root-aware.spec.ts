/**
 * e2e/portfolio-overview-root-aware.spec.ts — ROOT portfolio awareness
 *
 * WHY THIS EXISTS: The portfolio page has a special "ROOT" portfolio mode
 * (the aggregate/consolidated view). When the active portfolio is ROOT,
 * the "+ ADD POSITION" button must NOT appear — ROOT is read-only (it
 * reflects all sub-portfolios combined; you cannot add positions to it).
 *
 * WHY browser-level: the ROOT guard is applied via `isRoot` computed from
 * the portfolio name. Only the full data + render pipeline can confirm
 * the guard fires correctly in production-like conditions.
 *
 * DATA SOURCE: Route mocks — portfolio list returns a ROOT portfolio.
 * DESIGN REFERENCE: PRD-0089 W2 §4.19 (ROOT awareness), PRD-0028 §6.5
 */

import { test, expect } from "@playwright/test";
import {
  installStrictApiMocks,
  collectCriticalErrors,
  filterCriticalErrors,
} from "./fixtures/api-mocks";

// ── ROOT portfolio mock helpers ────────────────────────────────────────────────

function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: "e2e-user",
      tenant_id: "e2e-tenant",
      email: "e2e@test.local",
      name: "E2E User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-sig`;
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Portfolio W2 — ROOT portfolio awareness", () => {
  test("ROOT active → '+ ADD POSITION' button not in DOM", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    const token = buildFakeToken();

    // Auth
    await page.route("**/api/v1/auth/refresh", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: token,
          expires_in: 3600,
          user: { user_id: "e2e-user", tenant_id: "e2e-tenant", email: "e2e@test.local", name: "E2E User" },
        }),
      }),
    );
    await page.route("**/api/v1/auth/ws-token", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "fake-ws" }) }),
    );

    // Portfolio list — name = "ROOT" triggers the isRoot guard in page.tsx
    await page.route("**/api/v1/portfolios", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            portfolio_id: "port-root",
            name: "ROOT",
            currency: "USD",
            owner_id: "e2e-user",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ]),
      });
    });

    // Catch-all for remaining endpoints
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY getByText with exact string: the button label is exactly "+ ADD POSITION"
    // (uppercase, plus-sign prefix). If the ROOT guard is broken, this button
    // would appear and allow position creation on the aggregate view.
    const addPositionBtn = page.getByText("+ ADD POSITION", { exact: true });
    // WHY not.toBeVisible() not .toBeHidden(): when ROOT, the button should
    // not be in the DOM at all (not merely hidden), per §4.19 spec.
    await expect(addPositionBtn).not.toBeVisible();

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("non-ROOT portfolio → page loads without crash", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    // Additional endpoints the W2 page fires
    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("body")).not.toContainText("Application error");

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
