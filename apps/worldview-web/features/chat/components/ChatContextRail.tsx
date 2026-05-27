/**
 * features/chat/components/ChatContextRail.tsx — Right-hand chat context rail.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block D, T-16):
 *   A Bloomberg-grade chat surface is never just a message column — it
 *   surrounds the conversation with an always-on context rail showing
 *   the active entity, recent evidence, contradictions, and related
 *   tickers. Without it, every follow-up question forces the analyst to
 *   re-scroll history. The rail collapses a thread's "what do I know
 *   right now?" state into four dense sections at a fixed 320 px width.
 *
 *   FOUR SECTIONS (design doc 10-chat-ai.md §3 + plan §4 #6):
 *     1. Entity card    — active instrument + price + ratios + health dot
 *     2. Recent citations — deduped CitationV2[] across the thread
 *     3. Contradictions — aggregated SSE contradictions across all turns
 *     4. Related tickers — chips of entities resolved during the thread
 *
 *   Each section has its own 9px uppercase heading. Empty sections render
 *   the heading + a 1-line "—" muted placeholder (terminal style — we
 *   never hide structural rows, only their content).
 *
 * DATA SOURCING DECISION:
 *   The plan spec suggested using TanStack `useQuery` against the
 *   `qk.chat.contradictions(threadId)` and `qk.chat.recentCitations(threadId)`
 *   cache anchors. After auditing `useChatStream.ts` we confirmed those
 *   anchors are NOT yet populated — the hook stores everything on
 *   `localMessages` state, not in TanStack cache. Subscribing to those
 *   keys would return `undefined` forever.
 *
 *   PICK: derive directly from the `messages` prop (the same array
 *   `ChatMessageList` consumes). This is simpler, immediate, and gives
 *   the rail the exact same view the message column has. When the cache
 *   anchors are wired in a future commit, swap the `useMemo` body for a
 *   `useQuery` read — the component contract stays identical.
 *
 *   TODO(PLAN-0089-K-FU): migrate to cache-anchor reads once
 *   `useChatStream` writes through to `qk.chat.recentCitations` /
 *   `qk.chat.contradictions`.
 *
 * Q-4 DEDUP RULE: recent citations are deduped by `id` across the thread;
 *   when a citation occurs more than once, the highest `relevance_score`
 *   occurrence wins (its title/source survives), and the row suffix
 *   shows `· {count}×` so the analyst sees the answer was multiply-
 *   sourced. This mirrors the design-doc lock for recent-citations.
 *
 * READ-ONLY INVARIANT: this component performs ZERO fetches. Everything
 *   it renders was already captured by `useChatStream` during a turn.
 *   That keeps the rail latency-free (analyst expects it to update in
 *   lockstep with the message column).
 *
 * DESIGN REFERENCE:
 *   - docs/designs/0089/10-chat-ai.md §3 (4-section rail layout)
 *   - docs/ui/DESIGN_SYSTEM.md §0.1 typography + §0.3 semantic tokens
 *   - Plan §4 #6/#7/#8 (entity card + KG popover + health dot specs)
 */

"use client";

// "use client" because the rail mounts `EntityHealthDot` (Radix Tooltip),
// `ContradictionStrip` (interactive rows), and reads from the message
// list state owned by the chat page. None of this can SSR.

import { useMemo } from "react";

import { ContradictionStrip } from "@/features/chat/components/ContradictionStrip";
import { EntityHealthDot } from "@/features/chat/components/EntityHealthDot";
import type { CitationV2, Message } from "@/types/api";

// SECTION-DIVIDER NOTE: the plan calls for `<SectionDivider>` between the
// four rail sections. The existing primitive is grid-aware (col-span-3)
// and only fits inside a 3-col CSS grid; the rail is a flex column. We
// therefore satisfy the design intent (visual separation between
// sections) via the `border-b border-border` on each section wrapper.
// A future v1.1 refactor can promote a flex-friendly variant of
// `SectionDivider` and swap it in here without changing the rail's
// public contract.

