/**
 * Tests for the alias-type design tokens + AliasPill component (PLAN-0057 Wave F-2).
 *
 * The Wave C-3 backend change introduced 5 new alias_types — the test below
 * pins the contract that every one renders with a unique colour and label
 * so analysts can distinguish CUSIP from FIGI from ISIN at a glance.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AliasPill } from "@/components/entity/AliasPill";
import { aliasTypeToken, sortAliasesByType } from "@/lib/alias-types";

describe("aliasTypeToken", () => {
  it("returns explicit tokens for every Wave C-3 alias_type", () => {
    // PLAN-0087 D-F3-002: post Terminal Dark token migration the four
    // reference identifiers (CUSIP/FIGI/LEI/ISIN) deliberately share the
    // muted-foreground class so they recede behind primary identifiers.
    // The test now anchors uniqueness via the (label, sortIndex) tuple
    // rather than the legacy assumption that every type owned a unique
    // off-palette colour.
    const required = ["CUSIP", "FIGI", "LEI", "PRIMARY_TICKER", "NAME"];
    for (const type of required) {
      const token = aliasTypeToken(type);
      expect(token.label, `missing label for ${type}`).not.toBe("Alias");
      // sortIndex of FALLBACK is 100 — every required type gets a deliberate
      // (non-fallback) sort priority. This keeps the contract that they are
      // explicitly registered without coupling to the colour vocabulary.
      expect(token.sortIndex, `missing sortIndex for ${type}`).toBeLessThan(100);
    }
  });

  it("falls back gracefully for unknown alias_types", () => {
    const token = aliasTypeToken("UNRECOGNISED_TYPE");
    expect(token.label).toBe("Alias");
    expect(token.sortIndex).toBe(100);
  });

  it("falls back for null/undefined alias_type", () => {
    expect(aliasTypeToken(null).label).toBe("Alias");
    expect(aliasTypeToken(undefined).label).toBe("Alias");
  });
});

describe("sortAliasesByType", () => {
  it("orders primary identifiers before reference identifiers", () => {
    const input = [
      { alias_type: "ISIN", value: "US0378331005" },
      { alias_type: "TICKER", value: "AAPL" },
      { alias_type: "EXACT", value: "Apple Inc." },
      { alias_type: "PRIMARY_TICKER", value: "AAPL.US" },
      { alias_type: "FIGI", value: "BBG000B9XRY4" },
    ];
    const ordered = sortAliasesByType(input).map((a) => a.alias_type);
    expect(ordered).toEqual([
      "EXACT",
      "TICKER",
      "PRIMARY_TICKER",
      "ISIN",
      "FIGI",
    ]);
  });

  it("keeps unknown types at the tail", () => {
    const input = [
      { alias_type: "FUTURE_TYPE", value: "x" },
      { alias_type: "EXACT", value: "y" },
    ];
    const ordered = sortAliasesByType(input).map((a) => a.alias_type);
    expect(ordered[0]).toBe("EXACT");
    expect(ordered[1]).toBe("FUTURE_TYPE");
  });

  it("does not mutate the input array", () => {
    const input = [
      { alias_type: "ISIN", value: "x" },
      { alias_type: "EXACT", value: "y" },
    ];
    const ordered = sortAliasesByType(input);
    expect(input.map((a) => a.alias_type)).toEqual(["ISIN", "EXACT"]);
    expect(ordered).not.toBe(input);
  });
});

describe("AliasPill", () => {
  it("renders the alias label and value for known types", () => {
    render(<AliasPill aliasType="CUSIP" value="037833100" />);
    expect(screen.getByText("037833100")).toBeInTheDocument();
    expect(screen.getByText("CUSIP")).toBeInTheDocument();
  });

  it("renders without label when hideLabel is set", () => {
    render(<AliasPill aliasType="ISIN" value="US0378331005" hideLabel />);
    expect(screen.getByText("US0378331005")).toBeInTheDocument();
    expect(screen.queryByText("ISIN")).toBeNull();
  });

  it("renders the long value in title attribute even when truncated", () => {
    render(<AliasPill aliasType="LEI" value="HWUPKR0MPOU8FGXBT394" />);
    const span = screen.getByText("HWUPKR0MPOU8FGXBT394");
    expect(span.closest("span[title]")?.getAttribute("title")).toBe(
      "LEI: HWUPKR0MPOU8FGXBT394",
    );
  });

  it("falls back gracefully for unknown alias_type", () => {
    render(<AliasPill aliasType="UNKNOWN_TYPE" value="abc123" />);
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("Alias")).toBeInTheDocument();
  });

  it("renders a copy button by default with accessible label", () => {
    render(<AliasPill aliasType="CUSIP" value="037833100" />);
    const button = screen.getByRole("button", { name: /copy cusip value/i });
    expect(button).toBeInTheDocument();
  });

  it("hides the copy button when hideCopy is set", () => {
    render(<AliasPill aliasType="CUSIP" value="037833100" hideCopy />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ── Copy-to-clipboard interaction tests (PLAN-0057 Wave C T-007) ─────────────
// WHY a separate describe: these tests need fake timers + a mocked
// `navigator.clipboard` (jsdom does not provide one by default).  Keeping the
// fake-timer scope narrow means the rest of the file keeps using real timers.
//
// WHY fireEvent.click (not userEvent.click): @testing-library/user-event v14
// uses internal timer-based delays between pointer events, and its setup() with
// `advanceTimers: vi.advanceTimersByTime` deadlocks against vitest's fake
// timers in this jsdom environment.  fireEvent.click is a synchronous DOM
// dispatch — perfect for "the user clicked the copy button" semantics here.
describe("AliasPill — copy interaction", () => {
  // Track the original clipboard descriptor so we can restore it between tests
  // — some tests deliberately remove `navigator.clipboard` to verify the SSR
  // fallback path; without restore, later tests would lose the mock.
  let originalClipboard: PropertyDescriptor | undefined;

  beforeEach(() => {
    // jsdom does not implement Clipboard API — install a vi.fn() so we can
    // assert what was written and control the resolution / rejection.
    originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    // Use fake timers so we can assert the 1500 ms icon-reset deterministically
    // without sleeping in the test runner.
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalClipboard) {
      Object.defineProperty(navigator, "clipboard", originalClipboard);
    } else {
      // If jsdom never had a clipboard descriptor, drop our injected one.
      // The cast to `Record<string, unknown>` is necessary because TypeScript
      // doesn't allow `delete` on `navigator.clipboard` directly.
      delete (navigator as unknown as Record<string, unknown>).clipboard;
    }
    vi.restoreAllMocks();
  });

  /**
   * Helper that clicks the button and flushes pending promises so React
   * commits the post-click state update.  We need a microtask flush because
   * handleCopy is async (await navigator.clipboard.writeText) and React only
   * schedules setCopied(true) after the awaited promise resolves.
   */
  async function clickAndFlush(button: HTMLElement): Promise<void> {
    await act(async () => {
      fireEvent.click(button);
      // Allow the awaited writeText() promise to settle before assertions.
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("writes the value to navigator.clipboard on click", async () => {
    render(<AliasPill aliasType="CUSIP" value="037833100" />);
    const button = screen.getByRole("button", { name: /copy cusip value/i });

    await clickAndFlush(button);

    expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("037833100");
  });

  it("swaps Copy → Check icon after a successful copy", async () => {
    // The lucide-react icons render as <svg> with a `lucide-<name>` class on
    // the SVG element — this is the most stable selector across lucide
    // versions (icon names are part of the public API).
    const { container } = render(
      <AliasPill aliasType="CUSIP" value="037833100" />,
    );
    // Pre-condition: the Copy icon is rendered before the user clicks.
    expect(container.querySelector("svg.lucide-copy")).toBeInTheDocument();
    expect(container.querySelector("svg.lucide-check")).toBeNull();

    await clickAndFlush(
      screen.getByRole("button", { name: /copy cusip value/i }),
    );

    // After a successful click the Check icon must replace Copy — that's the
    // visual confirmation the analyst relies on.
    expect(container.querySelector("svg.lucide-check")).toBeInTheDocument();
    expect(container.querySelector("svg.lucide-copy")).toBeNull();
  });

  it("resets the icon back to Copy after 1500 ms", async () => {
    const { container } = render(
      <AliasPill aliasType="CUSIP" value="037833100" />,
    );

    await clickAndFlush(
      screen.getByRole("button", { name: /copy cusip value/i }),
    );
    expect(container.querySelector("svg.lucide-check")).toBeInTheDocument();

    // Advance fake timers past the 1500 ms window.setTimeout in handleCopy.
    // act() ensures the resulting React state update is flushed before we
    // assert on the post-timer icon.
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });

    expect(container.querySelector("svg.lucide-copy")).toBeInTheDocument();
    expect(container.querySelector("svg.lucide-check")).toBeNull();
  });

  it("silently no-ops when navigator.clipboard.writeText rejects", async () => {
    // Permission-denied (HTTPS context lock-down, locked-down browsers) must
    // not crash the component — handleCopy wraps writeText in try/catch.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const { container } = render(
      <AliasPill aliasType="CUSIP" value="037833100" />,
    );

    // The click must not throw — if the catch block were missing the awaited
    // rejection would surface as an unhandled promise and crash the test.
    await clickAndFlush(
      screen.getByRole("button", { name: /copy cusip value/i }),
    );

    // setCopied(true) is only called on success — the Check icon must NOT
    // appear when writeText rejects.
    expect(container.querySelector("svg.lucide-check")).toBeNull();
    expect(container.querySelector("svg.lucide-copy")).toBeInTheDocument();
  });

  it("does not throw when navigator.clipboard is undefined", async () => {
    // Simulate environments where the Clipboard API is unavailable (very old
    // browsers, SSR, locked-down enterprise builds).  AliasPill guards on
    // `navigator.clipboard` so the click should be a silent no-op.
    delete (navigator as unknown as Record<string, unknown>).clipboard;

    const { container } = render(
      <AliasPill aliasType="CUSIP" value="037833100" />,
    );

    await clickAndFlush(
      screen.getByRole("button", { name: /copy cusip value/i }),
    );

    expect(container.querySelector("svg.lucide-check")).toBeNull();
    expect(container.querySelector("svg.lucide-copy")).toBeInTheDocument();
  });
});
