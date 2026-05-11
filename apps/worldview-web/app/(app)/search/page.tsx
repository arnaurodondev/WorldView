/**
 * app/(app)/search/page.tsx — Full-text document search (PLAN-0064 W6)
 *
 * WHY this page exists: Sam (analyst persona) needs to search across ALL
 * ingested content — news articles, EDGAR filings — in one place. Before
 * this page, articles were only visible per-entity or in the news hub with
 * no free-text search capability.
 *
 * Architecture (request path):
 *   This page
 *     → GET /v1/search?q=... (S9 api-gateway, authenticated)
 *     → S9 validates Bearer token + issues internal JWT
 *     → S9 proxies → S6 nlp-pipeline GET /api/v1/search/documents
 *     → S6 queries chunks.tsv_english GIN index (tsvector full-text search)
 *     → returns results + entity facets
 *
 * WHY TanStack Query (useQuery): provides caching, deduplication, and loading
 * states out of the box. `enabled: debouncedQ.length >= 1` prevents an empty-
 * string search on page load that would hit the backend unnecessarily.
 *
 * WHY debounce (300ms): without it, every keystroke fires a network request.
 * 300ms is the standard UX threshold — feels instant to the user, but reduces
 * backend load by ~10x for a typical 5-character query.
 *
 * WHY entity facets sidebar: entity-filtered search is a core workflow —
 * "show me all NVDA-related filings". Displaying facets with doc counts lets
 * the user narrow results without knowing entity UUIDs.
 *
 * DESIGN REFERENCE: Bloomberg terminal aesthetic — dark theme, dense data rows,
 * monospace timestamps, source badges. Matches news/page.tsx visual language.
 */

"use client";

import { useState, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  FileText,
  Newspaper,
  Search,
} from "lucide-react";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type {
  SearchDocumentsResponse,
  SearchDocumentResult,
  SearchDocumentsFacet,
} from "@/types/api";

// ── Source-type filter chips ───────────────────────────────────────────────
// WHY "all" as the first option: matches S6 default (source_type omitted = all).
// Three chips mirror the terminal's tab-strip convention: compact, scannable.

const SOURCE_TYPES = [
  { value: "all", label: "All Sources" },
  { value: "news", label: "News" },
  { value: "sec_edgar", label: "SEC Filings" },
] as const;

type SourceType = (typeof SOURCE_TYPES)[number]["value"];

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * formatAge — format an ISO published_at as a relative time string.
 *
 * WHY relative time (not ISO): matches news/page.tsx convention. Analysts
 * care whether an article is "3h" vs "2d" old — not the absolute timestamp.
 * The terminal style keeps metadata minimal; the source URL is the primary
 * reference if exact time matters.
 */