interface ChatContextRailProps {
  /**
   * Thread id is currently unused at the data layer (we derive everything
   * from `messages`) but we keep it on the props contract so that the
   * future cache-anchor migration is a zero-call-site-change refactor.
   */
  readonly threadId: string;
  /**
   * All messages currently rendered in the thread (assistant + user).
   * The rail filters internally — user turns contribute nothing to
   * citations/contradictions but their entity context is still derived
   * from the turn-level resolved_entities.
   */
  readonly messages: Message[];
  /**
   * The instrument page the chat was opened from (if any). The Entity
   * card seeds its label off this. Falls back to "—" when null (e.g.
   * the global /chat page with no active instrument).
   */
  readonly activeEntity?: { id: string; ticker: string | null } | null;
}

// Maximum recent-citations rows rendered. Beyond this the rail becomes
// taller than 1080px and forces a scroll which defeats the "everything
// visible at a glance" goal. Picked to match the 18px row * ~12 rows
// fitting the rail's vertical budget below the entity card.
const MAX_RECENT_CITATIONS = 12;

// Maximum related-ticker chips. More than 8 produces a wrapping mess
// at 320px width; analysts only ever scan the top few anyway.
const MAX_RELATED_CHIPS = 8;

// ── Helpers ─────────────────────────────────────────────────────────────

/**
 * The wire-format `Message.citations` is typed as legacy `Citation[]` but
 * Block A's `useChatStream` patch populates it with `CitationV2`-shaped
 * objects whenever the SSE stream is the source. We narrow at the
 * boundary instead of leaking the duality outward.
 *
 * WHY a runtime check on `kind`: legacy `Citation` had no `kind` field,
 * so its presence is a structural discriminator that we can safely test
 * without a separate flag.
 */
function asCitationV2(c: unknown): CitationV2 | null {
  if (!c || typeof c !== "object") return null;
  const obj = c as Record<string, unknown>;
  if (typeof obj.id !== "string" || typeof obj.kind !== "string") return null;
  return obj as unknown as CitationV2;
}

interface DedupedCitation {
  citation: CitationV2;
  count: number;
}

/**
 * dedupeCitations — Q-4 dedup. Walks every assistant message in order,
 * groups citations by `id`, keeps the occurrence with the highest
 * `relevance_score`, and counts total occurrences.
 *
 * Returns at most MAX_RECENT_CITATIONS entries sorted by descending
 * count then descending relevance — so the most-cited evidence floats
 * to the top of the rail.
 */
function dedupeCitations(messages: Message[]): DedupedCitation[] {
  const byId = new Map<string, DedupedCitation>();
  for (const m of messages) {
    // Skip non-assistant turns — citations only attach to AI answers.
    if (m.role !== "assistant") continue;
    for (const raw of m.citations ?? []) {
      const v2 = asCitationV2(raw);
      if (!v2) continue;
      const existing = byId.get(v2.id);
      if (!existing) {
        byId.set(v2.id, { citation: v2, count: 1 });
        continue;
      }
      // Highest relevance wins for the surviving row. Treat missing
      // relevance_score as 0 so a scored row always beats an unscored.
      const incoming = v2.relevance_score ?? 0;
      const winning = existing.citation.relevance_score ?? 0;
      if (incoming > winning) existing.citation = v2;
      existing.count += 1;
    }
  }
  const list = Array.from(byId.values());
  list.sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    const ra = a.citation.relevance_score ?? 0;
    const rb = b.citation.relevance_score ?? 0;
    return rb - ra;
  });
  return list.slice(0, MAX_RECENT_CITATIONS);
}

/**
 * Aggregate all per-turn contradictions into a single flat array.
 * ContradictionStrip handles the rendering — we only flatten here.
 */
function aggregateContradictions(messages: Message[]): NonNullable<Message["contradictions"]> {
  const out: NonNullable<Message["contradictions"]> = [];
  for (const m of messages) {
    if (m.role !== "assistant") continue;
    if (m.contradictions && m.contradictions.length > 0) out.push(...m.contradictions);
  }
  return out;
}

/**
 * dedupeResolvedEntities — collect every `resolved_entities` id across
 * the thread, keep first-seen order, cap to MAX_RELATED_CHIPS. We dedupe
 * by string-equality (entity_id is a UUID, so trivial set semantics).
 */
