/**
 * lib/command-palette.ts — Pure ranking + filtering helpers for the global ⌘K palette.
 *
 * WHY THIS EXISTS: The CommandPalette component (components/shell/CommandPalette.tsx)
 * mixes three result sources — static navigation routes, live S9 instrument search,
 * and recent chat conversations. The ordering rules ("exact ticker match first, then
 * prefix matches, then recency") are pure data transformations with NO React or DOM
 * dependency, so they live here where they can be unit-tested in isolation without
 * rendering a dialog. The component stays a thin presenter.
 *
 * WHY NOT in lib/api/: nothing here performs I/O. lib/api/* modules are gateway
 * fetcher factories; this is a pure-function module like lib/format.ts.
 *
 * WHO USES IT: components/shell/CommandPalette.tsx + its tests.
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §6.15 Command Palette.
 */

// ── Minimal structural types ───────────────────────────────────────────────────
// WHY structural (not importing types/api wholesale): the ranking functions only
// care about a handful of fields. Accepting a minimal shape keeps the functions
// generic — tests can pass tiny literals, and a future caller with a richer row
// type (e.g. screener rows) can reuse the ranker without type gymnastics.

/** The slice of a SearchResult that ranking needs. */
export interface RankableInstrument {
  readonly entity_id: string;
  readonly ticker: string;
  readonly name: string;
}

/** The slice of a chat Thread that recency-sorting needs. */
export interface RankableThread {
  readonly thread_id: string;
  readonly title: string | null;
  readonly updated_at: string;
}

/**
 * One static navigation entry shown in the palette's "Navigate" group.
 * The lucide icon component is attached by the React layer (CommandPalette.tsx)
 * — keeping icons out of this module preserves its React-free purity.
 */
export interface PaletteNavEntry {
  /** Display label, e.g. "Portfolio › Transactions". */
  readonly label: string;
  /** App-router path, e.g. "/portfolio/transactions". */
  readonly path: string;
  /**
   * Canonical chord from lib/hotkey-registry (e.g. "g d") if one is wired in
   * GlobalHotkeyBindings. Rendered via formatChordForDisplay so the palette can
   * never advertise a different chord than the registry actually fires
   * (same no-lying invariant as the StatusBar).
   */
  readonly chord?: string;
  /**
   * Extra lowercase search terms beyond the label, e.g. ["stocks", "equities"]
   * for Screener. Lets "trades" find "Portfolio › Transactions".
   */
  readonly keywords?: readonly string[];
}

// ── Navigation filtering ───────────────────────────────────────────────────────

/**
 * matchesNavEntry — case-insensitive substring match of `query` against an
 * entry's label or any of its keywords.
 *
 * WHY substring (not fuzzy): the Navigate list is ~14 items. Fuzzy scoring
 * (fuse.js) buys nothing at this size and produces surprising matches
 * ("st" matching "Settings" via s…t). Substring is predictable: what you see
 * highlighted is literally what you typed.
 */
export function matchesNavEntry(entry: PaletteNavEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true; // empty query → show everything
  if (entry.label.toLowerCase().includes(q)) return true;
  return (entry.keywords ?? []).some((k) => k.toLowerCase().includes(q));
}

// ── Instrument ranking ─────────────────────────────────────────────────────────

/**
 * rankInstrumentResults — order S9 search results for the palette.
 *
 * RANKING CONTRACT (Round-1 spec): exact ticker match first, then ticker-prefix
 * matches, then everything else; within each tier, instruments the user visited
 * recently (localStorage recents, see lib/recent-instruments.ts) float above
 * never-visited ones, and the server's own relevance order breaks remaining ties.
 *
 * WHY this matters: typing "A" returns AAPL, A (Agilent), AA (Alcoa), ABNB…
 * The S3 ILIKE query returns them in arbitrary DB order. A trader typing the
 * full ticker "A" wants Agilent (exact match) pinned to the top — Bloomberg's
 * <GO> behaves the same way. Recency as a tie-breaker means a user who checks
 * AAPL every morning gets it above ABNB when both are prefix matches for "A".
 *
 * WHY a stable decorate-sort-undecorate: Array.prototype.sort IS stable in
 * modern JS, but we still attach the original index explicitly so the intent
 * is auditable and the function is safe under any engine.
 */
export function rankInstrumentResults<T extends RankableInstrument>(
  results: readonly T[],
  query: string,
  recentEntityIds: readonly string[] = [],
): T[] {
  const q = query.trim().toUpperCase();
  // Map entity_id → recency rank (0 = most recent). Misses get Infinity so
  // they sort after every recent instrument within the same tier.
  const recencyRank = new Map<string, number>();
  recentEntityIds.forEach((id, i) => {
    if (!recencyRank.has(id)) recencyRank.set(id, i);
  });

  const tierOf = (ticker: string): number => {
    const t = ticker.toUpperCase();
    if (q !== "" && t === q) return 0; // exact ticker match
    if (q !== "" && t.startsWith(q)) return 1; // ticker prefix match
    return 2; // name/substring match — server order preserved
  };

  return results
    .map((r, index) => ({
      r,
      index,
      tier: tierOf(r.ticker),
      recency: recencyRank.get(r.entity_id) ?? Number.POSITIVE_INFINITY,
    }))
    .sort((a, b) => {
      if (a.tier !== b.tier) return a.tier - b.tier;
      if (a.recency !== b.recency) return a.recency - b.recency;
      return a.index - b.index; // stable: keep server relevance order
    })
    .map((d) => d.r);
}

// ── Conversation recency ───────────────────────────────────────────────────────

/**
 * Fallback title for threads the user never named. rag-chat auto-titles threads
 * after the first exchange, but a thread created and abandoned before any reply
 * has title=null — we still want it selectable rather than rendering blank.
 */
export const UNTITLED_THREAD_LABEL = "Untitled conversation";

/**
 * filterRecentThreads — newest-first conversation list for the palette's
 * "Recent Conversations" group.
 *
 * - Sorts by `updated_at` DESC (ISO-8601 strings compare correctly as strings
 *   ONLY when timezone-normalised, so we go through Date.parse to be safe —
 *   rag-chat emits UTC but defensive parsing costs nothing at n≤100).
 * - When `query` is non-empty, keeps only threads whose title contains it
 *   (case-insensitive). Untitled threads match the UNTITLED_THREAD_LABEL text
 *   so typing "untitled" surfaces them.
 * - Truncates to `limit` AFTER filtering so a search can reach older threads
 *   than the default top-5.
 */
export function filterRecentThreads<T extends RankableThread>(
  threads: readonly T[],
  query: string,
  limit = 5,
): T[] {
  const q = query.trim().toLowerCase();
  return threads
    .filter((t) => {
      if (q === "") return true;
      const title = (t.title ?? UNTITLED_THREAD_LABEL).toLowerCase();
      return title.includes(q);
    })
    .slice() // copy before sort — never mutate a TanStack Query cache array in place
    .sort((a, b) => {
      const ta = Date.parse(a.updated_at);
      const tb = Date.parse(b.updated_at);
      // NaN-safe: unparseable timestamps sink to the bottom instead of
      // poisoning the comparator (NaN comparisons would make sort order random).
      const va = Number.isNaN(ta) ? Number.NEGATIVE_INFINITY : ta;
      const vb = Number.isNaN(tb) ? Number.NEGATIVE_INFINITY : tb;
      return vb - va;
    })
    .slice(0, limit);
}
