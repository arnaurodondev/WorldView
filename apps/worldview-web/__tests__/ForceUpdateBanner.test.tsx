/**
 * __tests__/ForceUpdateBanner.test.tsx — Unit tests for the build-version
 * mismatch banner.
 *
 * Coverage:
 *   - banner stays hidden when /api/version always returns the same buildId
 *   - banner appears once a poll observes a different buildId
 *   - banner stays hidden if /api/version errors transiently
 *   - the visible banner offers a Reload action that triggers
 *     window.location.reload
 *
 * NOTE: tests use REAL timers + a tiny `pollIntervalMs` so we don't need to
 * orchestrate fake-timer / fetch-microtask interactions (which are flaky
 * under jsdom + Vitest + the Vite plugin).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ForceUpdateBanner } from "@/components/shell/ForceUpdateBanner";

const ok = (body: unknown) =>
  ({ ok: true, json: async () => body }) as unknown as Response;
const fail = () =>
  ({ ok: false, json: async () => ({}) }) as unknown as Response;

const POLL = 15; // ms — small so tests finish fast under real timers

describe("<ForceUpdateBanner />", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch") as unknown as ReturnType<
      typeof vi.spyOn
    >;
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("renders nothing when buildId never changes", async () => {
    fetchSpy.mockResolvedValue(ok({ buildId: "abc123" }));

    render(<ForceUpdateBanner pollIntervalMs={POLL} />);

    // Wait long enough for several polls to fire — banner must stay hidden.
    await new Promise((r) => setTimeout(r, POLL * 4));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows the banner when /api/version returns a different buildId", async () => {
    fetchSpy
      .mockResolvedValueOnce(ok({ buildId: "old-sha" }))
      .mockResolvedValue(ok({ buildId: "new-sha" }));

    render(<ForceUpdateBanner pollIntervalMs={POLL} />);

    await waitFor(
      () => {
        expect(screen.getByRole("status")).toBeInTheDocument();
      },
      { timeout: 1000, interval: 10 },
    );
    expect(screen.getByText(/new version available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  });

  it("does not show the banner on transient fetch failures", async () => {
    // Baseline succeeds, then every later poll fails. Without a CONFIRMED
    // mismatch the banner must NOT alarm the user.
    fetchSpy.mockResolvedValueOnce(ok({ buildId: "abc" })).mockResolvedValue(fail());

    render(<ForceUpdateBanner pollIntervalMs={POLL} />);

    await new Promise((r) => setTimeout(r, POLL * 5));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("Reload button calls window.location.reload", async () => {
    fetchSpy
      .mockResolvedValueOnce(ok({ buildId: "v1" }))
      .mockResolvedValue(ok({ buildId: "v2" }));

    // jsdom's window.location.reload is read-only; spy via defineProperty to
    // avoid triggering a real navigation that would tear down jsdom state.
    const reloadMock = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload: reloadMock },
    });

    render(<ForceUpdateBanner pollIntervalMs={POLL} />);

    const reloadBtn = await screen.findByRole(
      "button",
      { name: /reload/i },
      { timeout: 1000 },
    );
    await userEvent.click(reloadBtn);
    expect(reloadMock).toHaveBeenCalledTimes(1);

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  // QA F-013 (2026-05-21): W1.1 G-001 relocated the banner from a
  // fixed bottom-right chip to an in-flow h-6 sticky notice above the
  // TopBar. Without these assertions, someone could re-introduce the
  // old `fixed bottom-7 right-3 rounded-[2px]` layout and the F1
  // sharp-corner / above-shell-chrome contract would silently regress.
  describe("layout (W1.1 G-001)", () => {
    it("renders as h-6 in-flow (NOT fixed bottom-right) when active", async () => {
      fetchSpy
        .mockResolvedValueOnce(ok({ buildId: "v1" }))
        .mockResolvedValue(ok({ buildId: "v2" }));
      render(<ForceUpdateBanner pollIntervalMs={POLL} />);
      const banner = await waitFor(() => screen.getByRole("status"));
      expect(banner.className).toMatch(/\bh-6\b/);
      expect(banner.className).not.toMatch(/\bfixed\b/);
      expect(banner.className).not.toMatch(/bottom-7|right-3/);
    });

    it("carries no border-radius (F1 sharp-corner lock — C-04)", async () => {
      fetchSpy
        .mockResolvedValueOnce(ok({ buildId: "v1" }))
        .mockResolvedValue(ok({ buildId: "v2" }));
      render(<ForceUpdateBanner pollIntervalMs={POLL} />);
      const banner = await waitFor(() => screen.getByRole("status"));
      expect(banner.className).not.toMatch(/rounded-\[2px\]/);
      expect(banner.className).not.toMatch(/rounded-(sm|md|lg|xl|2xl)/);
    });
  });
});
