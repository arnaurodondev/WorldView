/**
 * __tests__/data-timestamp.test.tsx — Unit tests for DataTimestamp
 *
 * WHY THIS EXISTS: pins the freshness colour bands and relative-time
 * formatting so the dashboard never shows misleading "Just now" colour on
 * stale data (or vice-versa).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTimestamp } from "@/components/ui/data-timestamp";

describe("DataTimestamp", () => {
  // WHY fake timers + a fixed "now": the colour band depends on age which
  // depends on Date.now(). Pinning both removes flake from real-time clock drift.
  const NOW = new Date("2026-04-28T12:00:00Z");

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows 'Just now' for sub-30s ages with positive colour", () => {
    const ts = new Date(NOW.getTime() - 10_000); // 10s ago
    render(<DataTimestamp timestamp={ts} />);
    const span = screen.getByText("Just now");
    expect(span.className).toContain("text-positive");
  });

  it("shows 'Nm ago' for under-1h ages and uses warning colour at 5–30 min", () => {
    const ts = new Date(NOW.getTime() - 10 * 60_000); // 10 min ago
    render(<DataTimestamp timestamp={ts} />);
    const span = screen.getByText("10m ago");
    expect(span.className).toContain("text-warning");
  });

  it("uses positive colour under 5 minutes", () => {
    const ts = new Date(NOW.getTime() - 2 * 60_000); // 2 min ago
    render(<DataTimestamp timestamp={ts} />);
    const span = screen.getByText("2m ago");
    expect(span.className).toContain("text-positive");
  });

  it("uses muted colour between 30m and 1h", () => {
    const ts = new Date(NOW.getTime() - 45 * 60_000); // 45 min ago
    render(<DataTimestamp timestamp={ts} />);
    const span = screen.getByText("45m ago");
    expect(span.className).toContain("text-muted-foreground");
  });

  it("formats hours past the 60-minute boundary", () => {
    const ts = new Date(NOW.getTime() - 3 * 3_600_000); // 3 hours ago
    render(<DataTimestamp timestamp={ts} />);
    expect(screen.getByText("3h ago")).toBeInTheDocument();
  });

  it("absolute format renders YYYY-MM-DD HH:MM UTC", () => {
    const ts = new Date("2026-04-28T10:32:00Z");
    render(<DataTimestamp timestamp={ts} format="absolute" />);
    expect(screen.getByText("2026-04-28 10:32 UTC")).toBeInTheDocument();
  });

  it("accepts ISO string timestamps", () => {
    render(<DataTimestamp timestamp="2026-04-28T11:55:00Z" />);
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });

  it("title attribute always carries absolute time for hover", () => {
    const ts = new Date("2026-04-28T11:55:00Z");
    render(<DataTimestamp timestamp={ts} />);
    const span = screen.getByText("5m ago");
    expect(span.getAttribute("title")).toBe("2026-04-28 11:55 UTC");
  });
});
