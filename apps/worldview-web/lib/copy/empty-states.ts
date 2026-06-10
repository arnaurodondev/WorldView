/**
 * lib/copy/empty-states.ts — centralised empty-state copy dictionary
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-10.10 — every empty-state across
 * the app reads from the same dictionary so we have one place to audit
 * tone, length, and finance-terminology accuracy.  Each entry maps a
 * stable key (e.g. "portfolio.no-holdings") to a {title, body, cta?}
 * triple so EmptyState can render any condition uniformly.
 *
 * Five canonical conditions (FU-10.11):
 *   - loading
 *   - empty-cold-start (user has account but no data yet)
 *   - empty-no-data (data source returned empty)
 *   - error
 *   - permission (user lacks access)
 *   - coming-soon (feature flagged off)
 *
 * Page agents extend this dictionary as new keys are needed.  The
 * empty-copy-dictionary arch test (plan §4) guarantees every
 * <EmptyState copyKey="X"> reference resolves to a key here.
 */

export interface EmptyCopy {
  readonly title: string;
  readonly body: string;
  readonly ctaLabel?: string;
}

export const EMPTY_COPY: Record<string, EmptyCopy> = {
  // Generic fallbacks — used when a page hasn't defined its own key yet.
  "generic.loading": {
    title: "Loading…",
    body: "Fetching the latest data from the platform.",
  },
  "generic.empty-cold-start": {
    title: "Nothing here yet",
    body: "Once data starts flowing through the platform you'll see it here.",
  },
  "generic.empty-no-data": {
    title: "No data",
    body: "This source returned an empty result for the current query.",
  },
  "generic.error": {
    title: "Couldn't load",
    body: "The platform returned an error. Retry, or check the status page.",
    ctaLabel: "Retry",
  },
  "generic.permission": {
    title: "Access required",
    body: "You don't have permission to view this resource.",
  },
  "generic.coming-soon": {
    title: "Coming soon",
    body: "This view is queued for a later wave of the roadmap.",
  },

  // Portfolio surface keys — extended by per-page agents.
  "portfolio.no-holdings": {
    title: "No holdings yet",
    body: "Connect a brokerage or enter a manual lot to populate this view.",
    ctaLabel: "Connect brokerage",
  },
  "portfolio.no-transactions": {
    title: "No transactions",
    body: "Transactions appear here after the first brokerage sync.",
  },

  // Screener surface keys.
  "screener.no-matches": {
    title: "No matches",
    body: "Try widening the criteria or removing a filter.",
  },

  // Watchlist surface keys.
  "watchlist.empty": {
    title: "Empty watchlist",
    body: "Add tickers from any instrument page to track them here.",
    ctaLabel: "Browse instruments",
  },

  // News / intelligence keys.
  "news.no-articles": {
    title: "No articles",
    body: "The pipeline hasn't surfaced any articles matching this query.",
  },
  "intelligence.no-brief": {
    title: "Brief unavailable",
    body: "Re-run the brief generator from the action menu.",
    ctaLabel: "Regenerate",
  },

  // Instrument surface keys — Round-2 reservation (cross-surface request,
  // item 4). Copy mirrors the headline/hint strings currently hardcoded in
  // components/instrument/shared/EmptyState.tsx call sites (NewsColumn,
  // GraphColumn, ContextPanel, ContradictionsBlock) so the Round-3
  // consolidation onto components/primitives/EmptyState.tsx is a pure
  // mechanical swap with zero copy changes. Dynamic fragments (the depth
  // number in the graph-timeout headline) are generalised — registry copy
  // must be static; surfaces needing interpolation keep a local string.
  "instrument.no-articles": {
    title: "No articles for this entity",
    body: "Articles appear here as the ingestion pipeline links coverage to this entity.",
  },
  "instrument.no-contradictions": {
    title: "No contradictions detected",
    body: "Conflicting claims between sources surface here when the KG pipeline flags them.",
  },
  "instrument.graph-timeout": {
    title: "Graph query timed out",
    body: "Deeper traversals are expensive. Try depth 1 or 2.",
    ctaLabel: "Reduce depth",
  },
  "instrument.graph-no-filter-matches": {
    title: "No entities match the type filter",
    body: "Clear or widen the entity-type filter in the toolbar above.",
  },
  "instrument.no-connections": {
    title: "No connections found",
    body: "The knowledge graph builds connections as news articles are ingested — check back later.",
  },
  "instrument.no-entity-context": {
    title: "No entity context",
    body: "This entity has not been enriched yet — the overnight enrichment worker populates name, type and description.",
  },
};

export type EmptyCopyKey = keyof typeof EMPTY_COPY;
