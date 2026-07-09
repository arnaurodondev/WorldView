/**
 * hooks/__tests__/usePortfolioMode.test.tsx — PLAN-0122 W-A (T-A-A-01).
 *
 * WHY THIS EXISTS: `usePortfolioMode` is the SINGLE source of the portfolio
 * detail level and the anchor of the "rendering gate, never a fork" design. Its
 * three-way precedence (URL → localStorage → flag default) and dual-sink write
 * are subtle, so they are pinned directly here — following the isolated-harness
 * pattern used by `__tests__/url-state.test.tsx` (test the hook, not a page).
 *
 * The rollout flag `PORTFOLIO_SIMPLE_DEFAULT` is mocked via a mutable holder so
 * a single file can exercise BOTH the `false` (W-A) and `true` (W-B) branches of
 * the default resolution.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  NuqsTestingAdapter,
  type OnUrlUpdateFunction,
} from "nuqs/adapters/testing";

// ── Rollout-flag mock ────────────────────────────────────────────────────────
// WHY a hoisted mutable holder + getter: vi.mock is hoisted above imports, so the
// factory must not close over a normal `let`. `vi.hoisted` gives a holder that is
// safe to reference. The getter is re-read on every property access, and the hook
// reads PORTFOLIO_SIMPLE_DEFAULT inside its body on each render — so flipping
// `flag.value` between tests changes the resolved default without a re-import.
const flag = vi.hoisted(() => ({ value: false }));
vi.mock("@/lib/portfolio/mode-flag", () => ({
  get PORTFOLIO_SIMPLE_DEFAULT() {
    return flag.value;
  },
}));

import {
  usePortfolioMode,
  PORTFOLIO_MODE_STORAGE_KEY,
} from "@/hooks/usePortfolioMode";

// ── Harness ──────────────────────────────────────────────────────────────────
// Renders the resolved mode + a button that flips it to "advanced", so tests can
// observe both reads and writes through the DOM (the url-state.test.tsx pattern).
function ModeHarness() {
  const { mode, setMode } = usePortfolioMode();
  return (
    <>
      <output data-testid="mode">{mode}</output>
      <button onClick={() => setMode("advanced")}>to-advanced</button>
      <button onClick={() => setMode("simple")}>to-simple</button>
    </>
  );
}

function renderHarness(searchParams = "", onUrlUpdate?: OnUrlUpdateFunction) {
  return render(<ModeHarness />, {
    wrapper: ({ children }) => (
      <NuqsTestingAdapter searchParams={searchParams} onUrlUpdate={onUrlUpdate}>
        {children}
      </NuqsTestingAdapter>
    ),
  });
}

// ── Setup ────────────────────────────────────────────────────────────────────
beforeEach(() => {
  // Each test starts from a clean localStorage + the production default flag.
  window.localStorage.clear();
  flag.value = false;
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("usePortfolioMode — default follows the rollout flag", () => {
  it("test_mode_default_follows_flag: flag false → advanced; flag true → simple", async () => {
    // W-A production value: no URL, no localStorage → Advanced (today's layout).
    const { unmount } = renderHarness("");
    expect(screen.getByTestId("mode").textContent).toBe("advanced");
    unmount();

    // W-B value: flipping the flag makes an unset user resolve to Simple.
    flag.value = true;
    renderHarness("");
    expect(screen.getByTestId("mode").textContent).toBe("simple");
  });
});

describe("usePortfolioMode — precedence", () => {
  it("test_mode_url_param_wins: ?mode=advanced beats a localStorage 'simple'", () => {
    // A shared/deep link must render what the link says regardless of the sticky
    // local choice — URL is the highest-precedence source.
    window.localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, "simple");
    renderHarness("?mode=advanced");
    expect(screen.getByTestId("mode").textContent).toBe("advanced");
  });

  it("test_mode_localstorage_when_no_url: localStorage wins over the flag default", async () => {
    // Flag default is "advanced" (false); a sticky "simple" must override it.
    // localStorage is read in an effect, so assert after reconcile via waitFor.
    window.localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, "simple");
    renderHarness("");
    await waitFor(() =>
      expect(screen.getByTestId("mode").textContent).toBe("simple"),
    );
  });

  it("test_mode_ssr_first_render_uses_default_not_localstorage: stored value does not apply before the reconcile effect (QA item 9)", async () => {
    // SSR-safety invariant: the server render and the FIRST client render must NOT
    // read localStorage (that would desync the two renders and trigger a hydration
    // mismatch). Guards against a regression that reads storage during render.
    //
    // WHY a render-recorder (not a synchronous DOM read): Testing Library's
    // `render` wraps in act(), which flushes useEffect before we could query the
    // DOM — so the post-reconcile value is all we'd see. Instead we record the
    // resolved mode on EVERY render pass into an external array; index 0 is the
    // first (pre-effect) render, which must equal the flag default even though a
    // sticky "simple" is in localStorage.
    const seen: string[] = [];
    function RecordingHarness() {
      const { mode } = usePortfolioMode();
      seen.push(mode);
      return <output data-testid="mode">{mode}</output>;
    }
    window.localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, "simple"); // flag default is "advanced"
    render(
      <NuqsTestingAdapter searchParams="">
        <RecordingHarness />
      </NuqsTestingAdapter>,
    );
    // First render used the default, NOT the sticky localStorage value.
    expect(seen[0]).toBe("advanced");
    // The post-paint effect then reconciles to the sticky value.
    await waitFor(() =>
      expect(screen.getByTestId("mode").textContent).toBe("simple"),
    );
    expect(seen[seen.length - 1]).toBe("simple");
  });
});

describe("usePortfolioMode — setMode writes both sinks", () => {
  it("test_setmode_writes_both_sinks: sets localStorage AND the ?mode URL param", async () => {
    const onUrl: OnUrlUpdateFunction = vi.fn();
    renderHarness("", onUrl);

    await userEvent.click(screen.getByText("to-advanced"));

    // Sticky sink: localStorage persists the choice.
    expect(window.localStorage.getItem(PORTFOLIO_MODE_STORAGE_KEY)).toBe(
      "advanced",
    );
    // Shareable sink: the URL param is written (kept even though it is a
    // concrete literal, so the view stays shareable).
    expect(onUrl).toHaveBeenLastCalledWith(
      expect.objectContaining({
        queryString: expect.stringContaining("mode=advanced"),
      }),
    );
    // And the resolved mode reflects the write immediately (no reload needed).
    expect(screen.getByTestId("mode").textContent).toBe("advanced");
  });

  it("test_mode_corrupted_localstorage_falls_back_to_default: junk value is ignored", async () => {
    // Defensive: a legacy/garbage value must not crash or leak through — it
    // falls back to the flag default ("advanced").
    window.localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, "not-a-mode");
    renderHarness("");
    await waitFor(() =>
      expect(screen.getByTestId("mode").textContent).toBe("advanced"),
    );
  });
});