function dedupeResolvedEntities(messages: Message[]): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const m of messages) {
    if (m.role !== "assistant") continue;
    for (const eid of m.resolved_entities ?? []) {
      if (typeof eid !== "string" || eid.length === 0) continue;
      if (seen.has(eid)) continue;
      seen.add(eid);
      order.push(eid);
      if (order.length >= MAX_RELATED_CHIPS) return order;
    }
  }
  return order;
}

// ── Sub-components (private — kept in this file to enforce the
// 4-section visual contract; Block G can promote them later if needed) ──

/**
 * SectionHeading — 9px uppercase tracking-wide muted row. The rail uses
 * this verbatim across all four sections. Extracted so the styling is
 * literally one source of truth.
 */
function SectionHeading({ label, count }: { label: string; count?: number }) {
  return (
    <div className="flex h-[14px] items-center gap-2 px-2 text-[9px] font-mono uppercase tracking-wide text-muted-foreground">
      <span>{label}</span>
      {typeof count === "number" ? <span className="tabular-nums">· {count}</span> : null}
    </div>
  );
}

/**
 * EmptyPlaceholder — terminal-style "—" line. We render the heading +
 * this so the rail's vertical layout stays stable across thread states
 * (it's disorienting if entire sections disappear between turns).
 */
function EmptyPlaceholder() {
  return (
    <div data-cell className="px-2 py-1 text-[10px] font-mono text-muted-foreground/60">
      —
    </div>
  );
}

/**
 * EntityCard — section 1. Renders the active entity's identifier + a
 * health dot when we know how to seed one. Today we have NO cached
 * `get_entity_health` payload (see file header), so the dot only
 * appears when the caller threads us a score via activeEntity at a
 * future iteration. For now we always render the card frame with the
 * ticker; price/ratios are placeholders until the cache anchor lands.
 *
 * WHY hard-coded "—" placeholders for price/PE/etc.: the rail must
 * show the visual rhythm so QA can see the layout is correct; the
 * cells will swap to live values when the cache anchor for
 * `get_intelligence_brief` is wired (PLAN-0089-K-FU).
 */
