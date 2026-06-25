/**
 * e2e/live/alert-wizard-create.spec.ts — P0-1: AlertWizard create, all 5 rule types.
 *
 * WHY THIS EXISTS (2026-06-22 E2E-gaps audit, P0-1 — "the highest-value gap"):
 * The 5-type alert-rule wizard is the platform's single biggest feature that is
 * UNIT-tested only. This spec drives the REAL wizard against the LIVE backend for
 * every rule type:
 *   PRICE_CROSS, NEWS_COUNT, NEWS_MOMENTUM, KG_CONNECTION, FUNDAMENTAL_CROSS.
 *
 * For each type the spec:
 *   1. opens /alerts → "⚙ Rules (N)" manager → "New rule",
 *   2. asserts all 5 type cards are present, then picks the type,
 *   3. fills the type's STRUCTURED condition editor using REAL data — the
 *      instrument/entity PICKERS issue live S3/S7 search and we click a real
 *      result (AAPL / MSFT), the MetricPicker reads the live S3 vocabulary, etc.,
 *   4. asserts the LIVE natural-language summary is non-empty and reflects the
 *      condition (it reads the picked ticker, not a UUID),
 *   5. asserts Save is gated until the condition is complete, then clicks Save,
 *   6. verifies persistence: the rule should appear in the manager list, survive
 *      a reload, and be returned by GET /v1/alert-rules.
 *
 * BACKEND-GAP TOLERANCE (flagged for a backend agent):
 * On the audited deployment the S9 gateway does NOT expose `/v1/alert-rules`
 * (every method 404s; OpenAPI lists no such path). When that route is absent the
 * persistence step CANNOT succeed through no fault of the frontend. Rather than
 * silently passing OR hard-failing on a server gap, each test:
 *   - ALWAYS asserts the full UI flow (steps 1-5) — the part the frontend owns,
 *   - probes `/v1/alert-rules` once; if it 404s it records an annotation and
 *     SKIPS the persistence assertions (step 6) with a clear "backend route
 *     missing" message; if it is present, persistence is asserted strictly.
 *
 * RUN: pnpm exec playwright test --project=live e2e/live/alert-wizard-create.spec.ts
 */

import { test, expect, type Page, type Locator } from "@playwright/test";
import { installLiveAuth, gotoLive, assertAuthenticated, API_BASE } from "../live-helpers";

test.describe.configure({ mode: "serial" });

// ── Picker helper ─────────────────────────────────────────────────────────────

/**
 * pickFromSearch — drive a shared Instrument/Entity picker to a real selection.
 *
 * The pickers (InstrumentPicker / EntityPicker) render an <input aria-label="…">
 * that debounces 300ms then shows a results dropdown of <button>s whose text
 * contains the ticker. We type the query, wait for the live result, click it, and
 * confirm the selection committed by the picker collapsing to its chip (which
 * exposes a "Clear {clearLabel}" button). Scoped to `root` so the KG editor's two
 * pickers target the right field.
 *
 * WHY confirm via the Clear button (not the chip text): the EntityPicker chip
 * shows the COMPANY NAME ("Microsoft Corporation"), not the ticker, so asserting
 * on the ticker would false-fail after a successful pick. The "Clear {label}"
 * button is present iff a value is committed — a reliable, picker-agnostic signal.
 */
async function pickFromSearch(
  root: Locator,
  inputAriaLabel: string,
  query: string,
  clearLabel: string,
): Promise<void> {
  const input = root.getByLabel(inputAriaLabel);
  const result = root.getByRole("button", { name: new RegExp(`\\b${query}\\b`) }).first();
  const committed = root.getByRole("button", { name: `Clear ${clearLabel}` });

  // RETRY the search (audit BUG-3): the EntityPicker fans out one search + N
  // per-candidate /overview calls per debounce; a burst can be rate-limited,
  // leaving the dropdown momentarily empty. Re-typing re-issues the search after
  // the limiter recovers. We try a few times with backoff before giving up.
  for (let attempt = 0; attempt < 4; attempt++) {
    // If a prior attempt already committed the value, we're done.
    if (await committed.count()) return;

    await expect(input, `picker input "${inputAriaLabel}" should be present`).toBeVisible({
      timeout: 15_000,
    });
    // Re-type from scratch each attempt so the debounced query re-fires.
    await input.fill("");
    await input.fill(query);
    try {
      await expect(result).toBeVisible({ timeout: 12_000 });
      await result.click();
      // Selection committed → the picker collapses to its chip + Clear button.
      await expect(committed).toBeVisible({ timeout: 5_000 });
      return;
    } catch {
      // Likely a rate-limited / slow search this attempt — back off and retry.
      await root.page().waitForTimeout(3000 * (attempt + 1));
    }
  }
  throw new Error(
    `live pick for "${query}" did not commit after retries (gateway rate limit?)`,
  );
}

