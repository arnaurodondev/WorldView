/**
 * features/chat/components/ThreadRail.tsx — Left-hand thread list rail.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-05):
 *   Extracted verbatim from `app/(app)/chat/page.tsx` lines 549–693 so the
 *   page can drop ~150 LOC and the rail can be composed inside the new
 *   `<ChatLayout>` shell (T-04). Behaviour parity is the goal — every
 *   existing UX (search, rename, delete, scroll preservation, 401-aware
 *   error banner, empty state) is preserved bit-for-bit. The page still
 *   owns the data + rename/delete handlers; the rail is pure presentation
 *   plus a thin debounced-search local state.
 *
 *   The page must NOT be edited as part of this commit — Block G T-20 is
 *   the planned site where the legacy thread-rail JSX is removed and the
 *   page composes `<ThreadRail .../>` instead. Until then the legacy and
 *   the extracted rail co-exist; only the legacy one renders.
 *
 * WHY 224px WIDE (vs. legacy 280px):
 *   Density bundle 2026-05-09 narrowed the rail from 280px to 224px so the
 *   message column gets the extra horizontal real estate. The width is
 *   imposed by the parent grid (`ChatLayout` `grid-cols-[224px_...]`), so
 *   this component does not set a width — only the internal layout
 *   (header / search box / scrollable list / market banner) needs to
 *   pack into whatever the parent allots.
 *
 * SEARCH SCOPE NOTE:
 *   The legacy page held BOTH `searchInput` (immediate keystroke value)
 *   AND `searchQuery` (debounced 200ms value) at page-level. Here we
 *   keep both *inside* the rail because the rail is the only consumer of
 *   the debounced value — pushing it up to the page in Block G would
 *   create an extra prop-drill for no caller benefit. The `threads`
 *   array passed in is the unfiltered list; the rail filters internally.
 *
 * DATA SOURCE: pure prop forwarding — no fetch, no TanStack subscription.
 *   The page owns `useQuery({ qk.chat.threads() })` and pipes the result.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §3.1 (left rail) +
 *   §6.4 (thread row 24px height — applied by `<ThreadItem>` in Block G
 *   T-20, NOT here).
 */

"use client";
// WHY "use client": this rail owns interactive state (search box + scroll
// preservation refs) and dispatches DOM events to its children. Server
// Component status is impossible.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquare, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketContextBanner } from "@/components/chat/MarketContextBanner";
import { ThreadItem } from "@/features/chat/components/ThreadItem";
import { cn } from "@/lib/utils";
import type { Thread } from "@/types/api";

interface ThreadRailProps {
  /** Full unfiltered thread list (or `undefined` while loading / error). */
  readonly threads: Thread[] | undefined;
  /** Active thread id used to highlight the matching row. */
  readonly activeThreadId: string | null;
  /** Loading flag forwarded from the parent's `useQuery`. */
  readonly isLoading: boolean;
  /** Error from the parent's `useQuery` — null when healthy. */
  readonly error: unknown;
  /** Refetch handler so the rail can drive the "Retry" affordance itself. */
  readonly onRetry: () => void;
  /** Called when the user clicks "New chat". */
  readonly onNewChat: () => void;
  /** Called when the user clicks a thread row. */
  readonly onSelect: (id: string) => void;
  /** Called when the user clicks the per-row delete icon. */
  readonly onDelete: (id: string, e: React.MouseEvent) => void;
  /** Called when the user commits an inline rename. */
  readonly onRename: (id: string, newTitle: string) => Promise<void>;
}

/**
 * ThreadRail — see file header. Composes `MarketContextBanner` at the top,
 * a header strip with the New-chat button, a debounced search input, and
 * the scrollable list of `<ThreadItem>` rows. The component is unaware of
 * the page's TanStack Query cache; it only consumes the props.
 */