function formatAge(iso: string | null): string {
  if (!iso) return "—";
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

/**
 * HighlightedSnippet — render a text snippet with highlighted match regions.
 *
 * WHY not dangerouslySetInnerHTML: S6 returns match offset pairs
 * (start, end) rather than pre-marked HTML. We render React elements directly
 * from the offset pairs — no raw HTML → no XSS risk, even if the snippet
 * contains user-supplied content that was stored in the DB.
 *
 * WHY line-clamp-2: snippets can be 300+ chars. Two lines keeps the result
 * card height consistent at ~56px regardless of snippet length.
 */
function HighlightedSnippet({
  snippet,
  offsets,
}: {
  snippet: string;
  offsets: [number, number][];
}) {
  if (!snippet) return null;

  // No offset pairs: just render the snippet as-is (dim text, consistent style).
  if (!offsets || offsets.length === 0) {
    return (
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
        {snippet}
      </p>
    );
  }

  // Build React nodes from offset pairs — interleave normal text with highlight spans.
  const parts: React.ReactNode[] = [];
  let pos = 0;

  for (const [start, end] of offsets) {
    // Text before this highlight
    if (start > pos) {
      parts.push(
        <span key={`t-${pos}`} className="text-muted-foreground">
          {snippet.slice(pos, start)}
        </span>,
      );
    }
    // The highlighted match — warning (amber) tint, no dangerouslySetInnerHTML.
    // WHY bg-warning/20: uses the design token --warning (#FFB000 Bloomberg amber)
    // so the highlight stays within the design system rather than raw Tailwind yellow.
    parts.push(
      <mark
        key={`m-${start}`}
        className="rounded px-0.5 bg-warning/20 text-warning"
      >
        {snippet.slice(start, end)}
      </mark>,
    );
    pos = end;
  }

  // Any trailing text after the last highlight
  if (pos < snippet.length) {
    parts.push(
      <span key="tail" className="text-muted-foreground">
        {snippet.slice(pos)}
      </span>,
    );
  }

  return <p className="mt-1 line-clamp-2 text-xs">{parts}</p>;
}

// ── Main Page Component ────────────────────────────────────────────────────

export default function SearchPage() {
  // WHY useApiClient: returns the memoised gateway bound to the current access
  // token. The gateway's searchDocuments() sends the Bearer token so S9 can
  // authenticate the request and issue an internal JWT for S6.
  const api = useApiClient();

  // Raw query text (updated on every keystroke — drives the input)
  const [query, setQuery] = useState("");

  // Debounced query (updated 300ms after the user stops typing — drives the fetch)
  const [debouncedQ, setDebouncedQ] = useState("");

  const [sourceType, setSourceType] = useState<SourceType>("all");
  const [page, setPage] = useState(1);

  // Selected entity facet IDs — when non-empty, S6 filters results to documents
  // that mention these entities. Each click toggles membership.
  const [selectedFacets, setSelectedFacets] = useState<string[]>([]);

  // ── Debounce effect ──────────────────────────────────────────────────────
  // WHY useEffect + clearTimeout: standard React debounce pattern. The cleanup
  // function cancels the pending timeout on every new keystroke so only the
  // final value (after the user pauses) fires the request.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Reset pagination + facets whenever the query or source filter changes.
  // WHY: keeping stale page=3 when the user types a new query would show the
  // wrong page. Clearing ensures page 1 is always shown for a new search.
  useEffect(() => {
    setPage(1);
    setSelectedFacets([]);
  }, [debouncedQ, sourceType]);

  // ── TanStack Query ────────────────────────────────────────────────────────
  const { data, isLoading, isError } = useQuery<SearchDocumentsResponse>({
    // WHY all four dimensions in the key: TanStack Query uses the key for cache
    // identity. Including q, sourceType, selectedFacets, and page means each
    // distinct combination has its own cache entry. Changing any one re-fetches.
    queryKey: qk.search.documents(debouncedQ, sourceType, selectedFacets, page),
    queryFn: () =>
      api.searchDocuments({
        q: debouncedQ,
        // WHY undefined for "all": the S6 endpoint defaults to source_type=all
        // when the param is omitted. Sending source_type=all explicitly also
        // works, but omitting it keeps URLs minimal.
        source_type: sourceType === "all" ? undefined : sourceType,
        entity_ids: selectedFacets.length > 0 ? selectedFacets : undefined,
        page,
        page_size: 25,
      }),
    // WHY enabled: prevents firing a search before the user types anything.
    // An empty-string query to the GIN index would return the most recent 25
    // documents — not useful and wastes a backend round-trip.
    enabled: debouncedQ.length >= 1,
    // WHY 30s staleTime: news articles and filings don't change after ingestion.
    // 30 seconds is long enough to avoid redundant fetches when the user navigates
    // away and back, but short enough that genuinely new content appears promptly.
    staleTime: 30_000,
  });

  // Toggle a facet entity ID in/out of selectedFacets.
  // WHY useCallback: stable reference prevents unnecessary re-renders of the
  // FacetSidebar component (though React is smart enough without it, it's a
  // good habit for callbacks passed as props).
  const toggleFacet = useCallback((entityId: string) => {
    setSelectedFacets((prev) =>
      prev.includes(entityId)
        ? prev.filter((id) => id !== entityId)
        : [...prev, entityId],
    );
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Header bar (matches news/page.tsx 28px height convention) ─────── */}
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border px-3">
        <Search
          className="h-3 w-3 text-muted-foreground"
          aria-hidden
          strokeWidth={1.5}
        />
        <h1 className="font-mono text-[11px] uppercase tracking-[0.08em] text-foreground">
          Search
        </h1>
        {/* Total count — only shown once data arrives */}
        {data && debouncedQ && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
            {data.total.toLocaleString()}
          </span>
        )}
      </div>

      {/* ── Search controls (query input + source filter chips) ─────────── */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        {/* WHY relative+absolute for the icon: insets the Search icon into the
            left padding of the Input. Avoids a flex container that would change
            the Input's width calculation. */}
        <div className="relative flex-1 max-w-2xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            className="pl-8 h-7 text-xs bg-background border-border font-mono"
            placeholder='Search articles and filings… supports "phrases" and OR'
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            // WHY autoFocus: the search page has a single primary action (typing
            // a query). Autofocusing avoids a required click before typing.
            autoFocus
          />
        </div>

        {/* Source type filter chips */}
        <div className="flex gap-0.5">
          {SOURCE_TYPES.map((s) => (
            <Button
              key={s.value}
              size="sm"
              // WHY "secondary" vs "ghost": the active chip uses secondary to
              // match the time-window selector convention in news/page.tsx.
              variant={sourceType === s.value ? "secondary" : "ghost"}
              onClick={() => setSourceType(s.value)}
              className="h-6 px-2 text-[10px] font-mono uppercase tracking-wider"
              aria-pressed={sourceType === s.value}
            >
              {s.label}
            </Button>
          ))}
        </div>
      </div>

      {/* ── Results + facet sidebar ──────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Results list — takes up remaining width when no facets; shrinks when sidebar shows */}
        <div className="flex-1 min-w-0 overflow-y-auto">
          {/* ── Status line (result count + latency) ──────────────────── */}
          {data && debouncedQ && (
            <div className="px-3 pt-2 pb-1">
              <p className="font-mono text-[10px] text-muted-foreground">
                {data.total.toLocaleString()}{" "}
                {data.total === 1 ? "result" : "results"} for{" "}
                <span className="text-foreground">&quot;{data.query}&quot;</span>{" "}
                ·{" "}
                <span className="tabular-nums">{data.latency_ms}ms</span>
              </p>
            </div>
          )}

          {/* ── Loading skeletons ──────────────────────────────────────── */}
          {isLoading && (
            <div className="space-y-1 px-3 pt-1">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className="rounded border border-border p-2 space-y-1.5">
                  <Skeleton className="h-3 w-3/4" style={{ animationDelay: `${i * 40}ms` }} />
                  <Skeleton className="h-2.5 w-1/2" style={{ animationDelay: `${i * 40 + 20}ms` }} />
                </div>
              ))}
            </div>
          )}

          {/* ── Error state ────────────────────────────────────────────── */}
          {isError && !isLoading && (
            <div className="px-3 py-4">
              <p className="font-mono text-xs text-destructive">
                Search failed — check your connection and try again.
              </p>
            </div>
          )}

          {/* ── Zero results ───────────────────────────────────────────── */}
          {!isLoading && !isError && data?.total === 0 && debouncedQ && (
            <div className="px-3 py-4">
              <p className="font-mono text-xs text-muted-foreground">
                No results for &quot;{debouncedQ}&quot;
              </p>
              {selectedFacets.length > 0 && (
                <p className="font-mono text-[10px] text-muted-foreground/60 mt-1">
                  Try removing entity filters — {selectedFacets.length} active
                </p>
              )}
            </div>
          )}

          {/* ── Empty initial state (no query yet) ─────────────────────── */}
          {!debouncedQ && (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
              <Search className="h-7 w-7 opacity-20" />
              <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/50">
                Type to search articles and filings
              </p>
            </div>
          )}

          {/* ── Result cards ───────────────────────────────────────────── */}
          {/* WHY no ul/li here: the result cards are not a list of navigable
              items — some link out (anchor), some have no URL (plain div).
              A div container avoids the semantic mismatch. */}
          {!isLoading && data && data.results.length > 0 && (
            <div className="divide-y divide-border/40 px-3">
              {data.results.map((result) => (
                <ResultCard key={result.doc_id} result={result} />
              ))}
            </div>
          )}

          {/* ── Load more button ──────────────────────────────────────── */}
          {data?.has_more && !isLoading && (
            <div className="px-3 pb-3 pt-2">
              <Button
                variant="outline"
                size="sm"
                className="w-full h-7 text-[10px] font-mono"
                onClick={() => setPage((p) => p + 1)}
              >
                Load more{" "}
                <ChevronRight className="ml-1 h-3 w-3" aria-hidden />
              </Button>
            </div>
          )}
        </div>

        {/* ── Entity facet sidebar ─────────────────────────────────────── */}
        {/* WHY conditional render (not always mounted): the sidebar only makes
            sense when there are results with entity mentions. An empty sidebar
            after a zero-result search would confuse the user. */}
        {(data?.facets?.length ?? 0) > 0 && (
          <FacetSidebar
            facets={data!.facets}
            selected={selectedFacets}
            onToggle={toggleFacet}
          />
        )}
      </div>
    </div>
  );
}

