/**
 * e2e/live/watchlists-member-count.spec.ts — P0-3: watchlists member-count integrity.
 *
 * WHY THIS EXISTS (2026-06-22 E2E-gaps audit, BUG-2 / P0-3):
 * The audit reported `/watchlists` showing "MEMBERS = 0" for every watchlist
 * while the sidebar simultaneously rendered real members (AAPL/MSFT/GOOGL). Root
 * cause: the hub list endpoint (`GET /v1/watchlists`) returns metadata WITHOUT
 * members, so the gateway mapper defaults `member_count` to 0. The page was
 * rebuilt (2026-06-19) to derive the per-row count from the per-watchlist
 * `/insights` endpoint (which carries the REAL `members_count`).
 *
 * This spec LOCKS that fix against the LIVE backend: for the first watchlist it
 * asserts the rail row shows a NON-ZERO member count AND that the count matches
 * what the `/insights` endpoint authoritatively reports — so any regression that
 * reverts the page to the bare-list count (every row 0) is caught.
 *
 * RUN: pnpm exec playwright test --project=live e2e/live/watchlists-member-count.spec.ts
 */

import { test, expect } from "@playwright/test";
import { installLiveAuth, gotoLive, assertAuthenticated, API_BASE } from "../live-helpers";

test.describe.configure({ mode: "serial" });

test.describe("@live watchlists member-count integrity", () => {
  test("rail row count is non-zero and matches the insights source (BUG-2)", async ({
    page,
  }) => {
    // Mint a real token; reuse it both to drive the UI (via the refresh seam) and
    // to query the backend directly for the authoritative member count.
    const token = await installLiveAuth(page);

    // ── 1. Authoritative truth from the backend ──────────────────────────────
    // Fetch the watchlist list + the first list's insights directly. `members_count`
    // here is what the rail row MUST show; the bug was the rail showing 0 instead.
    const listRes = await page.request.get(`${API_BASE}/v1/watchlists`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(listRes.ok(), "GET /v1/watchlists should succeed on the live stack").toBe(true);
    const lists = (await listRes.json()) as Array<{ id: string; name: string }>;

    // The seeded dev tenant ships 3 watchlists; if a deployment has none there is
    // nothing to assert about counts, so skip rather than false-fail.
    test.skip(lists.length === 0, "no watchlists on this deployment");
    const first = lists[0]!;

    const insightsRes = await page.request.get(
      `${API_BASE}/v1/watchlists/${first.id}/insights`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(insightsRes.ok(), "GET /v1/watchlists/{id}/insights should succeed").toBe(true);
    const insights = (await insightsRes.json()) as { members_count: number };
    const expectedCount = insights.members_count;

    // The whole point of the bug is that members EXIST but the page shows 0 — so
    // the test is only meaningful when the seed watchlist actually has members.
    expect(
      expectedCount,
      "seed watchlist should have members for this regression to be meaningful",
    ).toBeGreaterThan(0);

    // ── 2. What the page actually renders ────────────────────────────────────
    await gotoLive(page, "/watchlists");
    await assertAuthenticated(page);

    // The left rail is a <nav aria-label="Watchlists"> of selectable rows. Find
    // the row for the first watchlist by its name and read its "N members" meta.
    const rail = page.locator('nav[aria-label="Watchlists"]');
    await expect(rail).toBeVisible({ timeout: 15_000 });

    const row = rail.getByRole("button", { name: new RegExp(first.name, "i") });
    await expect(row, `rail row for "${first.name}" should render`).toBeVisible();

    // The meta line reads e.g. "3 members …". Wait for the insights-derived count
    // to replace the loading "—" placeholder, then assert it matches the source.
    // WHY a polling expect: the row mounts its own /insights query; the count
    // appears asynchronously after the row paints.
    await expect(async () => {
      const text = (await row.innerText()).replace(/\s+/g, " ");
      // Must NOT show the BUG-2 symptom ("0 members") when members exist.
      expect(text, `BUG-2 regression: row shows zero members\nrow text: "${text}"`).not.toMatch(
        /\b0 members?\b/,
      );
      // Must show the authoritative count from /insights.
      expect(
        text,
        `rail count != insights members_count (${expectedCount})\nrow text: "${text}"`,
      ).toMatch(new RegExp(`\\b${expectedCount} members?\\b`));
    }).toPass({ timeout: 15_000 });

    // ── 3. The detail pane stat strip agrees too ─────────────────────────────
    // Selecting the row populates the right pane; its "Members" stat must show the
    // same authoritative count (defends the detail surface as well as the rail).
    await row.click();
    const membersStat = page.getByText("Members", { exact: true }).first();
    await expect(membersStat).toBeVisible({ timeout: 15_000 });
    await expect(async () => {
      // The stat renders "Members <count>" as two adjacent spans; assert the count
      // string is present somewhere in the pane header region.
      const header = page.locator("header").filter({ hasText: first.name }).first();
      const headerText = (await header.innerText()).replace(/\s+/g, " ");
      expect(headerText).toContain(String(expectedCount));
    }).toPass({ timeout: 15_000 });
  });
});
