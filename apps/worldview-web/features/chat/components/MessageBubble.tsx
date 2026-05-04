// Server Component — no hooks, no browser APIs, no direct event handlers.
// Renders static JSX using props only. Imports MarkdownContent via the
// LazyMarkdownContent client wrapper (see below) and CitationBar which are
// Client Components — that is valid: Server Components can render Client Components.
// Do not re-add "use client" without checking all of the above.
// PLAN-0059-G Wave G-2: The dynamic import for MarkdownContent is in the
// LazyMarkdownContent client wrapper (features/chat/components/LazyMarkdownContent.tsx)
// — Server Components cannot call next/dynamic directly, so the split is done
// in a dedicated "use client" wrapper component.

/**
 * features/chat/components/MessageBubble.tsx — Single chat message bubble.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): this used to be inline in
 * `app/(app)/chat/page.tsx`. Pure render — no SSE / abort coupling — so
 * extraction is mechanical. The accompanying TypingIndicator and
 * StreamingBubble (which share visual chrome) are co-located in this file
 * so the three "bubble" renderers stay together.
 *
 * WAVE E CHANGES (T-E-5-02 + T-E-5-04):
 *   - Assistant messages now render via <LazyMarkdownContent> (tables, code,
 *     copy buttons), which lazy-loads MarkdownContent via next/dynamic.
 *   - A CitationBar (segmented red/yellow/green confidence strip) sits
 *     below assistant messages, complementing the existing pill list.
 *
 * WHY LazyMarkdownContent (not MarkdownContent directly):
 * PLAN-0059-G Wave G-2 requires lazy-loading react-markdown + remark-gfm (~50KB).
 * next/dynamic must be called inside a Client Component — MessageBubble is a
 * Server Component and cannot call next/dynamic. LazyMarkdownContent is a thin
 * "use client" wrapper that owns the dynamic import boundary, keeping this file
 * as a Server Component (enforced by server-component-audit.test.ts).
 *
 * WHO USES IT: app/(app)/chat/page.tsx, WorkspaceChatWidget.tsx, StructuredBrief.tsx
 * DATA SOURCE: Chat messages from TanStack Query cache (thread messages endpoint).
 * DESIGN REFERENCE: PRD-0028 §6.9 Chat; PLAN-0059-G Wave G-2 dynamic imports.
 */

import { Bot } from "lucide-react";
import { LazyMarkdownContent } from "./LazyMarkdownContent";
import { CitationBar } from "@/components/chat/CitationBar";
import type { Message } from "@/types/api";
import { CitationList } from "./CitationList";
import type { StreamingMessage } from "../lib/types";

/**
 * TypingIndicator — animated three-dot bubble shown while SSE stream is
 * active. Finance-grade polish: indicates the LLM is generating, not that
 * the network stalled.
 */
export function TypingIndicator() {
  return (
    <div className="flex max-w-[70%] items-end gap-2 self-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
        {/* WHY strokeWidth={1.5}: terminal chrome icon hairline rule — default 2px
            weight overpowers the 14px bot avatar icon at this size. */}
        <Bot className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
      </div>
      <div className="rounded-[2px] bg-muted px-4 py-3">
        {/* WHY static dots (no animate-bounce): Bloomberg-terminal mandate — no
            bounce/pulse animations on data surfaces. Three static dots still
            convey "generating" when paired with the TypingIndicator label. */}
        <div className="flex gap-1" aria-label="AI is generating a response">
          <span className="h-1.5 w-1.5 rounded-[2px] bg-muted-foreground" />
          <span className="h-1.5 w-1.5 rounded-[2px] bg-muted-foreground" />
          <span className="h-1.5 w-1.5 rounded-[2px] bg-muted-foreground" />
        </div>
      </div>
    </div>
  );
}

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  // WHY anchor prefix: CitationBar segments link to #{prefix}-N anchors that
  // we inject into the rendered message via `id` attributes. Use the
  // message_id to namespace anchors per message.
  const anchorPrefix = `cite-${message.message_id}`;

  return (
    <div className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`flex max-w-[70%] items-end gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}
      >
        {!isUser && (
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
            {/* WHY strokeWidth={1.5}: terminal chrome icon hairline rule — default 2px
                weight overpowers the 14px bot avatar icon at this size. */}
            <Bot className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
          </div>
        )}

        {/*
         * WHY text-[11px] leading-[1.5]: chat messages in a terminal must match the
         * 11px density of all other data surfaces — text-sm (14px) breaks density
         * consistency and makes chat feel like a consumer chatbot pasted into a
         * Bloomberg terminal. leading-[1.5] matches the compact prose standard.
         */}
        <div
          className={`rounded-[2px] px-4 py-3 text-[11px] leading-[1.5] ${
            isUser ? "bg-primary/10 text-foreground" : "bg-muted text-foreground"
          }`}
        >
          {/*
           * User vs assistant rendering split:
           *  - User: plain <pre> preserves their literal whitespace (a question
           *    like "compare:\n- AAPL\n- MSFT" reads as written). Markdown
           *    rendering on user input would mangle "*" wildcards etc.
           *  - Assistant: MarkdownContent size="compact" renders at 10px with
           *    11px headings — matches terminal density (PLAN-0051 T-E-5-02).
           *    WHY "compact" (not "comfortable"): "comfortable" is 12px, which is
           *    too spacious for a terminal surface that targets 11px everywhere.
           */}
          {isUser ? (
            <pre className="whitespace-pre-wrap font-sans text-[11px]">{message.content}</pre>
          ) : (
            <div id={anchorPrefix}>
              <LazyMarkdownContent size="compact">{message.content}</LazyMarkdownContent>
            </div>
          )}

          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>

      {/* Citation bar + pill list — assistant messages only */}
      {!isUser && (message.citations?.length ?? 0) > 0 && (
        <div className="ml-9 max-w-[70%]">
          {/* WHY both bar AND pills: the bar gives at-a-glance gestalt
              (mostly green = trust this answer); the pills give the
              actual click-through link. Different jobs, both useful. */}
          <CitationBar citations={message.citations} anchorPrefix={anchorPrefix} />
          <CitationList citations={message.citations} />
        </div>
      )}
    </div>
  );
}

/**
 * StreamingBubble — the in-flight assistant bubble shown while SSE tokens
 * arrive.
 *
 * WHY MarkdownContent here too: the streaming text often contains markdown
 * partials. Rendering through MarkdownContent gives consistent typography
 * with the final message. Trade-off: partial markdown sometimes flickers
 * (e.g. "**bo" before "**bold**" closes), which is acceptable.
 */
export function StreamingBubble({ streaming }: { streaming: StreamingMessage }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex max-w-[70%] items-end gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
          {/* WHY strokeWidth={1.5}: terminal chrome icon hairline rule — default 2px
              weight overpowers the 14px bot avatar icon at this size. */}
          <Bot className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
        </div>
        {/* WHY text-[11px] leading-[1.5] + size="compact": streaming bubble must
            match the final settled MessageBubble density — same 11px terminal rule. */}
        <div className="rounded-[2px] bg-muted px-4 py-3 text-[11px] leading-[1.5]">
          <LazyMarkdownContent size="compact">{streaming.text}</LazyMarkdownContent>
          {streaming.active && (
            // WHY no animate-pulse: terminal mandate — static cursor still reads as "streaming".
            <span className="ml-0.5 inline-block h-4 w-0.5 bg-primary align-middle" />
          )}
        </div>
      </div>
    </div>
  );
}
