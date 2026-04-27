import { test } from "@playwright/test";

test("diagnostic — log exact request URLs via events", async ({ page }) => {
  // Log ALL requests
  page.on("request", (req) => {
    console.log(`ALL_REQ: method=${req.method()} url=${req.url()} resourceType=${req.resourceType()}`);
  });

  // Wildcard to catch EVERYTHING
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (url.includes("auth")) {
      console.log(`ROUTE_AUTH: ${url}`);
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ access_token: "fake", expires_in: 7200,
          user: { user_id: "u1", tenant_id: "t1", email: "test@test.com", name: "Test" } }) });
    } else {
      void route.continue();
    }
  });

  await page.goto("/dashboard");
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(500);
  console.log("DONE");
});
