/**
 * lib/api/__tests__/alertRules.test.ts — unit tests for the alert-rules gateway
 * factory (PLAN-0113 W4 T-4-01).
 *
 * Strategy: mock global fetch() and assert the URL + method + body for each CRUD
 * method, mirroring search.test.ts / chat.test.ts. These pin the wire contract
 * against S9 `/v1/alert-rules` so a refactor can't silently change a path/verb.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createAlertRulesApi, type CreateAlertRuleInput } from "../alertRules";

function mockFetch(status: number, body: unknown = {}) {
  const mockResponse = {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    body: null,
  };
  return vi.spyOn(global, "fetch").mockResolvedValue(mockResponse as unknown as Response);
}

const CREATE_INPUT: CreateAlertRuleInput = {
  rule_type: "PRICE_CROSS",
  name: "AAPL > 250",
  condition: { instrument_id: "i-aapl", operator: "above", value: 250 },
  severity: "high",
};

describe("createAlertRulesApi", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("listAlertRules GETs /v1/alert-rules with serialized filters", async () => {
    const spy = mockFetch(200, { items: [], total: 0 });
    const api = createAlertRulesApi("tok");

    await api.listAlertRules({ enabled: true, rule_type: "NEWS_COUNT", limit: 10, offset: 0 });

    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/v1/alert-rules?");
    expect(url).toContain("enabled=true");
    expect(url).toContain("rule_type=NEWS_COUNT");
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=0");
  });

  it("listAlertRules omits unset filters (no ?enabled=undefined)", async () => {
    const spy = mockFetch(200, { items: [], total: 0 });
    const api = createAlertRulesApi("tok");

    await api.listAlertRules();

    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/v1/alert-rules");
    expect(url).not.toContain("undefined");
    expect(url).not.toContain("?");
  });

  it("getAlertRule GETs /v1/alert-rules/{id} (id URL-encoded)", async () => {
    const spy = mockFetch(200, { rule_id: "r 1" });
    const api = createAlertRulesApi("tok");

    await api.getAlertRule("r 1");

    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/v1/alert-rules/r%201");
  });

  it("createAlertRule POSTs the body to /v1/alert-rules", async () => {
    const spy = mockFetch(201, { rule_id: "r-1" });
    const api = createAlertRulesApi("tok");

    await api.createAlertRule(CREATE_INPUT);

    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/v1/alert-rules");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual(CREATE_INPUT);
  });

  it("updateAlertRule PATCHes /v1/alert-rules/{id} with the patch body", async () => {
    const spy = mockFetch(200, { rule_id: "r-1" });
    const api = createAlertRulesApi("tok");

    await api.updateAlertRule("r-1", { enabled: false });

    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/v1/alert-rules/r-1");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ enabled: false });
  });

  it("deleteAlertRule DELETEs /v1/alert-rules/{id} (204 → undefined)", async () => {
    const spy = mockFetch(204);
    const api = createAlertRulesApi("tok");

    const result = await api.deleteAlertRule("r-1");

    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/v1/alert-rules/r-1");
    expect((init as RequestInit).method).toBe("DELETE");
    expect(result).toBeUndefined();
  });
});
