/**
 * lib/api/chat.ts — Chat threads + SSE streaming.
 *
 * Includes the `normalizeThread`/`normalizeCitation` helpers, co-located
 * because they are chat-domain shape transformers (rag-chat citations →
 * legacy frontend Citation contract).
 */

import type { Thread, ChatStreamRequest, CompanyOverview } from "@/types/api";
import { BASE, GatewayError, apiFetch } from "./_client";

/**
 * normalizeThread — translate the rag-chat citation shape into the legacy
 * Citation contract the frontend chat components were built against.
 *
 * WHY THIS EXISTS: rag-chat's ThreadDetailResponse emits citations with
 * `{ id, source_name, confidence, item_type, entity_name, ... }`. The frontend
 * Citation type and components (CitationBar, CitationList, chat/page.tsx) still
 * expect `{ article_id, source, relevance_score, title, url }`. Calling
 * `cite.source.toLowerCase()` on the raw payload throws TypeError as soon as
 * any historical thread with citations is opened — the symptom the user
 * reported as "clicking an old chat shows an error".
 *
 * Normalization is one-way (server → UI). The mapping is purely additive: we
 * write the legacy field names so existing code keeps working AND keep the
 * new fields too in case future components consume them. When the frontend
 * Citation type is migrated to the canonical names, this helper can be
 * deleted in one commit.
 */
type RawCitation = {
  // Legacy (already in frontend Citation type)
  article_id?: string;
  source?: string;
  relevance_score?: number;
  // Canonical (rag-chat's ThreadDetailResponse)
  id?: string;
  source_name?: string;
  confidence?: number;
  item_type?: string;
  entity_name?: string;
  // Shared
  title?: string;
  url?: string;
};

/**
 * normalizeCitation — exported (QA Wave-3 closeout, 2026-06-11) so the SSE
 * `citations` event handler in useChatStream can apply the SAME mapping.
 *
 * WHY: streamed citations arrive with the canonical rag-chat shape
 * (`{ ref, id, source_name, confidence, ... }` — verified live). Before the
 * CRLF parser fix the streamed event never parsed, so this path was dead; the
 * moment it came alive, CitationList's `cite.source.toLowerCase()` crashed the
 * whole chat page mid-stream ("Cannot read properties of undefined (reading
 * 'toLowerCase')" error boundary). Normalizing at BOTH boundaries (thread
 * fetch here, SSE ingest in useChatStream) keeps every downstream component
 * on the legacy contract until the CitationV2 atomic rename.
 */
export function normalizeCitation(raw: RawCitation): RawCitation {
  return {
    ...raw,
    article_id: raw.article_id ?? raw.id ?? "",
    source: raw.source ?? raw.source_name ?? raw.item_type ?? "source",
    relevance_score: raw.relevance_score ?? raw.confidence ?? 0,
    title: raw.title ?? "",
    url: raw.url ?? "",
  };
}

function normalizeThread(thread: Thread): Thread {
  if (!thread || !Array.isArray(thread.messages)) return thread;
  return {
    ...thread,
    messages: thread.messages.map((m) => ({
      ...m,
      citations: Array.isArray(m.citations)
        ? (m.citations.map(normalizeCitation) as Thread["messages"][number]["citations"])
        : [],
    })),
  };
}