export function ThreadRail({
  threads,
  activeThreadId,
  isLoading,
  error,
  onRetry,
  onNewChat,
  onSelect,
  onDelete,
  onRename,
}: ThreadRailProps) {
  // ── Debounced search (extracted from page.tsx lines 170-171, 274-277) ──────
  // WHY two states: `searchInput` mirrors the controlled input on every
  // keystroke (so the box doesn't lag); `searchQuery` is the debounced
  // value that drives filtering (so the list doesn't re-render on every
  // letter). 200ms matches the legacy page convention.
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setSearchQuery(searchInput), 200);
    return () => clearTimeout(handle);
  }, [searchInput]);

  // ── Scroll preservation refs (extracted from page.tsx lines 181-182, 290-315) ─
  // WHY refs (not state): updating React state on every scroll event would
  // re-render the whole rail and tank performance for long thread lists.
  // We capture the scrollTop on the underlying Radix Viewport via a native
  // listener and restore it after each refetch.
  const sidebarScrollRef = useRef<HTMLDivElement>(null);
  const savedScrollTopRef = useRef<number>(0);

  useEffect(() => {
    const inner = sidebarScrollRef.current;
    if (!inner) return;
    const viewport = inner.closest<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (!viewport) return;
    const handleScroll = () => {
      savedScrollTopRef.current = viewport.scrollTop;
    };
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const inner = sidebarScrollRef.current;
    if (!inner) return;
    const viewport = inner.closest<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (!viewport) return;
    if (savedScrollTopRef.current > 0) {
      viewport.scrollTop = savedScrollTopRef.current;
    }
  }, [threads]);

  // Router for the 401 "Sign in" CTA — only constructed here so the rail
  // owns the affordance instead of pushing the responsibility back to the
  // page. Matches platform-QA round 5 (2026-05-01) decision.
  const router = useRouter();

  // ── Filter (extracted from page.tsx lines 327-341) ─────────────────────────
  // WHY include message text too: analysts often remember a phrase from the
  // answer ("...that NVDA report on Hopper...") even when they don't
  // remember the thread title.
  const filteredThreads = useMemo(() => {
    if (!threads) return undefined;
    if (!searchQuery.trim()) return threads;
    const needle = searchQuery.trim().toLowerCase();
    return threads.filter((t) => {
      const title = (t.title ?? "").toLowerCase();
      const msgText =
        t.messages?.map((m) => m.content).join(" ").toLowerCase() ?? "";
      return title.includes(needle) || msgText.includes(needle);
    });
  }, [threads, searchQuery]);

  // 401-vs-generic error split (parity with legacy page lines 638-669).
  const errorMessage = (error as Error | null)?.message ?? "";
  const is401 =
    errorMessage.includes("401") ||
    errorMessage.toLowerCase().includes("unauthor");

  return (
    // WHY <nav>: matches the legacy page's a11y landmark so screen-reader
    // users land on the same region label they had before.
    <nav className="flex h-full flex-col" aria-label="Chat thread list">
      {/* Market session strip — grounds the panel in real market context. */}
      <MarketContextBanner />

      {/* Header strip with title + New chat button. Density-bundle sizing
          (px-3 py-2 + 11px uppercase) preserved verbatim. */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-1.5">
          <MessageSquare className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground">
            Threads
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={onNewChat}
          className="h-7 gap-1 border-primary/30 px-2 text-xs text-primary hover:bg-primary/10"
          aria-label="Start new chat"
        >
          <Plus className="h-3 w-3" strokeWidth={1.5} />
          New chat
        </Button>
      </div>

      {/* Debounced search box. */}
      <div className="border-b border-border/40 p-2">
        <div className="relative">
          <Search
            className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground"
            strokeWidth={1.5}
          />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search threads…"
            aria-label="Search threads"
            className={cn(
              "w-full rounded-[2px] border border-border bg-muted",
              "pl-7 pr-2 py-1.5 text-xs text-foreground",
              "placeholder:text-muted-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary",
            )}
          />
        </div>
      </div>

      {/* Thread list body — the ref attaches to the inner content div; the
          scroll listener walks up to the Radix viewport (the real scroll
          container) via the data attribute. */}
      <ScrollArea className="flex-1">
        <div ref={sidebarScrollRef} className="space-y-0.5 p-2">
          {isLoading && (
            <div className="space-y-1.5 p-1" aria-label="Loading threads">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-8 w-full rounded-[2px]" />
              ))}
            </div>
          )}

          {Boolean(error) && !isLoading && (
            // 401 → "Sign in" CTA; everything else → "Retry".
            <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
              {is401 ? (
                <>
                  <p className="font-medium">Your session expired.</p>
                  <p className="mt-1">
                    Sign in again to load your conversations.
                  </p>
                  <button
                    type="button"
                    onClick={() => router.push("/login?redirect_to=/chat")}
                    className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20"
                  >
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  <p>Failed to load threads. Check your connection.</p>
                  <button
                    type="button"
                    onClick={onRetry}
                    className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20"
                  >
                    Retry
                  </button>
                </>
              )}
            </div>
          )}

          {!isLoading && !error && (!threads || threads.length === 0) && (
            <p className="px-3 py-3 text-xs text-muted-foreground">
              No conversations yet. Click &ldquo;New chat&rdquo; to begin.
            </p>
          )}

          {/* Empty-after-filter state (matches legacy lines 681-685). */}
          {filteredThreads?.length === 0 && threads && threads.length > 0 && (
            <p className="px-3 py-3 text-xs text-muted-foreground">
              No threads match &ldquo;{searchQuery}&rdquo;.
            </p>
          )}

          {filteredThreads?.map((thread) => (
            <ThreadItem
              key={thread.thread_id}
              thread={thread}
              isActive={thread.thread_id === activeThreadId}
              onSelect={onSelect}
              onDelete={onDelete}
              onRename={onRename}
            />
          ))}
        </div>
      </ScrollArea>
    </nav>
  );
}
