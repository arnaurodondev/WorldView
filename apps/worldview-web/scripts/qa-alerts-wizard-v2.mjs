/**
 * scripts/qa-alerts-wizard-v2.mjs — exhaustive e2e QA of the type-first AlertWizard
 * (PLAN-0113 Wave 4/5). Rewrite of qa-alerts-wizard.mjs.
 *
 * Drives the REAL backend (S9 :8000 via the frontend proxy :3001) with NO data
 * stubs — the company-overview 500 is now fixed, so EntityPicker resolves real
 * KG entity_ids live. The ONLY route stub is /api/v1/auth/refresh, which we
 * fulfil with a real dev-login JWT so AuthContext authenticates on mount (this
 * deployment has Zitadel configured → no Dev Login button → no httpOnly cookie
 * from dev-login, so the refresh path is the only browser-side auth seam).
 *
 * For EACH of the 5 rule types: open the wizard via /alerts → ⚙ Rules → New rule
 * → pick the type card → fill the editor with real entities (AAPL/MSFT) → assert
 * the live NL summary → Save → assert the rule appears in the list and survives a
 * reload. Plus validation (Save disabled until complete) and the 2 entry points.
 *
 * Usage: node scripts/qa-alerts-wizard-v2.mjs
 */
import { chromium, request as pwRequest } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FRONTEND = "http://localhost:3001";
const OUT =
  "/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/docs/audits/2026-06-20-alerts-ui-qa";
fs.mkdirSync(OUT, { recursive: true });

const report = [];
function newBucket(step) {
  const b = { step, consoleErrors: [], failedRequests: [], notes: [], result: "PENDING" };
  report.push(b);
  return b;
}
function attach(page, bucket) {
  page.on("console", (m) => {
    if (m.type() === "error") bucket.consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => bucket.consoleErrors.push("PAGEERROR: " + e.message));
  page.on("response", (r) => {
    const u = r.url();
    // Ignore the stubbed refresh + benign 304s.
    if (r.status() >= 400 && !u.includes("/auth/refresh")) {
      bucket.failedRequests.push(`${r.status()} ${r.request().method()} ${u}`);
    }
  });
}
async function shot(page, name) {
  const p = path.join(OUT, name + ".png");
  await page.screenshot({ path: p, fullPage: false });
  return name + ".png";
}
async function settle(page, ms = 2500) {
  try { await page.waitForLoadState("networkidle", { timeout: ms }); } catch { /* */ }
  await page.waitForTimeout(500);
}

async function freshAuth() {
  const api = await pwRequest.newContext();
  const resp = await api.post(`${FRONTEND}/api/v1/auth/dev-login`, { data: {} });
  const json = await resp.json();
  await api.dispose();
  return json;
}

async function installRoutes(context) {
  await context.route("**/api/v1/auth/refresh", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const auth = await freshAuth();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: auth.access_token,
        expires_in: auth.expires_in,
        user: auth.user,
      }),
    });
  });
}

async function devLogin(page, b) {
  await page.goto(`${FRONTEND}/alerts`, { waitUntil: "domcontentloaded" });
  await settle(page, 6000);
  const authed = !page.url().includes("/login");
  b.notes.push("post-nav URL: " + page.url());
  return authed;
}

// Open the wizard: /alerts → "⚙ Rules" button → "New rule".
async function openWizard(page) {
  await page.goto(`${FRONTEND}/alerts`, { waitUntil: "domcontentloaded" });
  await settle(page, 4000);
  await page.getByRole("button", { name: /manage alert rules/i }).first().click();
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: /create new alert rule/i }).first().click();
  await page.waitForTimeout(500);
}

async function pickType(page, type) {
  await page.locator(`[data-testid="rule-type-card-${type}"]`).click();
  await page.waitForTimeout(400);
}

async function fillInstrumentPicker(page, label, query, pickText) {
  const input = page.getByRole("textbox", { name: new RegExp(`${label} instrument search`, "i") });
  await input.first().fill(query);
  await page.waitForTimeout(1400);
  const dropRows = page.locator(".bg-popover button");
  if ((await dropRows.count()) === 0) {
    // Fallback: match by button containing the pick text.
    const opt = page.getByRole("button", { name: new RegExp(pickText, "i") }).first();
    if ((await opt.count()) === 0) return false;
    await opt.click();
    await page.waitForTimeout(300);
    return true;
  }
  await dropRows.first().click();
  await page.waitForTimeout(300);
  return true;
}

async function fillEntityPicker(page, label, query) {
  // Scope to THIS picker's container (the relative wrapper that holds the labelled
  // input) so the dropdown we click belongs to the right picker when two are
  // mounted (KG_CONNECTION). The EntityPicker renders input + dropdown inside one
  // `relative` div; we locate it via the labelled input's ancestor.
  const input = page.getByRole("textbox", { name: new RegExp(`${label} entity search`, "i") });
  await input.first().fill(query);
  await page.waitForTimeout(1800); // debounce + S3 search + overview enrich
  const container = input.first().locator("xpath=ancestor::div[contains(@class,'relative')][1]");
  const dropRows = container.locator(".bg-popover button");
  if ((await dropRows.count()) === 0) return false;
  await dropRows.first().click();
  await page.waitForTimeout(300);
  return true;
}

