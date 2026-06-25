/**
 * components/dashboard/BriefCatalystPreview.tsx — structured, cited "key
 * catalysts" preview for the Morning Briefing card's COLLAPSED view.
 *
 * WHY THIS EXISTS (roadmap 2026-06-19 Top-8 #8 / C3):
 * The competitive audit asks us to "promote the AI brief from a text block to
 * a structured, cited brief (bulleted catalysts each linking to source article
 * + affected ticker + impact window)" so the LLM layer is *visibly* the
 * product on the very first screen the user sees.
 *
 * Until now the collapsed view rendered ``brief.summary_paragraph`` as a plain
 * prose blob (one undifferentiated paragraph). The structured layout
 * (sections → cited bullets) only appeared AFTER the user clicked "Read more"
 * (the expanded ``StructuredBrief`` path). This component pulls that
 * structure forward: when the backend DID parse the brief into ``sections``
 * with citations, the collapsed card shows a SCANNABLE preview — the top
 * catalysts as bullets, each carrying its source chip(s) and any entity
 * (ticker) it mentions — instead of a wall of text.
 *
 * WHY A SEPARATE COMPONENT (not inlining in MorningBriefCard):
 * MorningBriefCard is already a large file with three render states. The
 * catalyst-preview render is a self-contained, prop-driven transform of the
 * already-parsed ``BriefSection[]`` + ``entity_mentions`` + ``citations`` —
 * isolating it keeps the card readable and lets us unit-test the preview in
 * isolation (deterministic: no data fetching, no TanStack).
 *
 * WHAT WE CAN / CANNOT WIRE (honest scope, per the task brief):
 *   - "links to source article"  → YES. Each bullet's ``BriefCitation`` carries
 *     a ``url`` (for ``source_type === "article"``). We render those as chips.
 *   - "affected ticker"          → YES (best-effort). The brief does not tag a
 *     bullet with a ticker directly, but ``brief.entity_mentions`` lists the
 *     entities the LLM referenced (name + ticker). We scan each bullet's text
 *     for those names and surface a small ticker pill — a deep-link to the
 *     instrument page — when one is found.
 *   - "impact window"            → BACKEND GAP. ``BriefCitation`` carries only
 *     ``document_id``/``title``/``url``/``source_type``/``snippet``. The
 *     per-article price-impact windows (``ImpactWindows``: t0/t1/t2/t5) live on
 *     the news article model, NOT on the brief citation. Surfacing them here
 *     would require S8 to join the article's impact windows into each
 *     ``BriefCitation``. We do NOT fabricate them — see FOLLOW-UP note below.
 *
 * FOLLOW-UP (backend): to fully satisfy roadmap #8 the S8 brief schema needs
 * ``BriefCitation.impact_window`` (or a resolved ticker per bullet) so the
 * frontend can render the price-impact magnitude alongside each catalyst. The
 * data exists in market-data (``ImpactWindows``) but is not threaded into the
 * brief payload today.
 *
 * DATA SOURCE: S8 PublicBriefingResponse (BriefingResponse in types/api.ts)
 * DESIGN REFERENCE: roadmap 2026-06-19 §3(c) C3, DESIGN_SYSTEM.md (terminal dark)
 */

"use client";
// WHY "use client": renders interactive next/link chips (source + ticker
// deep-links). The parent MorningBriefCard is already a client component.

import Link from "next/link";
import type {
  BriefSection,
  BriefBullet,
  BriefCitation,
  BriefingCitation,
  BriefingEntityMention,
} from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * MAX_PREVIEW_SECTIONS — how many sections the COLLAPSED preview renders.
 * The collapsed card is a single Row-1 cell; showing every section would
 * defeat the point of the "Read more" affordance. 2 sections (typically
 * "Market Snapshot" + "Portfolio Impact") give the trader the headline
 * catalysts; the rest live in the expanded StructuredBrief view.
 */
const MAX_PREVIEW_SECTIONS = 2;

/**
 * MAX_BULLETS_PER_SECTION — cap the bullets rendered per previewed section.
 * Most sections have 2-4 bullets; 2 keeps each section to ~2 lines so the
 * whole preview stays inside the collapsed card height without scrolling.
 */
