/**
 * features/chat/lib/conversation-derive.ts — Pure conversation-level
 * derivations for the chat context rail (frontend-rework Wave 2).
 *
 * WHY THIS EXISTS:
 * The context rail's two new sections — CONVERSATION SOURCES and TOOLS USED —
 * are aggregations over the whole conversation:
 *
 *   - Sources: every citation across every assistant turn, deduped by the
 *     underlying source document, with a count of how many times it was
 *     referenced. This turns the rail into a running bibliography of the
 *     research session ("what is this conversation actually grounded in?").
 *   - Tools: every completed tool invocation across the conversation, grouped
 *     by tool name with a count and an average latency — "which platform
 *     capabilities answered, and how fast".
 *
 * WHY A PURE MODULE (no React, no fetch, no Date):
 * Same rationale as ticker-extract.ts — these are deterministic functions of
 * the conversation log, so a table-driven Vitest suite can pin every rule
 * (dedup key precedence, count ordering, average rounding) without mounting
 * the rail component or mocking TanStack Query.
 *
 * WHO USES IT: ChatContextRail.tsx (render), chat page (none directly).
 */

import type { Message } from "@/types/api";
import type { ToolUsageSample } from "@/features/chat/lib/types";

// ── Conversation sources ──────────────────────────────────────────────────────

/** One aggregated source row for the rail's CONVERSATION SOURCES section. */
export interface ConversationSource {
  /** Stable dedup key — url when present, else article_id. */
  key: string;
  /** Raw source string from the citation (badge-ified by the rail). */
  source: string;
  /** Citation title (first non-empty one seen for this source). */
  title: string;
  /** Hyperlink — null for in-platform sources (knowledge-graph citations). */
  url: string | null;
  /** How many times this source was cited across the conversation. */
  count: number;
  /** Highest relevance_score seen for this source (tie-break ordering). */
  maxRelevance: number;
}

/**
 * Default row cap for the rail. 6 rows ≈ the vertical budget the sources
 * section gets on a 1080p rail next to entity cards + tools; the count
 * badge on the section header still reports the TOTAL distinct sources.
 */
export const DEFAULT_SOURCE_CAP = 6;

/**
 * aggregateConversationSources — citations across ALL assistant turns,
 * deduped by source document, ordered by reference count (desc) then by
 * best relevance (desc).
 *
 * DEDUP KEY: `url` when the citation has one (the canonical identity of an
 * external article — the same article can surface under two article_ids when
 * cited by different retrieval tools), else `article_id` (knowledge-graph
 * citations have no URL but a stable id). Citations with NEITHER are skipped:
 * a row that can't be identified can't be counted or opened.
 *
 * COUNT SEMANTICS: one increment per citation OCCURRENCE (a source cited in
 * three turns counts 3) — the count is the "how load-bearing is this source
 * for the conversation" signal the spec asks for.
 *
 * WHY count-then-relevance ordering: the rail answers "what is this
 * conversation grounded in" — a source referenced four times matters more
 * than a one-off with a marginally higher confidence score.
 */
export function aggregateConversationSources(
  messages: readonly Message[],
): ConversationSource[] {
  const byKey = new Map<string, ConversationSource>();

  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    for (const cit of msg.citations ?? []) {
      // Normalise the empty-string url the chat normalizer writes for
      // KG citations back to null — "" is not an openable link.
      const url = cit.url && cit.url.trim().length > 0 ? cit.url : null;
      const key = url ?? cit.article_id;
      if (!key) continue; // unidentifiable citation — cannot dedup or open

      const existing = byKey.get(key);
      if (existing) {
        existing.count += 1;
        existing.maxRelevance = Math.max(
          existing.maxRelevance,
          cit.relevance_score ?? 0,
        );
        // Backfill a title if the first occurrence had none.
        if (!existing.title && cit.title) existing.title = cit.title;
      } else {
        byKey.set(key, {
          key,
          source: cit.source || "source",
          title: cit.title ?? "",
          url,
          count: 1,
          maxRelevance: cit.relevance_score ?? 0,
        });
      }
    }
  }

  return [...byKey.values()].sort(
    (a, b) => b.count - a.count || b.maxRelevance - a.maxRelevance,
  );
}

// ── Tools used ────────────────────────────────────────────────────────────────

/** One aggregated tool row for the rail's TOOLS USED section. */
export interface ToolUsageRow {
  /** Internal tool name, e.g. "get_entity_narrative". */
  tool: string;
  /** Completed invocations across the conversation. */
  count: number;
  /**
   * Average latency in ms over the samples that HAD a latency, rounded to
   * the nearest integer. Null when no sample carried a latency at all.
   */
  avgLatencyMs: number | null;
}

/**
 * summarizeToolUsage — group conversation-level samples by tool name.
 *
 * ORDERING: by invocation count desc, then alphabetical for a stable render
 * (two tools used once each must not reorder between renders — the rail is
 * ambient context and reshuffling reads as a glitch).
 *
 * WHY average over non-null samples only: latency may be missing for a
 * sample on legacy backends (no duration_ms AND no matching tool_call
 * timestamp). Averaging nulls as zeros would silently deflate the number.
 */
export function summarizeToolUsage(
  samples: readonly ToolUsageSample[],
): ToolUsageRow[] {
  const byTool = new Map<string, { count: number; sum: number; timed: number }>();

  for (const s of samples) {
    const agg = byTool.get(s.tool) ?? { count: 0, sum: 0, timed: 0 };
    agg.count += 1;
    if (s.latencyMs !== null) {
      agg.sum += s.latencyMs;
      agg.timed += 1;
    }
    byTool.set(s.tool, agg);
  }

  return [...byTool.entries()]
    .map(([tool, { count, sum, timed }]) => ({
      tool,
      count,
      avgLatencyMs: timed > 0 ? Math.round(sum / timed) : null,
    }))
    .sort((a, b) => b.count - a.count || a.tool.localeCompare(b.tool));
}
