/**
 * features/chat/lib/__tests__/conversation-derive.test.ts
 *
 * Wave 2 (frontend-rework sprint) — pure conversation-level derivations
 * behind the context rail's CONVERSATION SOURCES and TOOLS USED sections.
 *
 * WHAT THESE GUARD:
 *   Sources:
 *     1. Dedup by URL — same article cited under two article_ids → one row.
 *     2. Dedup by article_id when no URL (knowledge-graph citations).
 *     3. Count = occurrences across the whole conversation.
 *     4. Ordering — count desc, then maxRelevance desc.
 *     5. User messages and unidentifiable citations are ignored.
 *     6. Empty-string URLs (chat normalizer artefact) normalise to null.
 *   Tools:
 *     7. Grouping by tool name with invocation counts.
 *     8. Average latency over TIMED samples only (nulls excluded, rounded).
 *     9. Ordering — count desc, then alphabetical (stable render).
 */

import { describe, expect, it } from "vitest";

import {
  aggregateConversationSources,
  summarizeToolUsage,
} from "../conversation-derive";
import type { ToolUsageSample } from "../types";
import type { Message } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

// WHY derive the citation shape from Message (not importing the deprecated
// legacy type): the no-legacy-citation architecture gate (Q-10) blocks bare
// `Citation` imports in features/chat/** — Message["citations"][number] gets
// the identical shape without naming the deprecated symbol.
type MessageCitation = NonNullable<Message["citations"]>[number];

let seq = 0;
function msg(
  role: "user" | "assistant",
  citations: Partial<MessageCitation>[] = [],
): Message {
  seq += 1;
  return {
    message_id: `m-${seq}`,
    thread_id: "t-1",
    role,
    content: "irrelevant for these derivations",
    created_at: "2026-06-11T00:00:00Z",
    citations: citations.map((c, i) => ({
      article_id: c.article_id ?? `art-${seq}-${i}`,
      title: c.title ?? `Title ${seq}-${i}`,
      url: c.url ?? "",
      source: c.source ?? "news",
      relevance_score: c.relevance_score ?? 0.5,
    })),
  };
}

// ── aggregateConversationSources ──────────────────────────────────────────────

describe("aggregateConversationSources", () => {
  it("dedupes by URL across turns and counts every reference", () => {
    const shared = {
      url: "https://example.com/aapl-10q",
      title: "AAPL 10-Q",
      source: "sec",
    };
    const messages = [
      msg("assistant", [{ ...shared, article_id: "a-1" }]),
      // Same URL under a DIFFERENT article_id (two retrieval tools citing
      // the same document) — must still collapse into one row.
      msg("assistant", [{ ...shared, article_id: "a-2" }]),
      msg("assistant", [{ ...shared, article_id: "a-1" }]),
    ];
    const rows = aggregateConversationSources(messages);
    expect(rows).toHaveLength(1);
    expect(rows[0].count).toBe(3);
    expect(rows[0].title).toBe("AAPL 10-Q");
    expect(rows[0].url).toBe("https://example.com/aapl-10q");
  });

  it("falls back to article_id as the dedup key for URL-less (KG) citations", () => {
    const messages = [
      msg("assistant", [
        { article_id: "kg-1", url: "", source: "kg", title: "Apple graph" },
      ]),
      msg("assistant", [
        { article_id: "kg-1", url: "", source: "kg", title: "Apple graph" },
      ]),
    ];
    const rows = aggregateConversationSources(messages);
    expect(rows).toHaveLength(1);
    expect(rows[0].count).toBe(2);
    // Empty-string url (chat normalizer artefact) must normalise to null —
    // the rail renders a non-link row for these.
    expect(rows[0].url).toBeNull();
  });

  it("orders by reference count desc, then by best relevance desc", () => {
    const messages = [
      msg("assistant", [
        { url: "https://x.com/once-high", relevance_score: 0.95 },
        { url: "https://x.com/twice-low", relevance_score: 0.2 },
        { url: "https://x.com/once-low", relevance_score: 0.3 },
      ]),
      msg("assistant", [{ url: "https://x.com/twice-low", relevance_score: 0.2 }]),
    ];
    const rows = aggregateConversationSources(messages);
    // twice-low (count 2) outranks both count-1 rows despite lower relevance;
    // among count-1 rows, the higher relevance wins.
    expect(rows.map((r) => r.url)).toEqual([
      "https://x.com/twice-low",
      "https://x.com/once-high",
      "https://x.com/once-low",
    ]);
  });

  it("tracks the MAX relevance seen for a deduped source", () => {
    const messages = [
      msg("assistant", [{ url: "https://x.com/a", relevance_score: 0.4 }]),
      msg("assistant", [{ url: "https://x.com/a", relevance_score: 0.9 }]),
    ];
    expect(aggregateConversationSources(messages)[0].maxRelevance).toBe(0.9);
  });

  it("ignores user messages and citations with neither url nor article_id", () => {
    const messages: Message[] = [
      // User message with citations (shouldn't happen, but must not count).
      msg("user", [{ url: "https://x.com/user-side" }]),
      // Unidentifiable citation — no url, no article_id.
      {
        ...msg("assistant"),
        citations: [
          {
            article_id: "",
            title: "ghost",
            url: "",
            source: "news",
            relevance_score: 0.9,
          },
        ],
      },
    ];
    expect(aggregateConversationSources(messages)).toHaveLength(0);
  });

  it("returns [] for an empty conversation", () => {
    expect(aggregateConversationSources([])).toEqual([]);
  });
});

// ── summarizeToolUsage ────────────────────────────────────────────────────────

describe("summarizeToolUsage", () => {
  it("groups samples by tool with counts and rounded average latency", () => {
    const samples: ToolUsageSample[] = [
      { tool: "get_price_history", latencyMs: 100 },
      { tool: "get_price_history", latencyMs: 201 },
      { tool: "search_documents", latencyMs: 950 },
    ];
    const rows = summarizeToolUsage(samples);
    expect(rows).toEqual([
      // count desc → price_history (2) first…
      { tool: "get_price_history", count: 2, avgLatencyMs: 151 }, // (100+201)/2 = 150.5 → 151
      { tool: "search_documents", count: 1, avgLatencyMs: 950 },
    ]);
  });

  it("averages over timed samples only (null latency excluded, not zeroed)", () => {
    const samples: ToolUsageSample[] = [
      { tool: "get_quote", latencyMs: 300 },
      { tool: "get_quote", latencyMs: null }, // legacy backend — untimed
    ];
    const rows = summarizeToolUsage(samples);
    expect(rows[0].count).toBe(2);
    // (300)/1, NOT (300+0)/2=150 — nulls must not deflate the average.
    expect(rows[0].avgLatencyMs).toBe(300);
  });

  it("reports null average when NO sample carried a latency", () => {
    const rows = summarizeToolUsage([{ tool: "x", latencyMs: null }]);
    expect(rows[0].avgLatencyMs).toBeNull();
  });

  it("breaks count ties alphabetically for a stable render order", () => {
    const samples: ToolUsageSample[] = [
      { tool: "zeta_tool", latencyMs: 1 },
      { tool: "alpha_tool", latencyMs: 1 },
    ];
    expect(summarizeToolUsage(samples).map((r) => r.tool)).toEqual([
      "alpha_tool",
      "zeta_tool",
    ]);
  });

  it("returns [] for no samples", () => {
    expect(summarizeToolUsage([])).toEqual([]);
  });
});
