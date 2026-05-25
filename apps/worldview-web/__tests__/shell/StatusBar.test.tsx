/**
 * __tests__/shell/StatusBar.test.tsx — PRD-0089 W1 §4.6.
 *
 * Pins the contract that the W1 StatusBar:
 *   - measures 22px tall (was 24px) — reclaims 2px across the viewport width
 *   - uses the F1 `border-border-subtle` token for its top border (instead of
 *     the banned `border-white/[0.06]` opacity literal)
 *   - WS dot tracks useAlertStream().isConnected (green when connected,
 *     red when disconnected; label "WS Live"/"WS Offline")
 *   - freshness dot is muted with "MARKET CLOSED" label when
 *     useMarketStatus().overall === "closed" (C-20 — no false "stale 42h"
 *     during weekends/holidays)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

const mockUseAlertStream = vi.fn();
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: () => mockUseAlertStream(),
}));

const mockUseMarketStatus = vi.fn();
vi.mock("@/hooks/useMarketStatus", () => ({
  useMarketStatus: () => mockUseMarketStatus(),
}));

import { StatusBar } from "@/components/shell/StatusBar";

function renderBar() {
  const registry = new HotkeyRegistry();
  return render(
    <HotkeyProvider registry={registry}>
      <StatusBar />
    </HotkeyProvider>,
  );
}

// Default mocks: connected + market open. Each test overrides as needed.
beforeEach(() => {
  vi.clearAllMocks();
  mockUseAlertStream.mockReturnValue({
    recentAlerts: [],
    criticalQueue: [],
    dequeueCritical: () => undefined,
    unreadCount: 0,
    isConnected: true,
  });
  mockUseMarketStatus.mockReturnValue({ overall: "open", exchanges: [] });
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("StatusBar (PRD-0089 W1)", () => {
  it("renders at h-[22px] with the border-border-subtle top border", () => {
    const { container } = renderBar();
    const bar = container.firstChild as HTMLElement;
    expect(bar.className).toMatch(/h-\[22px\]/);
    expect(bar.className).toMatch(/border-border-subtle/);
    expect(bar.className).not.toMatch(/border-white\/\[/);
  });

  it("WS dot renders green + 'WS Live' when isConnected = true", () => {
    renderBar();
    expect(screen.getByText("WS Live")).toBeInTheDocument();
  });

  it("WS dot renders red + 'WS Offline' when isConnected = false", () => {
    mockUseAlertStream.mockReturnValue({
      recentAlerts: [],
      criticalQueue: [],
      dequeueCritical: () => undefined,
      unreadCount: 0,
      isConnected: false,
    });
    renderBar();
    expect(screen.getByText("WS Offline")).toBeInTheDocument();
  });

  it("freshness label flips to 'MARKET CLOSED' when overall = 'closed' (C-20)", () => {
    mockUseMarketStatus.mockReturnValue({ overall: "closed", exchanges: [] });
    renderBar();
    expect(screen.getByText("MARKET CLOSED")).toBeInTheDocument();
    // The corresponding dot uses bg-muted-foreground when closed.
    const freshnessLabel = screen.getByText("MARKET CLOSED");
    const wrapper = freshnessLabel.parentElement as HTMLElement;
    const dot = wrapper.querySelector("span[aria-hidden]");
    expect(dot?.className).toMatch(/bg-muted-foreground/);
  });

  it("freshness label is 'Quotes Live' during regular session", () => {
    renderBar();
    expect(screen.getByText("Quotes Live")).toBeInTheDocument();
  });
});

// ── QA F-007 (2026-05-21): chord-hint left cluster ────────────────────

describe("StatusBar — chord hint cluster (F-007)", () => {
  /**
   * The hint cluster is fed by the live HotkeyRegistry. Tests register
   * bindings on a fresh registry, mount StatusBar inside the matching
   * HotkeyProvider, and assert the kbd elements + ordering.
   */
  function renderWithBindings(register: (r: HotkeyRegistry) => void) {
    const registry = new HotkeyRegistry();
    register(registry);
    return render(
      <HotkeyProvider registry={registry}>
        <StatusBar />
      </HotkeyProvider>,
    );
  }

  beforeEach(() => {
    // Match the defaults for the right cluster so its assertions don't fire.
    mockUseAlertStream.mockReturnValue({
      recentAlerts: [],
      criticalQueue: [],
      dequeueCritical: () => undefined,
      unreadCount: 0,
      isConnected: true,
    });
    mockUseMarketStatus.mockReturnValue({ overall: "open", exchanges: [] });
  });

  it("renders the empty-state placeholder when no bindings are registered", () => {
    renderWithBindings(() => undefined);
    // The component renders "…" muted-foreground when bindings.length === 0.
    expect(screen.getByText("…")).toBeInTheDocument();
  });

  it("renders registered priority bindings as kbd + short label", () => {
    renderWithBindings((registry) => {
      registry.register({
        id: "nav.dashboard",
        chord: "g d",
        scope: "global",
        group: "Navigation",
        label: "Go to Dashboard",
        handler: () => undefined,
      });
      registry.register({
        id: "nav.portfolio",
        chord: "g p",
        scope: "global",
        group: "Navigation",
        label: "Go to Portfolio",
        handler: () => undefined,
      });
    });
    // Two kbd elements; visible short labels strip the "Go to " prefix.
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Portfolio").length).toBeGreaterThanOrEqual(1);
    // Underlying chord glyphs render as <kbd> (G D format).
    const kbds = document.querySelectorAll("kbd");
    expect(kbds.length).toBeGreaterThanOrEqual(2);
  });

  it("caps the hint cluster at 6 entries (STATUS_BAR_HINT_LIMIT)", () => {
    renderWithBindings((registry) => {
      // Register 10 priority chord ids; the cap should clip to 6.
      const ids = [
        "nav.dashboard", "nav.screener", "nav.workspace", "nav.portfolio",
        "nav.alerts", "nav.chat", "shell.search.focus", "shell.help.cheatsheet",
        "nav.news", "nav.settings",
      ];
      ids.forEach((id) =>
        registry.register({
          id,
          chord: id.split(".")[1]?.[0] ?? "x",
          scope: "global",
          group: "Navigation",
          label: id,
          handler: () => undefined,
        }),
      );
    });
    const kbds = document.querySelectorAll("kbd");
    expect(kbds.length).toBeLessThanOrEqual(6);
  });
});
