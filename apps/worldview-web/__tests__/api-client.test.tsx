/**
 * __tests__/api-client.test.tsx — PLAN-0059-C C-3 useApiClient memoisation.
 *
 * COVERS the C-3 critical test:
 *   - test_use_api_client_memoizes_per_token
 *     → same token returns same gateway instance (===) across renders;
 *       a token change produces a NEW gateway instance.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { ApiClientProvider, useApiClient } from "@/lib/api-client";

// ── Auth mock ────────────────────────────────────────────────────────────────
//
// We control accessToken via this fake provider so the test can mutate the
// "logged-in" token between renders.

let currentToken: string | null = "tok-1";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    accessToken: currentToken,
    isAuthenticated: currentToken !== null,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  }),
}));

// ── Gateway mock ─────────────────────────────────────────────────────────────
//
// createGateway is mocked to return a fresh object EACH call — that way, when
// the provider memoises correctly we can distinguish a memoised reuse (one
// call) from a misbehaving recompute (multiple calls per render).

const createGatewayMock = vi.fn((token?: string | null) => ({
  __token: token,
  getPortfolios: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: (t?: string | null) => createGatewayMock(t),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

beforeEach(() => {
  createGatewayMock.mockClear();
  currentToken = "tok-1";
});

describe("useApiClient — memoisation", () => {
  it("returns the SAME gateway reference for the same token across renders", () => {
    const refs: unknown[] = [];

    function Probe() {
      const gw = useApiClient();
      refs.push(gw);
      return null;
    }

    const { rerender } = render(
      <ApiClientProvider>
        <Probe />
      </ApiClientProvider>,
    );

    // Force a re-render of the same tree (same token). The provider's useMemo
    // dependency [accessToken] is unchanged → memoised gateway is returned.
    rerender(
      <ApiClientProvider>
        <Probe />
      </ApiClientProvider>,
    );

    expect(refs.length).toBeGreaterThanOrEqual(2);
    expect(refs[0]).toBe(refs[1]); // strict identity ===
    // createGateway should have been called once for the lifetime of this token.
    expect(createGatewayMock).toHaveBeenCalledTimes(1);
    expect(createGatewayMock).toHaveBeenCalledWith("tok-1");
  });

  it("returns a DIFFERENT gateway reference when the token rotates", () => {
    const refs: unknown[] = [];

    function Probe() {
      const gw = useApiClient();
      refs.push(gw);
      return null;
    }

    const { rerender } = render(
      <ApiClientProvider>
        <Probe />
      </ApiClientProvider>,
    );

    // Mutate the token before re-rendering — the mocked useAuth will return
    // the new value, the provider's memo dep changes, and a NEW gateway must
    // be constructed.
    act(() => {
      currentToken = "tok-2";
    });
    rerender(
      <ApiClientProvider>
        <Probe />
      </ApiClientProvider>,
    );

    expect(refs.length).toBeGreaterThanOrEqual(2);
    expect(refs[0]).not.toBe(refs[refs.length - 1]);
    expect(createGatewayMock).toHaveBeenCalledWith("tok-2");
  });

  it("throws a clear error when used outside the provider", () => {
    function Probe() {
      useApiClient();
      return null;
    }

    // Suppress the React error-boundary console noise for this assertion.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/ApiClientProvider/);
    spy.mockRestore();
  });
});