// ── Per-type fill strategies ────────────────────────────────────────────────────

/**
 * Each entry knows how to fill ONE rule type's editor with real data and the
 * substring the live NL summary should contain once complete.
 */
interface RuleTypeCase {
  type: string; // matches the data-testid suffix on the card
  label: string;
  /** Fill the (already-mounted) Step-2 editor inside the wizard dialog. */
  fill: (dialog: Locator, page: Page) => Promise<void>;
  /** Substring the live NL summary should contain when complete (e.g. a ticker). */
  summaryContains: RegExp;
}

const RULE_CASES: RuleTypeCase[] = [
  {
    type: "PRICE_CROSS",
    label: "Price cross",
    summaryContains: /AAPL/,
    fill: async (dialog) => {
      await pickFromSearch(dialog, "Instrument instrument search", "AAPL", "Instrument");
      // Direction defaults to "above"; just set a positive price level.
      await dialog.getByLabel("Price level").fill("250");
    },
  },
  {
    type: "FUNDAMENTAL_CROSS",
    label: "Fundamental",
    summaryContains: /AAPL/,
    fill: async (dialog) => {
      await pickFromSearch(dialog, "Instrument instrument search", "AAPL", "Instrument");
      // MetricPicker reads the live S3 field vocabulary; pick a known numeric key.
      // Selecting by label "P/E Ratio" sets value="pe_ratio" (a backend-valid key).
      const metric = dialog.getByLabel("Fundamental metric");
      await expect(metric).toBeEnabled({ timeout: 15_000 });
      await metric.selectOption({ label: "P/E Ratio" });
      await dialog.getByLabel("Metric threshold").fill("25");
    },
  },
  {
    type: "NEWS_COUNT",
    label: "News volume",
    summaryContains: /MSFT|article/i,
    fill: async (dialog) => {
      // EntityPicker resolves the REAL KG entity_id behind the scenes.
      await pickFromSearch(dialog, "Entity entity search", "MSFT", "Entity");
      await dialog.getByLabel("Article count threshold").fill("5");
      // Window has a sensible default; leave it.
    },
  },
  {
    type: "NEWS_MOMENTUM",
    label: "News momentum",
    summaryContains: /MSFT|momentum|%/i,
    fill: async (dialog) => {
      await pickFromSearch(dialog, "Entity entity search", "MSFT", "Entity");
      await dialog.getByLabel("Momentum delta percent").fill("50");
      await dialog.getByLabel("Minimum article count").fill("2");
    },
  },
  {
    type: "KG_CONNECTION",
    label: "Connection",
    summaryContains: /AAPL|MSFT|connect/i,
    fill: async (dialog) => {
      // Two entity pickers — source must differ from target (editor enforces it).
      await pickFromSearch(dialog, "From entity entity search", "AAPL", "From entity");
      await pickFromSearch(dialog, "To entity entity search", "MSFT", "To entity");
      // max_hops defaults inside the valid 1..3 range.
    },
  },
];

// ── Backend-route availability probe (cached across the suite) ──────────────────

let alertRulesAvailable: boolean | null = null;