const MAX_BULLETS_PER_SECTION = 2;

/**
 * MAX_SOURCE_CHIPS_PER_BULLET — cap inline source chips per catalyst bullet.
 * Bullets usually cite 1-2 sources; capping at 2 in the compact preview keeps
 * each bullet to a single visual line. The expanded view shows up to 3.
 */
const MAX_SOURCE_CHIPS_PER_BULLET = 2;

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * stripCitationMarkers — remove the cryptic inline ``[cN]`` / ``[N#]`` markers
 * the LLM weaves into bullet text. The frontend renders citation chips
 * separately, so these markers are pure visual noise here (mirrors the same
 * strip in StructuredBrief.tsx and MorningBriefCard.tsx). Digit-only forms are
 * targeted so legitimate brackets (e.g. ``[2026-06-30]`` date ranges) survive.
 */
function stripCitationMarkers(text: string): string {
  return text
    .replace(/\s*\[(?:c|N)\d+\]/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

/**
 * extractDomain — short host label for a source chip ("bloomberg.com").
 * Never throws — a malformed URL must not crash the dashboard cell.
 */
function extractDomain(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "source";
  }
}

/**
 * firstMentionInText — find the first entity_mention whose name appears in the
 * bullet text, so we can surface its ticker as an affected-instrument pill.
 *
 * WHY case-insensitive substring (not word-boundary regex): entity names can
 * contain regex-special characters and multi-word forms ("Apple Inc."). A
 * simple lowercased ``includes`` is robust, cheap, and good enough for a
 * "which tickers does this catalyst touch" hint. We prefer mentions that carry
 * a ticker (the pill is only useful when it deep-links to an instrument page).
 */
function firstMentionInText(
  text: string,
  mentions: BriefingEntityMention[],
): BriefingEntityMention | null {
  const haystack = text.toLowerCase();
  // Prefer ticker-bearing mentions first so the pill always deep-links cleanly.
  const ordered = [...mentions].sort((a, b) => {
    const at = a.ticker ? 0 : 1;
    const bt = b.ticker ? 0 : 1;
    return at - bt;
  });
  for (const m of ordered) {
    if (m.name && haystack.includes(m.name.toLowerCase())) return m;
  }
  return null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * SourceChip — a compact, clickable source-domain chip for one citation.
 * Only article citations carry a navigable URL; event/alert citations render
 * as a non-interactive label so the trader still sees the source type.
 */
function SourceChip({ citation }: { citation: BriefCitation | BriefingCitation }) {
  // WHY back-compat key/id resolution: W4+ emits ``document_id``; pre-W4 cached
  // responses emit ``source_id``. Either may be present.
  const url = citation.url ?? null;
  const domain = url ? extractDomain(url) : citation.source_type;

  if (url && citation.source_type === "article") {
    return (
      <Link
        href={url}
        // WHY new tab: article URLs go to external publishers — keep the
        // dashboard visible while the trader reads the underlying story.
        target="_blank"
        rel="noopener noreferrer"
        title={citation.title}
        className="inline-flex max-w-[140px] items-center rounded-[2px] border border-border/60 bg-muted/50 px-1 py-0.5 font-mono text-[9px] uppercase tracking-[0.04em] text-muted-foreground/80 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <span className="truncate">{domain}</span>
      </Link>
    );
  }

  // Non-navigable source (event/alert, or article without a URL).
  return (
    <span
      title={citation.title}
      className="inline-flex max-w-[140px] items-center rounded-[2px] border border-border/40 bg-muted/30 px-1 py-0.5 font-mono text-[9px] uppercase tracking-[0.04em] text-muted-foreground/50"
    >
      <span className="truncate">{domain}</span>
    </span>
  );
}

/**
 * CatalystBullet — a single cited catalyst row: the claim text, an optional
 * affected-ticker pill (deep-link to the instrument page), and the source
 * chip(s) that back the claim.
 */
function CatalystBullet({
  bullet,
  mentions,
}: {
  bullet: BriefBullet;
  mentions: BriefingEntityMention[];
}) {
  const text = stripCitationMarkers(bullet.text);
  // Empty after stripping (a bullet that was only a marker) → render nothing.
  if (!text) return null;

  const citations = (bullet.citations ?? []).slice(0, MAX_SOURCE_CHIPS_PER_BULLET);
  // Best-effort affected-instrument pill — only when the bullet text names a
  // known entity that carries a ticker (so the pill deep-links cleanly).
  const mention = firstMentionInText(text, mentions);
  const ticker = mention?.ticker ?? null;
  // PRD-0089 F2 §6.6 convention: prefer ticker-first instrument URLs.
  const instrumentSlug = ticker ?? mention?.entity_id ?? null;

  return (
    <li
      // WHY a leading dot pseudo-element (before:): a terminal-grade bullet
      // marker that aligns with the StructuredBrief expanded view, so the
      // collapsed preview and the expanded view read as the same component.
      className="relative pl-2.5 text-[11px] leading-[1.45] text-foreground/90 before:absolute before:left-0 before:top-[7px] before:h-[3px] before:w-[3px] before:rounded-full before:bg-primary/70"
    >
      <span>{text}</span>

      {/* Affected-ticker pill + source chips — wrapped so they flow onto a
          second line on narrow cells rather than overflowing the row. */}
      {(instrumentSlug || citations.length > 0) && (
        <span className="ml-1.5 inline-flex flex-wrap items-center gap-1 align-middle">
          {/* Affected instrument deep-link (best-effort; see firstMentionInText). */}
          {instrumentSlug && (
            <Link
              href={`/instruments/${instrumentSlug}`}
              title={mention?.name ?? undefined}
              className="inline-flex items-center rounded-[2px] border border-primary/40 bg-primary/10 px-1 py-0.5 font-mono text-[9px] uppercase tracking-[0.04em] text-primary transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {ticker ?? mention?.name}
            </Link>
          )}
          {/* Source chips — the "cited" part of the cited brief. */}
          {citations.map((cit, i) => (
            <SourceChip
              // WHY index-based key: a bullet can cite the same domain/document
              // twice, and document_id may be absent on degenerate fixtures, so
              // the stable list position is the safest unique key here.
              key={`cit-${i}`}
              citation={cit}
            />
          ))}
        </span>
      )}
    </li>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export interface BriefCatalystPreviewProps {
  /** Parsed brief sections (already filtered of REMOVED placeholders upstream). */
  sections: BriefSection[];
  /** Entity mentions used to resolve affected-ticker pills. */
  mentions: BriefingEntityMention[];
}

/**
 * BriefCatalystPreview — the structured, cited collapsed-view body.
 *
 * Renders the first ``MAX_PREVIEW_SECTIONS`` sections as compact section
 * headers with up to ``MAX_BULLETS_PER_SECTION`` cited catalyst bullets each.
 * Returns ``null`` when there are no renderable sections so the caller can
 * fall back to the prose summary path (the live v4.x reality where
 * ``sections`` is empty — see MorningBriefCard).
 */
export function BriefCatalystPreview({
  sections,
  mentions,
}: BriefCatalystPreviewProps) {
  // Take the top N sections, dropping any with no bullets after slicing.
  const previewSections = sections
    .slice(0, MAX_PREVIEW_SECTIONS)
    .map((sec) => ({
      title: sec.title,
      bullets: (sec.bullets ?? []).slice(0, MAX_BULLETS_PER_SECTION),
    }))
    .filter((sec) => sec.bullets.length > 0);

  // Nothing renderable → let the caller use the prose fallback.
  if (previewSections.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5" data-testid="brief-catalyst-preview">
      {previewSections.map((sec, i) => (
        <section
          // WHY border-l primary rail: matches the expanded StructuredBrief
          // section treatment so the two views feel like one component.
          key={`${sec.title}-${i}`}
          className="border-l-2 border-primary/40 pl-2"
        >
          {/* Section heading — tracked uppercase to match the dashboard
              widget-header treatment. */}
          <h3 className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {sec.title}
          </h3>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {sec.bullets.map((bullet, j) => (
              <CatalystBullet key={j} bullet={bullet} mentions={mentions} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