// ── Sub-component: Result Card ─────────────────────────────────────────────

/**
 * ResultCard — single search result row.
 *
 * WHY separate component: keeps the JSX in SearchPage manageable. Each card
 * is ~30 lines of JSX; inlining 25 of them would make the page unreadable.
 *
 * Design:
 *   [Title — links to source if URL available]
 *   [Snippet with highlighted match spans]
 *   [Source badge (News/SEC)] [Age timestamp]
 */
function ResultCard({ result }: { result: SearchDocumentResult }) {
  const isEdgar = result.source_type === "sec_edgar";

  // WHY conditional anchor vs span: if there is no source_url (e.g. some SEC
  // filings only have an accession number stored, not a direct link), we render
  // a plain div to avoid dead <a href="#"> links that confuse screen readers.
  const TitleElement = result.source_url ? (
    <a
      href={result.source_url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[11px] font-medium leading-snug hover:underline line-clamp-1"
      // WHY aria-label: screen readers should announce the destination context
      // so "opens in new tab" is surfaced without a visible icon.
      aria-label={`${result.title ?? "Untitled"} (opens in new tab)`}
    >
      {result.title ?? "Untitled"}
    </a>
  ) : (
    <p className="text-[11px] font-medium leading-snug line-clamp-1">
      {result.title ?? "Untitled"}
    </p>
  );

  return (
    <div className="py-2 hover:bg-muted/20 transition-colors -mx-3 px-3">
      <div className="flex items-start justify-between gap-2">
        {/* Left: title + snippet */}
        <div className="flex-1 min-w-0">
          {TitleElement}
          <HighlightedSnippet
            snippet={result.snippet ?? ""}
            offsets={(result.match_offsets as [number, number][] | undefined) ?? []}
          />
        </div>

        {/* Right: source badge + age — shrink-0 prevents layout thrash */}
        <div className="flex shrink-0 flex-col items-end gap-1">
          {/* Source badge: primary tint for SEC filings, positive (green) for news.
              WHY design tokens: avoids raw Tailwind color classes (PLAN-0071 P1-4);
              primary = terminal blue-white accent; positive = institutional green. */}
          <Badge
            variant="outline"
            className={cn(
              "h-4 px-1 text-[9px] font-mono uppercase tracking-wider",
              isEdgar
                ? "border-primary/40 text-primary"
                : "border-positive/40 text-positive",
            )}
          >
            {/* WHY icon before text: scan pattern — icon at a glance, label for
                confirmation. FileText for SEC, Newspaper for news. */}
            {isEdgar ? (
              <FileText className="mr-0.5 h-2 w-2" aria-hidden />
            ) : (
              <Newspaper className="mr-0.5 h-2 w-2" aria-hidden />
            )}
            {isEdgar ? "SEC" : "News"}
          </Badge>
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
            {formatAge(result.published_at ?? null)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Sub-component: Facet Sidebar ────────────────────────────────────────────

/**
 * FacetSidebar — entity filter panel on the right.
 *
 * WHY a dedicated component: isolates the facet toggle logic from the main
 * page, and makes it easy to test in isolation if needed.
 *
 * UX: clicking a facet toggles it. Multiple facets can be selected (OR — S6
 * returns documents matching ANY of the selected entities). Active facets
 * are highlighted with bg-accent.
 */
function FacetSidebar({
  facets,
  selected,
  onToggle,
}: {
  facets: SearchDocumentsFacet[];
  selected: string[];
  onToggle: (entityId: string) => void;
}) {
  return (
    // WHY w-52 shrink-0: fixed width sidebar. flex-1 on the results list
    // absorbs any remaining space. shrink-0 prevents the sidebar from
    // collapsing on narrow viewports (the results list min-w-0 handles overflow).
    <div className="w-52 shrink-0 overflow-y-auto border-l border-border px-2 py-2">
      <p className="mb-1.5 px-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
        Filter by entity
      </p>
      <div className="space-y-0.5">
        {facets.map((facet) => {
          const isActive = selected.includes(facet.entity_id);
          return (
            <button
              key={facet.entity_id}
              onClick={() => onToggle(facet.entity_id)}
              // WHY full-width button: easier to click than a small toggle.
              // Keyboard-accessible (button element, not div with onClick).
              className={cn(
                "flex w-full items-center justify-between rounded px-2 py-1 text-left transition-colors",
                "font-mono text-[10px] hover:bg-accent",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground",
              )}
              aria-pressed={isActive}
              title={`Filter to ${facet.name} (${facet.entity_type})`}
            >
              <span className="truncate">{facet.name}</span>
              {/* doc count badge — gives the user a signal of relevance */}
              <Badge
                variant="outline"
                className="ml-1 h-4 shrink-0 px-1 text-[9px] tabular-nums"
              >
                {facet.count}
              </Badge>
            </button>
          );
        })}
      </div>
    </div>
  );
}
