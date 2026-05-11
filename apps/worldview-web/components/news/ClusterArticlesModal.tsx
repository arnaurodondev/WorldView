/**
 * components/news/ClusterArticlesModal.tsx — Near-duplicate cluster viewer (P2-F)
 *
 * WHY THIS EXISTS: When the user clicks the "+N sim" chip on a news article, they
 * want to see all the sibling articles that cover the same story. This Sheet (a
 * side panel that slides in from the right) shows the full list.
 *
 * HOW IT WORKS:
 * 1. The parent passes `clusterId` — when non-null the Sheet opens.
 * 2. A TanStack Query fetches GET /v1/news/cluster/{clusterId} (S9 proxy → content-store).
 * 3. The response contains a list of articles (usually 2 — primary + duplicate).
 * 4. Clicking outside or pressing Escape closes the Sheet (Radix Dialog behavior).
 *
 * WHY Sheet (not Dialog): Sheet slides in from the right, keeping the news list
 * visible behind it — the analyst retains context. A Dialog would obscure everything.
 *
 * WHY TanStack Query (not fetch): enables caching — if the user closes and re-opens
 * the same cluster, the data is served from cache without a network round-trip.
 * `staleTime: 5 * 60_000` (5 min) matches the news feed's refetch interval.
 *
 * WHO USES IT: app/(app)/news/page.tsx + components/instrument/NewsTab.tsx
 */

