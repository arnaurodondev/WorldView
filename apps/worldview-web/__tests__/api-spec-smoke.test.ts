/**
 * __tests__/api-spec-smoke.test.ts — Smoke tests for the committed S9 OpenAPI spec
 *
 * WHY THIS EXISTS: The committed infra/contracts/s9-openapi.json is the source of
 * truth for generated TypeScript types (types/generated/api.ts). These tests
 * ensure the snapshot is non-empty and contains the key routes that the frontend
 * depends on. If someone accidentally commits an empty or malformed spec, this
 * test suite fails immediately — catching the issue before it silently produces
 * wrong generated types.
 *
 * WHO USES IT: CI pipeline + local validation gate (`pnpm test`).
 * DATA SOURCE: infra/contracts/s9-openapi.json (committed snapshot)
 * DESIGN REFERENCE: PLAN-0059-C1 — OpenAPI codegen + drift gate
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Load the committed spec from the repo root.
// WHY resolve relative to __dirname: avoids CWD ambiguity when the test runner
// is invoked from different directories (e.g., repo root vs app directory).
const SPEC_PATH = resolve(__dirname, "../../../infra/contracts/s9-openapi.json");

let spec: {
  openapi: string;
  info: { title: string; version: string };
  paths: Record<string, unknown>;
  components?: { schemas?: Record<string, unknown> };
};

try {
  const raw = readFileSync(SPEC_PATH, "utf-8");
  spec = JSON.parse(raw);
} catch (err) {
  throw new Error(
    `Cannot load S9 OpenAPI spec from ${SPEC_PATH}. ` +
    "Run: curl http://localhost:8000/openapi.json | python3 -m json.tool > infra/contracts/s9-openapi.json"
  );
}

describe("S9 OpenAPI spec smoke tests", () => {
  it("spec file is valid JSON with openapi version", () => {
    // WHY check openapi field: an empty or truncated file would parse as {} or
    // crash above. This asserts the spec is actually an OpenAPI document.
    expect(spec.openapi).toMatch(/^3\./);
  });

  it("spec has a title and version", () => {
    expect(spec.info.title).toBeTruthy();
    expect(spec.info.version).toBeTruthy();
  });

  it("spec has at least 50 paths (non-empty API surface)", () => {
    // WHY 50: the live S9 spec has 93 paths as of 2026-05-03. A drastic drop
    // in path count signals an accidental empty snapshot was committed.
    const pathCount = Object.keys(spec.paths ?? {}).length;
    expect(pathCount).toBeGreaterThanOrEqual(50);
  });

  // ── Key route presence checks ────────────────────────────────────────────
  // Each check verifies a critical frontend route exists in the spec. If S9
  // removes or renames a route, this test fails — alerting the team BEFORE
  // the component breaks at runtime.

  it("includes /v1/portfolios (portfolio list and create)", () => {
    expect(spec.paths["/v1/portfolios"]).toBeDefined();
    expect((spec.paths["/v1/portfolios"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  it("includes /v1/instruments/{instrument_id}/page-bundle (instrument page)", () => {
    expect(spec.paths["/v1/instruments/{instrument_id}/page-bundle"]).toBeDefined();
  });

  it("includes /v1/search/instruments (global search)", () => {
    expect(spec.paths["/v1/search/instruments"]).toBeDefined();
    expect((spec.paths["/v1/search/instruments"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  it("includes /v1/news/top (ranked news feed)", () => {
    expect(spec.paths["/v1/news/top"]).toBeDefined();
    expect((spec.paths["/v1/news/top"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  it("includes /v1/chat/stream (AI chat SSE stream)", () => {
    expect(spec.paths["/v1/chat/stream"]).toBeDefined();
    expect((spec.paths["/v1/chat/stream"] as Record<string, unknown>)["post"]).toBeDefined();
  });

  it("includes /v1/watchlists (watchlist CRUD)", () => {
    expect(spec.paths["/v1/watchlists"]).toBeDefined();
  });

  it("includes /v1/ohlcv/{instrument_id} (OHLCV chart data)", () => {
    expect(spec.paths["/v1/ohlcv/{instrument_id}"]).toBeDefined();
    expect((spec.paths["/v1/ohlcv/{instrument_id}"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  it("includes /v1/signals/prediction-markets (prediction markets)", () => {
    expect(spec.paths["/v1/signals/prediction-markets"]).toBeDefined();
  });

  it("includes /v1/alerts/pending (pending alerts)", () => {
    expect(spec.paths["/v1/alerts/pending"]).toBeDefined();
  });

  it("includes /v1/fundamentals/screen (screener POST endpoint)", () => {
    expect(spec.paths["/v1/fundamentals/screen"]).toBeDefined();
    expect((spec.paths["/v1/fundamentals/screen"] as Record<string, unknown>)["post"]).toBeDefined();
  });

  // ── Component schemas ────────────────────────────────────────────────────

  it("includes /v1/portfolio/{portfolio_id}/bundle (portfolio bundle endpoint)", () => {
    expect(spec.paths["/v1/portfolio/{portfolio_id}/bundle"]).toBeDefined();
    expect((spec.paths["/v1/portfolio/{portfolio_id}/bundle"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  it("includes /v1/dashboard/snapshot (dashboard snapshot endpoint)", () => {
    expect(spec.paths["/v1/dashboard/snapshot"]).toBeDefined();
    expect((spec.paths["/v1/dashboard/snapshot"] as Record<string, unknown>)["get"]).toBeDefined();
  });

  // ── Schema count ratchet (PLAN-0070-B-3, raised by C-1+C-2) ──────────────
  // WHY ≥28: After PLAN-0070 Waves B-1+B-2+C-1+C-2 the spec has 28 named
  // component schemas (C-1 adds PortfolioBundleResponse, C-2 adds
  // DashboardSnapshotResponse). If someone accidentally removes a
  // response_model= annotation or commits a stale spec snapshot, this
  // threshold fails immediately — catching regression before it silently
  // produces an under-typed generated/api.ts.
  //
  // Raise the threshold after each new wave adds schemas; NEVER lower it.
  it("has at least 28 named component schemas (ratchet after B-1+B-2+C-1+C-2)", () => {
    const schemas = spec.components?.schemas ?? {};
    const count = Object.keys(schemas).length;
    expect(count).toBeGreaterThanOrEqual(28);
  });

  it("includes HTTPValidationError in component schemas", () => {
    // WHY: This is the only validation error shape that appears across all 422
    // responses. Its presence confirms the schemas section is populated.
    expect(spec.components?.schemas?.["HTTPValidationError"]).toBeDefined();
  });

  it("includes _BatchOHLCVRequest in component schemas", () => {
    // WHY: The batch OHLCV request is one of the typed request bodies. Its
    // presence confirms request schemas are being exported from the spec.
    expect(spec.components?.schemas?.["_BatchOHLCVRequest"]).toBeDefined();
  });

  // ── Tier-1 schema presence checks (PLAN-0070-B-1) ────────────────────────
  // These 8 schemas correspond to the highest-traffic S9 routes. If any of
  // them disappears from the spec (e.g. someone removes a response_model=
  // annotation), this test fails immediately. Each schema name is checked
  // individually so the failure message is specific about which schema is missing.

  it("includes QuoteResponse schema (GET /v1/quotes/{id})", () => {
    expect(spec.components?.schemas?.["QuoteResponse"]).toBeDefined();
  });

  it("includes NewsTopResponse schema (GET /v1/news/top)", () => {
    expect(spec.components?.schemas?.["NewsTopResponse"]).toBeDefined();
  });

  it("includes NewsArticle schema (items of NewsTopResponse.articles)", () => {
    expect(spec.components?.schemas?.["NewsArticle"]).toBeDefined();
  });

  it("includes PortfolioResponse schema (GET /v1/portfolios)", () => {
    expect(spec.components?.schemas?.["PortfolioResponse"]).toBeDefined();
  });

  it("includes OHLCVResponse schema (GET /v1/ohlcv/{id})", () => {
    expect(spec.components?.schemas?.["OHLCVResponse"]).toBeDefined();
  });

  it("includes AlertResponse schema (GET /v1/alerts/pending)", () => {
    expect(spec.components?.schemas?.["AlertResponse"]).toBeDefined();
  });

  it("includes WatchlistResponse schema (GET /v1/watchlists)", () => {
    expect(spec.components?.schemas?.["WatchlistResponse"]).toBeDefined();
  });

  it("includes InstrumentSearchResult schema (GET /v1/search/instruments)", () => {
    expect(spec.components?.schemas?.["InstrumentSearchResult"]).toBeDefined();
  });

  // ── Tier-2 schema presence checks (PLAN-0070-B-2) ────────────────────────

  it("includes ScreenerResponse schema (POST /v1/fundamentals/screen)", () => {
    expect(spec.components?.schemas?.["ScreenerResponse"]).toBeDefined();
  });

  it("includes PredictionMarketsListResponse schema (GET /v1/signals/prediction-markets)", () => {
    expect(spec.components?.schemas?.["PredictionMarketsListResponse"]).toBeDefined();
  });

  it("includes EarningsCalendarResponse schema (GET /v1/fundamentals/earnings-calendar)", () => {
    expect(spec.components?.schemas?.["EarningsCalendarResponse"]).toBeDefined();
  });

  // ── Bundle + snapshot schemas (PLAN-0070-C-1, C-2) ───────────────────────

  it("includes PortfolioBundleResponse schema (GET /v1/portfolio/{id}/bundle)", () => {
    expect(spec.components?.schemas?.["PortfolioBundleResponse"]).toBeDefined();
  });

  it("includes DashboardSnapshotResponse schema (GET /v1/dashboard/snapshot)", () => {
    expect(spec.components?.schemas?.["DashboardSnapshotResponse"]).toBeDefined();
  });
});
