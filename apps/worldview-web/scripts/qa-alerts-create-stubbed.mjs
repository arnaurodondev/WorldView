/**
 * scripts/qa-alerts-create-stubbed.mjs — proves the FRONTEND create→list→reload
 * contract for the AlertWizard in isolation from the backend.
 *
 * WHY STUBBED: at QA time the S10 alert API container (worldview-alert-1) is DOWN
 * — its alembic migrate sidecar is failing ("Can't locate revision identified by
 * '0010'") because a PARALLEL backend agent is mid-migration on services/alert.
 * So /api/v1/alert-rules returns 500 for everyone. That is a BACKEND/infra issue
 * (owned by the other agent), not a frontend bug. To still validate the FRONTEND
 * end-to-end — that the wizard POSTs the correct structured body, then the rule
 * appears in the manager list and survives a reload — we stub ONLY the
 * /api/v1/alert-rules CRUD endpoint with an in-memory store. Everything else
 * (search, overview, screener fields, NL summary, the actual wizard logic) runs
 * against the real frontend + live backend.
 *
 * Usage: node scripts/qa-alerts-create-stubbed.mjs
 */
import { chromium, request as pwRequest } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FRONTEND = "http://localhost:3001";
const OUT =
  "/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/docs/audits/2026-06-20-alerts-ui-qa";
fs.mkdirSync(OUT, { recursive: true });

const report = [];
function bucket(step) {
  const b = { step, notes: [], capturedPost: null, result: "PENDING" };
  report.push(b);
  return b;
}
async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: false });
  return name + ".png";
}
async function settle(page, ms = 2500) {
  try { await page.waitForLoadState("networkidle", { timeout: ms }); } catch { /* */ }
  await page.waitForTimeout(500);
}
async function freshAuth() {
  const api = await pwRequest.newContext();
  const r = await api.post(`${FRONTEND}/api/v1/auth/dev-login`, { data: {} });
  const j = await r.json();
  await api.dispose();
  return j;
}

// In-memory rule store shared across the stub routes.
const store = [];
let lastPost = null;

async function run(browser) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } });

  await context.route("**/api/v1/auth/refresh", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const a = await freshAuth();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: a.access_token, expires_in: a.expires_in, user: a.user }),
    });
  });

  // Stub the (currently-down) alert-rules CRUD with an in-memory store.
  await context.route("**/api/v1/alert-rules**", async (route) => {
    const req = route.request();
    const method = req.method();
    if (method === "POST") {
      const body = JSON.parse(req.postData() || "{}");
      lastPost = body;
      const now = new Date().toISOString();
      const rule = {
        rule_id: "stub-" + (store.length + 1),
        tenant_id: "t",
        user_id: "u",
        rule_type: body.rule_type,
        name: body.name,
        entity_id: body.condition?.instrument_id ?? body.condition?.entity_id ?? null,
        node_a_entity_id: body.condition?.source_entity_id ?? null,
        node_b_entity_id: body.condition?.target_entity_id ?? null,
        condition: body.condition,
        severity: body.severity ?? "medium",
        enabled: true,
        cooldown_seconds: 3600,
        notify_in_app: body.notify_in_app ?? true,
        notify_email: body.notify_email ?? false,
        last_state: null,
        created_at: now,
        updated_at: now,
      };
      store.push(rule);
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(rule) });
    }
    if (method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: store, total: store.length }),
      });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  const page = await context.newPage();

  // ── Create a PRICE_CROSS rule end-to-end through the wizard ────────────────
  const b = bucket("create-price-cross-and-persist");
  await page.goto(`${FRONTEND}/alerts`, { waitUntil: "domcontentloaded" });
  await settle(page, 4000);
  await page.getByRole("button", { name: /manage alert rules/i }).first().click();
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: /create new alert rule/i }).first().click();
  await page.waitForTimeout(400);
  await page.locator('[data-testid="rule-type-card-PRICE_CROSS"]').click();
  await page.waitForTimeout(300);
  // Fill instrument via real search.
  await page.getByRole("textbox", { name: /Instrument instrument search/i }).fill("AAPL");
  await page.waitForTimeout(1400);
  await page.locator(".bg-popover button").first().click();
  await page.waitForTimeout(300);
  await page.getByRole("spinbutton", { name: /^price level$/i }).fill("250");
  await page.waitForTimeout(300);
  const summary = (await page.locator('[data-testid="rule-nl-summary"]').textContent()) ?? "";
  b.notes.push("NL summary: " + summary);
  b.shot = await shot(page, "stubbed-price-editor-filled");
  await page.getByRole("button", { name: /create rule/i }).click();
  await page.waitForTimeout(1200);
  b.capturedPost = lastPost;
  b.notes.push("POST body: " + JSON.stringify(lastPost));
  // List should now show the rule.
  await page.waitForTimeout(800);
  let rows = await page.locator('ul[role="list"] li').count();
  b.notes.push("rule rows after create: " + rows);
  b.shot2 = await shot(page, "stubbed-rule-list-after-create");

  // ── Reload → rule still listed (served from the stub store) ────────────────
  await page.goto(`${FRONTEND}/alerts`, { waitUntil: "domcontentloaded" });
  await settle(page, 3000);
  await page.getByRole("button", { name: /manage alert rules/i }).first().click();
  await page.waitForTimeout(900);
  const rowsAfterReload = await page.locator('ul[role="list"] li').count();
  b.notes.push("rule rows after reload: " + rowsAfterReload);
  b.shot3 = await shot(page, "stubbed-rule-list-after-reload");

  const postOk =
    lastPost &&
    lastPost.rule_type === "PRICE_CROSS" &&
    lastPost.condition?.instrument_id &&
    lastPost.condition?.operator === "above" &&
    lastPost.condition?.value === 250;
  b.result = postOk && rows > 0 && rowsAfterReload > 0 ? "PASS" : "FAIL";

  await context.close();
}

const browser = await chromium.launch();
try { await run(browser); } finally { await browser.close(); }
fs.writeFileSync(path.join(OUT, "qa-alerts-create-stubbed.json"), JSON.stringify(report, null, 2));
console.log("\n===== STUBBED CREATE→LIST→RELOAD =====");
for (const b of report) {
  console.log(`[${b.result}] ${b.step}`);
  for (const n of b.notes) console.log("   - " + n);
}
console.log("Screenshots in:", OUT);