function EntityCard({ activeEntity }: { activeEntity: ChatContextRailProps["activeEntity"] }) {
  const ticker = activeEntity?.ticker ?? null;
  return (
    <section aria-label="Active entity" className="border-b border-border">
      <SectionHeading label="entity" />
      <div className="flex items-center gap-2 px-2 py-1">
        <span
          data-cell
          className="font-mono text-[11px] tabular-nums text-foreground"
        >
          {ticker ?? "—"}
        </span>
        {/* No live health score available yet — render a neutral 0 dot
            only when we have a ticker (so the card looks intentional
            during the live walk-through). Real data lands when the
            cached `get_entity_health` plumbing ships. */}
        {ticker ? <EntityHealthDot score={0} /> : null}
        <span data-cell className="ml-auto font-mono text-[10px] text-muted-foreground">
          {activeEntity?.id ? activeEntity.id.slice(0, 8) : "—"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-x-2 px-2 pb-1 text-[10px] font-mono text-muted-foreground tabular-nums">
        {/* Three placeholder cells — the design calls for price / change
            / P/E in v1 + market_cap / employees / sector in v1.1. They
            are wired to "—" until the brief cache anchor lands. */}
        <span data-cell>price —</span>
        <span data-cell>chg —</span>
        <span data-cell>P/E —</span>
      </div>
    </section>
  );
}

/**
 * RecentCitationsSection — section 2. Renders the deduped recent
 * citations with `· N×` count suffix. We do NOT reuse `CitationStrip`
 * because that component renders a per-row hovercard (heavy) and has
 * no slot for the count suffix. Inline rendering keeps the rail crisp.
 */
function RecentCitationsSection({ deduped }: { deduped: DedupedCitation[] }) {
  return (
    <section aria-label="Recent citations" className="border-b border-border">
      <SectionHeading label="recent citations" count={deduped.length || undefined} />
      {deduped.length === 0 ? (
        <EmptyPlaceholder />
      ) : (
        <ul role="list" className="divide-y divide-border">
          {deduped.map(({ citation, count }) => (
            <li
              key={citation.id}
              data-cell
              className="flex h-[18px] items-center gap-2 px-2 text-[10px] font-mono"
            >
              <span className="uppercase text-muted-foreground">[{citation.kind}]</span>
              <span className="flex-1 truncate text-foreground">
                {citation.title || "Untitled"}
              </span>
              {count > 1 ? (
                <span
                  className="text-muted-foreground tabular-nums"
                  title="Cited across multiple turns"
                >
                  · {count}×
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * ContradictionsSection — section 3. Wraps ContradictionStrip with the
 * heading + empty placeholder convention. ContradictionStrip already
 * returns `null` for empty arrays so we handle the empty case here.
 */
function ContradictionsSection({
  contradictions,
}: {
  contradictions: NonNullable<Message["contradictions"]>;
}) {
  return (
    <section aria-label="Contradictions" className="border-b border-border">
      <SectionHeading label="contradictions" count={contradictions.length || undefined} />
      {contradictions.length === 0 ? (
        <EmptyPlaceholder />
      ) : (
        <ContradictionStrip contradictions={contradictions} />
      )}
    </section>
  );
}

/**
 * RelatedTickersSection — section 4. Renders entity-id chips for every
 * entity resolved during the thread. We do NOT use the AG-Grid
 * `TickerLinkCellRenderer` (the only existing TickerLink primitive)
 * because it is bound to AG Grid's row params. Instead we render
 * plain `<a>` chips here — the design system permits this since the
 * primitive layer doesn't yet have a generic ticker chip.
 *
 * NAVIGATION: chips link to `/instruments/{ticker}` when activeEntity
 * gives us a ticker; otherwise to the entity detail page by id. This
 * matches PRD-0089 F2's instrument-routing lock.
 */
function RelatedTickersSection({
  entityIds,
  activeEntity,
}: {
  entityIds: string[];
  activeEntity: ChatContextRailProps["activeEntity"];
}) {
  return (
    <section aria-label="Related tickers">
      <SectionHeading label="related" count={entityIds.length || undefined} />
      {entityIds.length === 0 ? (
        <EmptyPlaceholder />
      ) : (
        <div className="flex flex-wrap gap-1 px-2 py-1">
          {entityIds.map((eid) => {
            // If this chip corresponds to the active entity, prefer
            // its ticker as the chip label (cleaner than a UUID). All
            // other entities still surface their id-prefix — the
            // ticker-by-id lookup needs a backend round-trip that we
            // explicitly defer to the cache-anchor migration.
            const isActive = activeEntity?.id === eid;
            const label =
              isActive && activeEntity?.ticker ? activeEntity.ticker : eid.slice(0, 8);
            const href = isActive && activeEntity?.ticker
              ? `/instruments/${encodeURIComponent(activeEntity.ticker)}`
              : `/entities/${encodeURIComponent(eid)}`;
            return (
              <a
                key={eid}
                href={href}
                data-cell
                className="inline-flex h-[16px] items-center border border-border bg-card px-1 font-mono text-[10px] tabular-nums text-foreground hover:bg-muted/40"
              >
                {label}
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Public component ───────────────────────────────────────────────────

/**
 * ChatContextRail — see file header. Parent constrains the width to
 * 320px (per design doc); this component uses `w-full` and lets the
 * parent decide. All four sections render unconditionally — empty
 * sections show their heading + a muted "—" so the layout is stable.
 */
export function ChatContextRail({ threadId: _threadId, messages, activeEntity }: ChatContextRailProps) {
  // useMemo so the three derivations don't re-run on every parent
  // re-render — the rail is mounted next to the message column which
  // re-renders on every streaming token, and the dedup loops are O(N*M).
  const dedupedCitations = useMemo(() => dedupeCitations(messages), [messages]);
  const contradictions = useMemo(() => aggregateContradictions(messages), [messages]);
  const resolvedEntityIds = useMemo(() => dedupeResolvedEntities(messages), [messages]);

  return (
    <aside
      aria-label="Chat context rail"
      // w-full so the parent shell controls the 320px width. Bordered
      // box so the rail visually separates from the message column.
      className="flex w-full flex-col border-l border-border bg-card"
    >
      <EntityCard activeEntity={activeEntity} />
      <RecentCitationsSection deduped={dedupedCitations} />
      <ContradictionsSection contradictions={contradictions} />
      <RelatedTickersSection entityIds={resolvedEntityIds} activeEntity={activeEntity} />
    </aside>
  );
}