export function createChatApi(t: string | undefined) {
  return {
    /**
     * getThreads — user's conversation thread list
     *
     * PLAN-0052 platform-QA round 7 (2026-05-01): the live S9 gateway returns
     * `{threads: [...]}` (envelope), but earlier code assumed a bare `Thread[]`.
     * Calling `.filter(...)` on the envelope object threw a TypeError that the
     * chat page surfaced as "Failed to load threads", masking the real error
     * and producing the chat-tab popup. Tolerate both shapes so a future
     * back-compat shift doesn't break the page again.
     */
    async getThreads(): Promise<Thread[]> {
      const raw = await apiFetch<{ threads?: Thread[] } | Thread[]>("/v1/threads", {
        token: t,
      });
      if (Array.isArray(raw)) return raw;
      return Array.isArray(raw?.threads) ? raw.threads : [];
    },

    /**
     * createThread — start a new conversation thread
     */
    createThread(title?: string): Promise<Thread> {
      return apiFetch<Thread>("/v1/threads", {
        method: "POST",
        body: { title },
        token: t,
      });
    },

    /**
     * getThread — get thread with its full message history
     *
     * WHY normalizeThread: rag-chat returns citations with the canonical
     * `{ id, source_name, confidence, item_type, ... }` shape but the frontend
     * Citation type still uses the legacy `{ article_id, source, relevance_score }`
     * names from PRD-0028. Without normalization the chat page throws
     * "Cannot read properties of undefined (reading 'toLowerCase')" the moment
     * a message with citations renders, which manifests as "clicking an old
     * thread crashes the UI". Mapping at the gateway boundary keeps every
     * downstream component (CitationList, CitationBar) untouched.
     */
    async getThread(threadId: string): Promise<Thread> {
      const raw = await apiFetch<Thread>(
        `/v1/threads/${encodeURIComponent(threadId)}`,
        { token: t },
      );
      return normalizeThread(raw);
    },

    /**
     * deleteThread — delete a conversation thread
     */
    deleteThread(threadId: string): Promise<void> {
      return apiFetch<void>(`/v1/threads/${encodeURIComponent(threadId)}`, {
        method: "DELETE",
        token: t,
      });
    },

    /**
     * updateThread — patch mutable thread fields (currently only `title`)
     *
     * WHY PATCH (not PUT): a PUT would imply replacing the whole resource
     * including its messages, which is wrong — messages are append-only on
     * the rag-chat side. PATCH semantics let us send just the fields the
     * user changed, and the server merges into the row. PLAN-0051 Wave E /
     * T-E-5-06.
     *
     * Accepts `{ title }` for now; the typing leaves room for future fields
     * (e.g. `is_pinned`) without changing call sites.
     */
    async updateThread(threadId: string, patch: { title?: string }): Promise<Thread> {
      // WHY normalizeThread: PATCH returns the full ThreadDetailResponse with
      // messages+citations in rag-chat's canonical shape; same field-name
      // mismatch as getThread() above. See normalizeThread() comment block.
      const raw = await apiFetch<Thread>(
        `/v1/threads/${encodeURIComponent(threadId)}`,
        { method: "PATCH", body: patch, token: t },
      );
      return normalizeThread(raw);
    },

    /**
     * getCompanyOverviewByTicker — ONE-request entity overview for chat cards.
     *
     * WHY THIS EXISTS (frontend-rework Wave 2, backed by the Wave-1 S9
     * endpoint GET /v1/companies/by-ticker/{ticker}/overview): the chat
     * context rail's entity mini-cards previously did a two-step dance —
     * searchInstruments(ticker) → instrument_id → getCompanyOverview(id) —
     * i.e. TWO round-trips per detected ticker. The by-ticker endpoint
     * resolves the ticker server-side (S3 lookup + KG alias fallback) and
     * returns the SAME composed CompanyOverview shape in one call.
     *
     * WHY return null on 404 (instead of throwing): the rail's cards are
     * ambient background context — a ticker that fails to resolve (bare-token
     * false positive that slipped the blocklist, delisted symbol) must simply
     * produce NO card, never an error banner. Mapping the 404 to null at the
     * API boundary keeps every caller's "no data → no card" branch trivial
     * and mirrors the old searchInstruments-miss behaviour exactly.
     * Non-404 failures still throw — a 500/timeout is a real error TanStack
     * Query should record (the rail renders nothing for error states too,
     * but retry/backoff semantics stay intact).
     */
    async getCompanyOverviewByTicker(
      ticker: string,
    ): Promise<CompanyOverview | null> {
      try {
        return await apiFetch<CompanyOverview>(
          `/v1/companies/by-ticker/${encodeURIComponent(ticker)}/overview`,
          { token: t },
        );
      } catch (err) {
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * streamChat — POST SSE streaming chat response
     *
     * WHY fetch() not EventSource: EventSource is GET-only and can't send
     * a request body with the question. We use fetch() + ReadableStream for
     * POST-based SSE. The token goes in the Authorization header (not URL).
     * See PRD-0028 §6.2 Chat Routes for streaming protocol details.
     *
     * Returns a native ReadableStream — the ChatUI component reads chunks
     * via response.body.getReader().
     */
    async streamChat(
      request: ChatStreamRequest,
    ): Promise<ReadableStream<Uint8Array> | null> {
      const response = await fetch(`${BASE}/v1/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(t ? { Authorization: `Bearer ${t}` } : {}),
        },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        throw new GatewayError(response.status, response.statusText);
      }

      // Return the raw ReadableStream — ChatUI reads it with getReader()
      return response.body;
    },
  };
}
