/**
 * __tests__/portfolios-add-position.test.ts — Unit tests for addPosition()
 *
 * WHY THIS EXISTS (PLAN-0108 W5 T-5-02):
 *   The W1 migration renamed the `direction` field to `trade_side` in S1's
 *   RecordTransactionRequest. This test pins that the request body sent by
 *   addPosition() contains `trade_side: "BUY"` (not the old `direction` field)
 *   so regressions are caught at the unit level before any integration test runs.
 *
 * STRATEGY: spy on the global `fetch` to capture the raw request body; assert
 * field presence and absence without running a real network call.
 *
 * DATA SOURCE: Mocked fetch — deterministic, no network.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPortfoliosApi } from "@/lib/api/portfolios";

// ── Minimal S1 transaction response ──────────────────────────────────────────
// addPosition() returns a Transaction object — we need the raw S1 shape to
// satisfy the apiFetch<...> generic. Only fields that addPosition() reads back
// are needed here.
const MOCK_S1_RESPONSE = {
  id: "txn-001",
  portfolio_id: "port-123",
  instrument_id: "inst-456",
  transaction_type: "TRADE",
  trade_side: "BUY", // W1 renamed from direction → trade_side
  quantity: "10",
  price: "150.00",
  fees: "0",
  currency: "USD",
  executed_at: "2026-06-08T10:00:00Z",
  created_at: "2026-06-08T10:00:00Z",
};

// WHY cast to unknown: vi.spyOn on the overloaded `globalThis.fetch` returns
// a MockInstance type that TypeScript can't unify with vi.Mock due to overloads.
// Casting through unknown lets us treat the spy as a plain vi.fn() call recorder.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let fetchSpy: { mock: { calls: any[][] }; mockRestore: () => void };

beforeEach(() => {
  // Spy on global fetch and resolve with the mock S1 response.
  // WHY json() is async: apiFetch calls response.json() on error paths;
  // on success it calls response.json() directly. Make both .ok and .json() work.
  fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(MOCK_S1_RESPONSE),
  } as Response);
});

afterEach(() => {
  fetchSpy.mockRestore();
});

// ── Request body shape ────────────────────────────────────────────────────────

describe("createPortfoliosApi().addPosition — request body (T-5-02, PLAN-0108)", () => {
  it("sends trade_side: 'BUY' in the request body", async () => {
    const api = createPortfoliosApi("test-token");
    await api.addPosition("port-123", "inst-456", 10, 150);

    // Extract the body that was sent to fetch.
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    // WHY exact equality: "BUY" is the only valid value for a manual open —
    // a SELL would reduce a holding that doesn't exist yet (BP-328 family).
    expect(body.trade_side).toBe("BUY");
  });

  it("does NOT send the old 'direction' field", async () => {
    const api = createPortfoliosApi("test-token");
    await api.addPosition("port-123", "inst-456", 10, 150);

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    // WHY explicitly assert absence: the old field `direction` was silently
    // accepted by older S1 deployments — asserting it's gone prevents any
    // future rollback from re-introducing the wrong field (T-5-02 guard).
    expect(body).not.toHaveProperty("direction");
  });

  it("sends transaction_type: 'TRADE'", async () => {
    const api = createPortfoliosApi("test-token");
    await api.addPosition("port-123", "inst-456", 5, 200);

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    expect(body.transaction_type).toBe("TRADE");
  });

  it("sends the correct portfolio_id, instrument_id, quantity, and price", async () => {
    const api = createPortfoliosApi("test-token");
    await api.addPosition("port-789", "inst-111", 25, 75.5);

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    expect(body.portfolio_id).toBe("port-789");
    expect(body.instrument_id).toBe("inst-111");
    expect(body.quantity).toBe(25);
    expect(body.price).toBe(75.5);
  });
});

// ── PLAN-0122 W-C (R-13): optional tradeDate → executed_at ─────────────────────
//
// WHY these tests: the trade-date picker in AddPositionDialog depends on the
// gateway threading a chosen date into `executed_at`. The param is optional and
// TRAILING so every existing 4-arg caller is unaffected (backward-compat). These
// pin both branches: provided ⇒ that date; omitted ⇒ "now".

describe("createPortfoliosApi().addPosition — optional tradeDate (PLAN-0122 R-13)", () => {
  it("uses the provided tradeDate for executed_at when given", async () => {
    const api = createPortfoliosApi("test-token");
    await api.addPosition("port-1", "inst-1", 10, 100, "2020-01-15T00:00:00Z");

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    // The chosen date flows straight through to S1's executed_at field.
    expect(body.executed_at).toBe("2020-01-15T00:00:00Z");
  });

  it("defaults executed_at to now when tradeDate is omitted (backward-compat)", async () => {
    const before = Date.now();
    const api = createPortfoliosApi("test-token");
    // Called with the ORIGINAL 4-arg signature — proves existing callers are safe.
    await api.addPosition("port-1", "inst-1", 10, 100);
    const after = Date.now();

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;

    // executed_at is an ISO "now" string within the call window.
    expect(typeof body.executed_at).toBe("string");
    const ts = Date.parse(body.executed_at as string);
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });
});
