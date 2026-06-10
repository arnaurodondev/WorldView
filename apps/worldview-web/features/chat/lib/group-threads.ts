/**
 * features/chat/lib/group-threads.ts — date-bucket grouping for the thread
 * sidebar (Round 1 Foundation — chat history sidebar).
 *
 * WHY GROUPING: a flat list of 40 threads forces the analyst to read every
 * timestamp to find "the thread from yesterday". Date buckets (Today /
 * Yesterday / Previous 7 days / Older) are the convention users already know
 * from ChatGPT/Claude/Slack — recognition over recall.
 *
 * WHY A PURE FUNCTION IN lib/ (not inline in the page): the bucketing edge
 * cases (midnight boundaries, invalid dates, missing updated_at) deserve
 * direct unit tests without rendering the whole chat page. The page just
 * maps over the returned groups.
 *
 * WHY LOCAL TIME (not UTC): "Today" must match the user's wall clock — a
 * thread from 23:50 local yesterday must NOT appear under Today just because
 * it is the same UTC day. We compare calendar days via local Date fields.
 */

import type { Thread } from "@/types/api";

/** Ordered bucket labels — render order is the array order below. */
export const THREAD_GROUP_ORDER = [
  "Today",
  "Yesterday",
  "Previous 7 days",
  "Older",
] as const;

export type ThreadGroupLabel = (typeof THREAD_GROUP_ORDER)[number];

export interface ThreadGroup {
  label: ThreadGroupLabel;
  threads: Thread[];
}

/**
 * startOfLocalDay — midnight of the given date in the user's timezone.
 * Used as the boundary marker for "Today" / "Yesterday" comparisons.
 */
function startOfLocalDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Pick the best activity timestamp for a thread; null when unparsable. */
function threadTimestamp(thread: Thread): number | null {
  for (const candidate of [thread.updated_at, thread.created_at]) {
    if (!candidate) continue;
    const t = new Date(candidate).getTime();
    if (!Number.isNaN(t)) return t;
  }
  return null;
}

/**
 * groupThreadsByDate — bucket threads into Today / Yesterday / Previous 7
 * days / Older, preserving the input order WITHIN each bucket (the API
 * already returns most-recent-first; we must not reshuffle).
 *
 * Threads with no parsable timestamp land in "Older" — they are legacy rows
 * and "Older" is the only honest claim we can make about them.
 *
 * Empty buckets are omitted so the sidebar never renders a bare header.
 *
 * @param now — injectable for tests (defaults to the real clock).
 */
export function groupThreadsByDate(
  threads: Thread[],
  now: Date = new Date(),
): ThreadGroup[] {
  const todayStart = startOfLocalDay(now);
  const DAY_MS = 24 * 60 * 60 * 1000;
  const yesterdayStart = todayStart - DAY_MS;
  // "Previous 7 days" = the 7 calendar days BEFORE yesterday's bucket starts
  // would double-count; spec-wise we mean: newer than 7 days ago but older
  // than yesterday. 7 days back from today's midnight is the cutoff.
  const weekStart = todayStart - 7 * DAY_MS;

  const buckets: Record<ThreadGroupLabel, Thread[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };

  for (const thread of threads) {
    const t = threadTimestamp(thread);
    if (t === null) {
      buckets.Older.push(thread);
    } else if (t >= todayStart) {
      buckets.Today.push(thread);
    } else if (t >= yesterdayStart) {
      buckets.Yesterday.push(thread);
    } else if (t >= weekStart) {
      buckets["Previous 7 days"].push(thread);
    } else {
      buckets.Older.push(thread);
    }
  }

  return THREAD_GROUP_ORDER.filter((label) => buckets[label].length > 0).map(
    (label) => ({ label, threads: buckets[label] }),
  );
}