"use client";
// WHY "use client": uses useQuery (React state) + Sheet (Radix Dialog, which uses
// browser APIs). Server components cannot use either.

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ClusterArticle } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ClusterArticlesModalProps {
  /**
   * The UUID of the duplicate cluster to display.
   * When null (or undefined), the Sheet is closed.
   * When non-null, the Sheet opens and fetches the cluster's articles.
   */
  clusterId: string | null;

  /** Called when the user dismisses the Sheet (close button, Escape, backdrop click). */
  onClose: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatPublishedAt — convert ISO-8601 timestamp to a human-readable relative string.
 *
 * WHY local helper (not imported from utils): the utils formatRelativeTime
 * exists but has slightly different output format. Defining here keeps the
 * component self-contained and easy to tweak independently.
 */
function formatPublishedAt(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const sec = Math.floor((Date.now() - then) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

/**
 * ClusterArticleSkeleton — loading placeholder for one article row.
 *
 * WHY 2 rows: a cluster always has exactly 2 articles (primary + duplicate).
 * Showing 2 skeleton rows sets the correct expectation while data loads.
 */
function ClusterArticleSkeleton() {
  return (
    <div className="space-y-2 pt-3">
      {/* Row 1 */}
      <div className="space-y-1 border-b border-border/40 pb-3">
        <Skeleton className="h-3 w-3/4" />
        <div className="flex gap-2">
          <Skeleton className="h-2 w-16" />
          <Skeleton className="h-2 w-10" />
        </div>
      </div>
      {/* Row 2 */}
      <div className="space-y-1 pb-3">
        <Skeleton className="h-3 w-2/3" />
        <div className="flex gap-2">
          <Skeleton className="h-2 w-16" />
          <Skeleton className="h-2 w-10" />
        </div>
      </div>
    </div>
  );
}

// ── Article row ───────────────────────────────────────────────────────────────

/**
 * ClusterArticleRow — renders one article in the cluster list.
 *
 * WHY an `<a>` (not a button + router.push): cluster articles link out to
 * external news sources (source_url). Opening in a new tab is the correct
 * behavior — same as the main news feed rows.
 */
function ClusterArticleRow({ article }: { article: ClusterArticle }) {
  return (
    <a
      href={article.url ?? "#"}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${article.title ?? "(untitled)"} (opens in new tab)`}
      className={cn(
        "group block border-b border-border/40 py-3 last:border-0",
        // WHY no px: the Sheet already has p-3 on the container.
        "transition-colors hover:bg-muted/20 rounded-[2px]",
      )}
    >
      {/* Article title */}
      <p className="text-[11px] leading-snug text-foreground group-hover:text-primary transition-colors">
        {article.title ?? "(untitled)"}
      </p>

      {/* Metadata row — source, timestamp, external link icon */}
      <div className="mt-1 flex items-center gap-2">
        {/* WHY source_name || "—": source_name is always null from content-store
            (documents table has no source_name column). Display "—" as fallback
            so the row doesn't collapse to an empty line. */}
        <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/60">
          {article.source_name ?? "—"}
        </span>
        <span className="text-[9px] text-muted-foreground/40" aria-hidden>·</span>
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground/60">
          {formatPublishedAt(article.published_at)}
        </span>
        {/* External link icon — visual cue that clicking opens a new tab */}
        <ExternalLink
          className="h-2.5 w-2.5 shrink-0 text-muted-foreground/40 ml-auto"
          aria-hidden
        />
      </div>
    </a>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

/**
 * ClusterArticlesModal — Sheet panel that shows all articles in a near-duplicate cluster.
 *
 * OPEN/CLOSE: controlled by `clusterId` prop — non-null = open, null = closed.
 * The parent controls the open state via a `useState<string | null>(null)`.
 *
 * FETCHING: TanStack Query with `enabled: !!clusterId` so no fetch happens when
 * the Sheet is closed. The query key includes clusterId so different clusters
 * cache independently.
 */
export function ClusterArticlesModal({ clusterId, onClose }: ClusterArticlesModalProps) {
  // WHY useApiClient (not createGateway directly): useApiClient provides the
  // access token from AuthContext automatically, same pattern as the news page.
  const gateway = useApiClient();

  // Fetch cluster articles when clusterId is set.
  // WHY enabled: !!clusterId — avoids a fetch when the Sheet first mounts with
  // clusterId=null. TanStack Query skips the queryFn when enabled=false.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.news.cluster(clusterId ?? ""),
    queryFn: () => gateway.getClusterArticles(clusterId!),
    // WHY enabled guard: clusterId="" would hit the API with an empty string
    // which returns 404. Guard prevents the spurious call.
    enabled: !!clusterId,
    // WHY 5 min staleTime: cluster membership is immutable once written (no
    // re-deduplication for existing articles). Aggressive caching is safe here.
    staleTime: 5 * 60_000,
  });

  const articles = data?.articles ?? [];

  // Sheet open state mirrors clusterId: open when non-null, closed when null.
  // WHY we use onOpenChange to call onClose: Radix Dialog fires onOpenChange(false)
  // when the user presses Escape or clicks the backdrop. We propagate that to the
  // parent so it can set clusterId back to null (controlling the open state).
  return (
    <Sheet open={!!clusterId} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" className="flex flex-col gap-0 p-0">

        {/* Header */}
        <SheetHeader className="border-b border-border px-4 py-3">
          <SheetTitle>
            {/* WHY "Similar articles" (not "Duplicate articles"): near-duplicates
                are corroboration signals — "duplicate" implies they are junk, which
                they aren't. Same language as the chip ("sim"). */}
            Similar articles
          </SheetTitle>
          <SheetDescription>
            {/* Show cluster_size from the first article if available, else "N" */}
            {articles.length > 0
              ? `${articles.length} article${articles.length !== 1 ? "s" : ""} covering the same story`
              : isLoading
              ? "Loading similar articles…"
              : "Articles covering the same story"}
          </SheetDescription>
        </SheetHeader>

        {/* Body */}
        <div className="flex-1 overflow-auto px-4">
          {isLoading ? (
            // WHY 2 skeletons: cluster always has exactly 2 articles (primary + duplicate).
            <ClusterArticleSkeleton />
          ) : isError ? (
            // WHY simple text (not full InlineEmptyState): the error state is rare
            // and the Sheet is small. A full component would dominate the panel.
            <p className="pt-4 font-mono text-[10px] text-muted-foreground">
              Failed to load similar articles.
            </p>
          ) : articles.length === 0 ? (
            <p className="pt-4 font-mono text-[10px] text-muted-foreground">
              No similar articles found.
            </p>
          ) : (
            // Article list — typically 2 rows (primary + 1 near-duplicate).
            <div className="divide-y divide-border/20 pt-1">
              {articles.map((article) => (
                <ClusterArticleRow key={article.id} article={article} />
              ))}
            </div>
          )}
        </div>

        {/* Footer — cluster metadata */}
        {clusterId && !isLoading && !isError && articles.length > 0 && (
          <div className="shrink-0 border-t border-border/40 px-4 py-2">
            <p className="font-mono text-[9px] tabular-nums text-muted-foreground/50">
              cluster {clusterId.slice(0, 8)}…
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