/** Probe whether the S9 gateway exposes /v1/alert-rules at all (cached once). */
async function probeAlertRulesRoute(page: Page, token: string): Promise<boolean> {
  if (alertRulesAvailable !== null) return alertRulesAvailable;
  const res = await page.request.get(`${API_BASE}/v1/alert-rules?limit=1`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  // 404 = route genuinely absent (backend gap). 401/403 would be an auth problem
  // (treated as "available but unauthorized" — let the strict path surface it).
  alertRulesAvailable = res.status() !== 404;
  return alertRulesAvailable;
}

// ── Wizard driver ───────────────────────────────────────────────────────────────

/** Open /alerts → Rules manager → New rule, returning the wizard dialog locator. */
async function openWizard(page: Page): Promise<Locator> {
  await gotoLive(page, "/alerts");
  await assertAuthenticated(page);

  // The page header carries the "⚙ Rules (N)" button that opens RuleManagerDialog.
  await page.getByRole("button", { name: /Manage alert rules/i }).click();

  // Inside the manager dialog, "New rule" opens the wizard.
  await page.getByRole("button", { name: /Create new alert rule/i }).click();

  // The wizard is a dialog titled "NEW ALERT RULE".
  const dialog = page.getByRole("dialog").filter({ hasText: "NEW ALERT RULE" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  return dialog;
}

// ── The test ────────────────────────────────────────────────────────────────────

test.describe("@live AlertWizard create — all 5 rule types", () => {
  let token: string;

  // WHY a long per-test timeout: each test cold-compiles /alerts on first hit,
  // then drives live pickers that fan out search + overview calls with 429-aware
  // retries. 120s covers the worst case without flaking.
  test.setTimeout(120_000);

  test.beforeEach(async ({ page }) => {
    token = await installLiveAuth(page);
  });

  // Cool down between tests so the gateway rate limiter (audit BUG-3) recovers
  // before the next test's picker fan-out. Cheap insurance against cross-test
  // 429 contamination in this serial project.
  test.afterEach(async ({ page }) => {
    await page.waitForTimeout(2000);
  });

  for (const rc of RULE_CASES) {
    test(`creates ${rc.label} (${rc.type}) end-to-end`, async ({ page }) => {
      const dialog = await openWizard(page);

      // ── Step 1: all 5 type cards present, then pick this type ───────────────
      for (const t of RULE_CASES) {
        await expect(
          dialog.getByTestId(`rule-type-card-${t.type}`),
          `type card ${t.type} should be present in Step 1`,
        ).toBeVisible();
      }
      await dialog.getByTestId(`rule-type-card-${rc.type}`).click();

      // ── Step 2: Save starts disabled (condition incomplete) ─────────────────
      const saveBtn = dialog.getByRole("button", { name: /Create rule/i });
      await expect(saveBtn, "Save must be disabled before the condition is complete").toBeDisabled();

      // ── Fill the structured editor with REAL data via the live pickers ──────
      await rc.fill(dialog, page);

      // ── Live NL summary reflects the condition (reads ticker, not a UUID) ────
      const summary = dialog.getByTestId("rule-nl-summary");
      await expect(summary).toBeVisible();
      await expect(async () => {
        const text = await summary.innerText();
        expect(text.trim().length, "NL summary should be non-empty").toBeGreaterThan(0);
        expect(text).toMatch(rc.summaryContains);
        // It must NOT show a raw UUID where a ticker/name belongs.
        expect(text, `summary leaked a UUID: "${text}"`).not.toMatch(
          /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i,
        );
      }).toPass({ timeout: 15_000 });

      // ── Save becomes enabled once the condition is complete ─────────────────
      await expect(saveBtn, "Save should enable once the condition is complete").toBeEnabled({
        timeout: 15_000,
      });

      // Give this rule a unique name so we can find it in the list afterwards.
      const ruleName = `E2E ${rc.type} ${Date.now()}`;
      await dialog.getByLabel("Rule name").fill(ruleName);

      // ── Persistence — gated on the backend route actually existing ──────────
      const available = await probeAlertRulesRoute(page, token);
      if (!available) {
        // Flag the backend gap loudly in the report; the frontend UI flow above
        // is fully proven, but persistence is impossible without the S9 route.
        test.info().annotations.push({
          type: "backend-gap",
          description:
            "S9 gateway does not expose /v1/alert-rules (404). The wizard UI flow " +
            "is verified, but Save cannot persist until the backend route ships. " +
            "FLAGGED for a backend agent — see report.",
        });
        // Close the wizard without asserting persistence (would 404 server-side).
        await dialog.getByRole("button", { name: /^Cancel$/ }).click();
        test.skip(true, "backend /v1/alert-rules route missing — persistence not assertable");
        return;
      }

      // Route IS present → assert real persistence.
      await saveBtn.click();
      await expect(dialog).toBeHidden({ timeout: 15_000 });

      // 1) The rule appears in the manager list.
      await expect(page.getByText(ruleName, { exact: false })).toBeVisible({ timeout: 15_000 });

      // 2) It is returned by the backend.
      const listRes = await page.request.get(`${API_BASE}/v1/alert-rules?limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(listRes.ok()).toBe(true);
      const body = (await listRes.json()) as { items: Array<{ name: string }> };
      expect(
        body.items.some((r) => r.name === ruleName),
        "created rule should be returned by GET /v1/alert-rules",
      ).toBe(true);

      // 3) It survives a reload (re-open the manager and confirm it is listed).
      await gotoLive(page, "/alerts");
      await page.getByRole("button", { name: /Manage alert rules/i }).click();
      await expect(page.getByText(ruleName, { exact: false })).toBeVisible({ timeout: 15_000 });
    });
  }
});
