/**
 * app/(app)/watchlists/__tests__/watchlists-columns.test.ts
 *
 * WHY: Unit tests for watchlistHubColumns, watchlistMembersColumns, and the
 * formatRelativeTime helper. These run as pure unit tests (no DOM mount).
 *
 * PLAN-0059 F-1 — DataTable migration tests (≥3 per migrated table).
 * Tests cover both watchlists tables (hub + members) = Table 4 in the migration.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { watchlistHubColumns, formatRelativeTime } from "../hub-columns";
import { watchlistMembersColumns } from "../members-columns";

afterEach(() => {
  vi.restoreAllMocks();
});

// ── watchlistHubColumns ──────────────────────────────────────────────────────

describe("watchlistHubColumns", () => {
  it("has exactly 4 columns", () => {
    expect(watchlistHubColumns).toHaveLength(4);
  });

  it("column ids match expected order", () => {
    const ids = watchlistHubColumns.map((c) => c.id);
    expect(ids).toEqual(["name", "member_count", "updated_at", "created_at"]);
  });

  it("all columns have accessorKey (direct field access)", () => {
    for (const col of watchlistHubColumns) {
      expect(
        (col as { accessorKey?: string }).accessorKey,
        `column "${col.id}" should have accessorKey`,
      ).toBeDefined();
    }
  });
});

// ── watchlistMembersColumns ──────────────────────────────────────────────────

describe("watchlistMembersColumns", () => {
  it("has exactly 4 columns", () => {
    expect(watchlistMembersColumns).toHaveLength(4);
  });

  it("column ids match expected order", () => {
    const ids = watchlistMembersColumns.map((c) => c.id);
    expect(ids).toEqual(["ticker", "name", "resolution", "added_at"]);
  });

  it("all columns have accessorKey (direct field access)", () => {
    for (const col of watchlistMembersColumns) {
      expect(
        (col as { accessorKey?: string }).accessorKey,
        `column "${col.id}" should have accessorKey`,
      ).toBeDefined();
    }
  });
});

// ── formatRelativeTime ───────────────────────────────────────────────────────

describe("formatRelativeTime", () => {
  it("returns 'just now' for timestamps within the last minute", () => {
    const iso = new Date(Date.now() - 30_000).toISOString();
    expect(formatRelativeTime(iso)).toBe("just now");
  });

  it("returns minutes ago for timestamps 1–59 minutes old", () => {
    const iso = new Date(Date.now() - 15 * 60_000).toISOString();
    expect(formatRelativeTime(iso)).toBe("15m ago");
  });

  it("returns hours ago for timestamps 1–23 hours old", () => {
    const iso = new Date(Date.now() - 3 * 3600_000).toISOString();
    expect(formatRelativeTime(iso)).toBe("3h ago");
  });

  it("returns days ago for timestamps 1–6 days old", () => {
    const iso = new Date(Date.now() - 2 * 86_400_000).toISOString();
    expect(formatRelativeTime(iso)).toBe("2d ago");
  });

  it("returns a formatted date for timestamps older than 7 days", () => {
    // Use a fixed date so the test isn't time-sensitive.
    const iso = "2026-01-01T12:00:00Z"; // well over 7 days ago
    const result = formatRelativeTime(iso);
    // Expect something like "Jan 1" — not a relative "Nd ago" format.
    expect(result).toMatch(/^[A-Z][a-z]+ \d+$/);
  });
});