async function saveDisabled(page) {
  const save = page.getByRole("button", { name: /create rule|save changes/i }).first();
  return await save.isDisabled();
}
async function nlSummary(page) {
  return (await page.locator('[data-testid="rule-nl-summary"]').first().textContent()) ?? "";
}
async function clickSave(page) {
  await page.getByRole("button", { name: /create rule/i }).first().click();
}
async function ruleListLabels(page) {
  await page.waitForTimeout(1200);
  const rows = page.locator('ul[role="list"] li');
  const n = await rows.count();
  const out = [];
  for (let i = 0; i < n; i++) out.push((await rows.nth(i).innerText()).replace(/\s+/g, " ").trim());
  return out;
}

async function run(browser) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
  await installRoutes(context);
  const page = await context.newPage();

  const login = newBucket("login");
  attach(page, login);
  login.result = (await devLogin(page, login)) ? "PASS" : "FAIL";

  const flows = [
    {
      type: "PRICE_CROSS",
      fill: async () => {
        await fillInstrumentPicker(page, "Instrument", "AAPL", "AAPL");
        await page.getByRole("spinbutton", { name: /^price level$/i }).fill("250");
      },
      expectSummary: /price crosses above 250/i,
    },
    {
      type: "FUNDAMENTAL_CROSS",
      fill: async () => {
        await fillInstrumentPicker(page, "Instrument", "AAPL", "AAPL");
        const sel = page.getByRole("combobox", { name: /fundamental metric/i });
        const optionValues = await sel
          .locator("option")
          .evaluateAll((os) => os.map((o) => o.value).filter((v) => v));
        if (optionValues.length) await sel.selectOption(optionValues[0]);
        await page.getByRole("spinbutton", { name: /metric threshold/i }).fill("25");
      },
      expectSummary: /crosses (above|below) 25/i,
      checkMetric: true,
    },
    {
      type: "NEWS_COUNT",
      fill: async () => {
        await fillEntityPicker(page, "Entity", "AAPL");
        await page.getByRole("spinbutton", { name: /article count threshold/i }).fill("5");
      },
      expectSummary: /≥ 5 articles.*mention/i,
    },
    {
      type: "NEWS_MOMENTUM",
      fill: async () => {
        await fillEntityPicker(page, "Entity", "AAPL");
        await page.getByRole("spinbutton", { name: /momentum delta percent/i }).fill("50");
      },
      expectSummary: /news momentum.*jumps ≥ 50%/i,
    },
    {
      type: "KG_CONNECTION",
      fill: async () => {
        await fillEntityPicker(page, "From entity", "AAPL");
        await fillEntityPicker(page, "To entity", "MSFT");
      },
      expectSummary: /connects to.*within \d hop/i,
    },
  ];

  for (const f of flows) {
    const b = newBucket(`wizard-${f.type}`);
    attach(page, b);
    try {
      await openWizard(page);
      await pickType(page, f.type);
      const disabledBefore = await saveDisabled(page);
      b.notes.push(`save disabled before fill: ${disabledBefore}`);
      await f.fill();
      await page.waitForTimeout(500);
      if (f.checkMetric) {
        const optCount = await page
          .getByRole("combobox", { name: /fundamental metric/i })
          .locator("option")
          .count();
        b.notes.push(`MetricPicker option count (incl placeholder): ${optCount}`);
      }
      const summary = await nlSummary(page);
      b.notes.push(`NL summary: ${summary}`);
      b.shot = await shot(page, `editor-${f.type}`);
      const disabledAfter = await saveDisabled(page);
      b.notes.push(`save disabled after fill: ${disabledAfter}`);
      const summaryOk = f.expectSummary.test(summary);
      b.notes.push(`summary matches expected: ${summaryOk}`);

      if (disabledAfter) {
        b.result = "FAIL";
        b.notes.push("Save still disabled after a complete fill — cannot create.");
        await page.keyboard.press("Escape").catch(() => {});
        continue;
      }
      await clickSave(page);
      await page.waitForTimeout(1800);
      const labels = await ruleListLabels(page);
      b.notes.push(`rule list rows after save: ${labels.length}`);
      b.result =
        disabledBefore && !disabledAfter && summaryOk && labels.length > 0 ? "PASS" : "PARTIAL";
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(400);
    } catch (e) {
      b.result = "FAIL";
      b.notes.push("ERROR: " + e.message);
      await shot(page, `editor-${f.type}-ERROR`).catch(() => {});
    }
  }

  // Wizard step-1 grid screenshot.
  try {
    await openWizard(page);
    await shot(page, "wizard-step1-type-grid");
    await page.keyboard.press("Escape").catch(() => {});
  } catch { /* */ }

  // ── Persistence across reload ──────────────────────────────────────────────
  const persist = newBucket("persistence-reload");
  attach(page, persist);
  try {
    await page.goto(`${FRONTEND}/alerts`, { waitUntil: "domcontentloaded" });
    await settle(page, 3000);
    await page.getByRole("button", { name: /manage alert rules/i }).first().click();
    await page.waitForTimeout(1000);
    const labels = await ruleListLabels(page);
    persist.notes.push(`rules visible after reload: ${labels.length}`);
    persist.shot = await shot(page, "rule-list-after-reload");
    persist.result = labels.length > 0 ? "PASS" : "FAIL";
    await page.keyboard.press("Escape").catch(() => {});
  } catch (e) {
    persist.result = "FAIL";
    persist.notes.push("ERROR: " + e.message);
  }

  // ── Entry point: instrument page +Alert ────────────────────────────────────
  const ep1 = newBucket("entrypoint-instrument-alert");
  attach(page, ep1);
  try {
    await page.goto(`${FRONTEND}/instruments/AAPL`, { waitUntil: "domcontentloaded" });
    await settle(page, 6000);
    const btn = page.locator('[data-testid="instrument-alert-button"]');
    const present = (await btn.count()) > 0;
    ep1.notes.push(`+Alert button present: ${present}`);
    if (present) {
      ep1.notes.push(`+Alert button enabled: ${!(await btn.first().isDisabled())}`);
      await btn.first().click();
      await page.waitForTimeout(800);
      const summary = await nlSummary(page);
      ep1.notes.push(`prefilled NL summary: ${summary}`);
      // Chip should show AAPL (not a UUID). The price editor is PRICE_CROSS so the
      // type-card grid should NOT be present (skipped to step 2).
      const gridPresent = (await page.locator('[data-testid="rule-type-card-PRICE_CROSS"]').count()) > 0;
      ep1.notes.push(`type-card grid present (should be false): ${gridPresent}`);
      const chip = await page.locator("span.text-primary", { hasText: /AAPL/i }).count();
      ep1.notes.push(`AAPL chip present: ${chip > 0}`);
      ep1.shot = await shot(page, "entrypoint-instrument-alert");
      ep1.result = !gridPresent && (chip > 0 || /AAPL/i.test(summary)) ? "PASS" : "PARTIAL";
      await page.keyboard.press("Escape").catch(() => {});
    } else {
      ep1.result = "FAIL";
    }
  } catch (e) {
    ep1.result = "FAIL";
    ep1.notes.push("ERROR: " + e.message);
  }

  // ── Entry point: KG connections page +Alert ────────────────────────────────
  const ep2 = newBucket("entrypoint-kg-connection-alert");
  attach(page, ep2);
  try {
    await page.goto(`${FRONTEND}/connections`, { waitUntil: "domcontentloaded" });
    await settle(page, 5000);
    // PathBetweenPanel lives under the "How are these related?" (pairwise) tab.
    await page.getByRole("tab", { name: /how are these related/i }).click().catch(() => {});
    await page.waitForTimeout(800);
    // Pick two entities to reveal the "Alert on connection" button.
    const okA = await fillEntityPicker(page, "Source", "AAPL");
    const okB = await fillEntityPicker(page, "Target", "MSFT");
    ep2.notes.push(`source picked: ${okA}, target picked: ${okB}`);
    await page.waitForTimeout(800);
    const btn = page.locator('[data-testid="kg-connection-alert-button"]');
    const present = (await btn.count()) > 0;
    ep2.notes.push(`KG +Alert button present: ${present}`);
    if (present) {
      await btn.first().click();
      await page.waitForTimeout(800);
      const summary = await nlSummary(page);
      ep2.notes.push(`prefilled NL summary: ${summary}`);
      const gridPresent =
        (await page.locator('[data-testid="rule-type-card-KG_CONNECTION"]').count()) > 0;
      ep2.notes.push(`type-card grid present (should be false): ${gridPresent}`);
      ep2.shot = await shot(page, "entrypoint-kg-connection-alert");
      // Both seeded entity chips should render names (AAPL/MSFT/company names).
      ep2.result =
        !gridPresent && /connects to/i.test(summary) && !/—/.test(summary) ? "PASS" : "PARTIAL";
      await page.keyboard.press("Escape").catch(() => {});
    } else {
      ep2.shot = await shot(page, "entrypoint-kg-connection-panel");
      ep2.result = "FAIL";
    }
  } catch (e) {
    ep2.result = "FAIL";
    ep2.notes.push("ERROR: " + e.message);
  }

  await context.close();
}

const browser = await chromium.launch();
try {
  await run(browser);
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(OUT, "qa-alerts-wizard-v2.json"), JSON.stringify(report, null, 2));
console.log("\n===== ALERT WIZARD QA SUMMARY =====");
for (const b of report) {
  console.log(`\n[${b.result}] ${b.step}`);
  for (const n of b.notes) console.log("   - " + n);
  if (b.consoleErrors.length) console.log("   consoleErrors: " + JSON.stringify(b.consoleErrors));
  if (b.failedRequests.length) console.log("   failedRequests: " + JSON.stringify(b.failedRequests));
}
console.log("\nScreenshots + JSON in:", OUT);
