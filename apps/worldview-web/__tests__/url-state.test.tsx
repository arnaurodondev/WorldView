/**
 * __tests__/url-state.test.tsx — nuqs URL-state round-trip tests (PLAN-0059 C-6)
 *
 * Verifies the three URL-backed dimensions adopted in this wave:
 *   1. Portfolio active tab — `?tab=holdings|transactions|watchlist`
 *   2. Equity-curve period — `?period=1W|1M|3M|6M|1Y|All`
 *   3. Screener cap tier — `?capTier=ALL|LARGE|MID|SMALL`
 *
 * We test the parser + setter contract directly via tiny harness components
 * wrapped with `NuqsTestingAdapter`. Testing the parsers in isolation is the
 * documented nuqs-recommended pattern (and avoids dragging the entire
 * portfolio + screener page trees + their TanStack queries into a unit
 * test).
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  NuqsTestingAdapter,
  type OnUrlUpdateFunction,
} from "nuqs/adapters/testing";
import { parseAsStringLiteral, useQueryState } from "nuqs";

// ── Harnesses ────────────────────────────────────────────────────────────────

function TabHarness() {
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringLiteral(["holdings", "transactions", "watchlist"] as const)
      .withDefault("holdings")
      .withOptions({ clearOnDefault: true }),
  );
  return (
    <>
      <output data-testid="value">{tab}</output>
      <button onClick={() => setTab("transactions")}>tx</button>
      <button onClick={() => setTab("watchlist")}>wl</button>
      <button onClick={() => setTab("holdings")}>hd</button>
    </>
  );
}

function PeriodHarness() {
  const [period, setPeriod] = useQueryState(
    "period",
    parseAsStringLiteral([
      "1W",
      "1M",
      "3M",
      "6M",
      "1Y",
      "All",
    ] as const)
      .withDefault("3M")
      .withOptions({ clearOnDefault: true }),
  );
  return (
    <>
      <output data-testid="value">{period}</output>
      <button onClick={() => setPeriod("1Y")}>1Y</button>
      <button onClick={() => setPeriod("3M")}>3M</button>
    </>
  );
}

function CapTierHarness() {
  const [tier, setTier] = useQueryState(
    "capTier",
    parseAsStringLiteral(["ALL", "LARGE", "MID", "SMALL"] as const)
      .withDefault("ALL")
      .withOptions({ clearOnDefault: true }),
  );
  return (
    <>
      <output data-testid="value">{tier}</output>
      <button onClick={() => setTier("MID")}>MID</button>
      <button onClick={() => setTier("ALL")}>ALL</button>
    </>
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("C-6 nuqs URL state — portfolio tab", () => {
  it("renders default 'holdings' when ?tab is absent", () => {
    render(<TabHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("holdings");
  });

  it("hydrates from ?tab=transactions on mount", () => {
    render(<TabHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?tab=transactions">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("transactions");
  });

  it("writes ?tab=watchlist on click and clears on default", async () => {
    const onUrl: OnUrlUpdateFunction = vi.fn();
    render(<TabHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="" onUrlUpdate={onUrl}>
          {children}
        </NuqsTestingAdapter>
      ),
    });

    await userEvent.click(screen.getByText("wl"));
    expect(onUrl).toHaveBeenLastCalledWith(
      expect.objectContaining({
        queryString: expect.stringContaining("tab=watchlist"),
      }),
    );

    // Switching back to the default ("holdings") must drop the param so the
    // canonical URL stays clean — clearOnDefault contract.
    await userEvent.click(screen.getByText("hd"));
    expect(onUrl).toHaveBeenLastCalledWith(
      expect.objectContaining({ queryString: "" }),
    );
  });

  it("rejects an unknown ?tab value and falls back to default", () => {
    render(<TabHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?tab=garbage">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("holdings");
  });
});

describe("C-6 nuqs URL state — equity period", () => {
  it("hydrates from ?period=1Y", () => {
    render(<PeriodHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?period=1Y">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("1Y");
  });

  it("clears the param on returning to default 3M", async () => {
    const onUrl: OnUrlUpdateFunction = vi.fn();
    render(<PeriodHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?period=1Y" onUrlUpdate={onUrl}>
          {children}
        </NuqsTestingAdapter>
      ),
    });
    await userEvent.click(screen.getByText("3M"));
    expect(onUrl).toHaveBeenLastCalledWith(
      expect.objectContaining({ queryString: "" }),
    );
  });
});

describe("C-6 nuqs URL state — screener cap tier", () => {
  it("hydrates from ?capTier=MID", () => {
    render(<CapTierHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?capTier=MID">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("MID");
  });

  it("rejects unknown values and falls back to ALL", () => {
    render(<CapTierHarness />, {
      wrapper: ({ children }) => (
        <NuqsTestingAdapter searchParams="?capTier=NOTREAL">
          {children}
        </NuqsTestingAdapter>
      ),
    });
    expect(screen.getByTestId("value").textContent).toBe("ALL");
  });
});
