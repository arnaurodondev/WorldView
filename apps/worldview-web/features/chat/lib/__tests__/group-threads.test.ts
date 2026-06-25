/**
 * features/chat/lib/__tests__/group-threads.test.ts
 *
 * Round 1 Foundation — date bucketing for the chat history sidebar.
 * Pure-function tests with an injected `now` so midnight-boundary cases are
 * deterministic regardless of when CI runs.
 */

import { describe, expect, it } from "vitest";

import { groupThreadsByDate } from "../group-threads";
import type { Thread } from "@/types/api";

/** Minimal thread factory — only the fields the bucketing reads. */
function makeThread(id: string, updatedAt: string | null, createdAt = ""): Thread {
  return {
    thread_id: id,
    title: id,
    owner_id: "u1",
    messages: [],
    created_at: createdAt,
    updated_at: updatedAt as unknown as string,
  };
}

// Fixed reference clock: 2026-06-10 15:00 LOCAL time. Buckets are computed in
// local time (a 23:50-yesterday thread must not be "Today"), so we construct
// the date via local components, not an ISO-Z string.
const NOW = new Date(2026, 5, 10, 15, 0, 0);

/** Build a local-time ISO-ish string offset from NOW by `hours`. */
function hoursAgo(hours: number): string {
  return new Date(NOW.getTime() - hours * 3600_000).toISOString();
}

describe("groupThreadsByDate", () => {
  it("buckets threads into Today / Yesterday / Previous 7 days / Older", () => {
    const threads = [
      makeThread("t-today", hoursAgo(1)), // 14:00 today
      makeThread("t-yesterday", hoursAgo(20)), // 19:00 yesterday
      makeThread("t-week", hoursAgo(4 * 24)), // 4 days ago
      makeThread("t-older", hoursAgo(30 * 24)), // a month ago
    ];

    const groups = groupThreadsByDate(threads, NOW);

    expect(groups.map((g) => g.label)).toEqual([
      "Today",
      "Yesterday",
      "Previous 7 days",
      "Older",
    ]);
    expect(groups[0].threads.map((t) => t.thread_id)).toEqual(["t-today"]);
    expect(groups[1].threads.map((t) => t.thread_id)).toEqual(["t-yesterday"]);
    expect(groups[2].threads.map((t) => t.thread_id)).toEqual(["t-week"]);
    expect(groups[3].threads.map((t) => t.thread_id)).toEqual(["t-older"]);
  });

  it("omits empty buckets entirely (no bare headers)", () => {
    const groups = groupThreadsByDate([makeThread("only", hoursAgo(2))], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Today");
  });

  it("uses local midnight as the Today/Yesterday boundary", () => {
    // 23:50 yesterday local time — 15h10m before the 15:00 reference.
    const lateYesterday = new Date(2026, 5, 9, 23, 50).toISOString();
    // 00:10 today local time.
    const earlyToday = new Date(2026, 5, 10, 0, 10).toISOString();

    const groups = groupThreadsByDate(
      [makeThread("late-y", lateYesterday), makeThread("early-t", earlyToday)],
      NOW,
    );

    expect(groups.find((g) => g.label === "Today")?.threads[0].thread_id).toBe(
      "early-t",
    );
    expect(
      groups.find((g) => g.label === "Yesterday")?.threads[0].thread_id,
    ).toBe("late-y");
  });

  it("falls back to created_at when updated_at is missing, and to Older when both are unparsable", () => {
    const groups = groupThreadsByDate(
      [
        makeThread("via-created", null, hoursAgo(1)),
        makeThread("no-dates", null, ""),
        makeThread("garbage", "not-a-date", "also-not-a-date"),
      ],
      NOW,
    );

    expect(groups.find((g) => g.label === "Today")?.threads[0].thread_id).toBe(
      "via-created",
    );
    expect(groups.find((g) => g.label === "Older")?.threads.map((t) => t.thread_id)).toEqual([
      "no-dates",
      "garbage",
    ]);
  });

  it("preserves the input order within each bucket (API is most-recent-first)", () => {
    const groups = groupThreadsByDate(
      [
        makeThread("a", hoursAgo(1)),
        makeThread("b", hoursAgo(2)),
        makeThread("c", hoursAgo(3)),
      ],
      NOW,
    );
    expect(groups[0].threads.map((t) => t.thread_id)).toEqual(["a", "b", "c"]);
  });

  it("returns an empty array for an empty thread list (named empty state is the caller's job)", () => {
    expect(groupThreadsByDate([], NOW)).toEqual([]);
  });
});
