/**
 * components/brief/StructuredBrief.tsx — Shared structured brief renderer
 * (PLAN-0062-W4 T-W4-D-02)
 *
 * WHY THIS EXISTS:
 * Four surfaces render AI briefs: MorningBriefCard, InstrumentBriefPanel,
 * InstrumentAISubheader, and chat MessageBubble. Before W4 each surface had
 * its own ad-hoc markdown renderer — no citations, no confidence badge, no
 * lead block. Extracting a shared <StructuredBrief> component:
 *
 *   1. Enforces a single render pipeline for the W4 schema (BriefBullet with
 *      citations, lead, confidence) across all four surfaces.
 *   2. Makes future W4+ enhancements (e.g. confidence tooltips, citation
 *      footnote numbers) a one-file change instead of four.
 *   3. Provides three layout variants so each surface can tune density
 *      without forking the citation logic:
 *        - "compact" → single-column, small text, no confidence badge
 *        - "full"    → two-tier lead + sections, confidence badge (DEFAULT)
 *        - "inline"  → horizontal band, single-line lead, citation count only
 *
 * WHY CITATION CHIPS (not inline superscripts):
 * Bloomberg-style citation chips at the bottom of each bullet are more
 * scannable than inline [1] superscripts — traders can skim the citation
 * source domain at a glance without counting footnotes. The chip shows the
 * domain ("bloomberg.com") and opens the article in a new tab.
 *
 * WHY CONFIDENCE BADGE:
 * The confidence score [0.0–1.0] from S8 signals whether the LLM had
 * enough cited evidence to back every claim. A low score (<0.6) triggers
 * a muted amber "Low confidence" badge — not an error, just a heads-up.
 *
 * WHO USES THIS:
 * Wave E will wire this into MorningBriefCard, InstrumentBriefPanel,
 * InstrumentAISubheader, and MessageBubble. Wave D tests verify the component
 * in isolation before wiring.
 *
 * DATA SOURCE: S8 PublicBriefingResponse (BriefingResponse in types/api.ts)
 * DESIGN REFERENCE: PLAN-0062-W4 T-W4-D-02, PRD-0028 §6.5
 */

"use client";
// WHY "use client": StructuredBrief renders interactive citation chips
// (Link from next/link) and may conditionally animate the confidence ring.
// Even in "compact" and "inline" variants the component uses external URLs
// via next/link, which requires the client bundle.

import Link from "next/link";
import type { BriefSection, BriefBullet, BriefCitation, BriefingCitation } from "@/types/api";
import {
  resolveCitationLink,
  getCitationSourceId,
  getCitationDomain,
} from "./citation-link";
// PLAN-0066 Wave F T-W10-F-03: BulletFeedback provides per-bullet thumbs up/down.
// Dynamic import not needed — BulletFeedback is small and renders only when briefId
// is present. The parent (MorningBriefCard) is already "use client".
import { BulletFeedback } from "@/features/dashboard/components/BulletFeedback";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * StructuredBriefVariant — controls the density + chrome of the rendered brief.
 *
 * "compact" → Used in workspace panel or small card. Renders lead + sections
 *             without confidence badge. Citation chips are minimal (domain only).
 *
 * "full"    → Default. Used in MorningBriefCard expanded view and instrument
 *             detail page. Renders lead block, all sections, confidence badge,
 *             and full citation chips.
 *
 * "inline"  → Used in chat MessageBubble and InstrumentAISubheader horizontal
 *             band. Renders only the lead text + citation count chip. Sections
 *             are hidden to keep the band single-line.
 */
export type StructuredBriefVariant = "compact" | "full" | "inline";

export interface StructuredBriefProps {
  /**
   * The structured sections from BriefingResponse.sections. Required for the
   * "compact" and "full" variants; ignored in "inline" (which only renders lead).
   */
  sections?: BriefSection[];

  /**
   * The 1-2 sentence lead extracted from the ## LEAD block (PLAN-0062-W4).
   * Rendered at the top of the brief in all variants. Optional: when null/absent
   * the lead block is omitted entirely and sections render directly.
   */
  lead?: string | null;

  /**
   * Citation confidence score [0.0–1.0]. Rendered as a badge in the "full"
   * variant. Below 0.6 shows an amber "low confidence" indicator.
   * WHY optional: pre-W4 cached responses lack this field.
   */
  confidence?: number;

  /**
   * Layout variant — controls density, chrome, and which elements are visible.
   * Defaults to "full" when not provided.
   */
  variant?: StructuredBriefVariant;

  /**
   * Optional CSS class name for the root element. Use when the caller needs to
   * override margin, padding, or background for its grid cell.
   */
  className?: string;

  /**
   * PLAN-0066 Wave F: DB id of the persisted brief.
   * When provided, BulletFeedback widgets (thumbs up/down) are rendered on hover
   * for each bullet. When absent, no feedback widgets are shown.
   * WHY optional: instrument briefs, cached responses, and legacy contexts where
   * a brief ID is not available still render correctly without feedback widgets.
   */
  briefId?: string | null;

  /**
   * PLAN-0066 Wave F: auth token for the BulletFeedback POST.
   * Passed from the parent that owns useAuth(). Only used when briefId is present.
   */
  token?: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * CONFIDENCE_HIGH_THRESHOLD — at or above this score the confidence badge is
 * suppressed in "full" mode (high confidence is the expected state, no badge
 * needed). Below this threshold a muted amber badge is shown.
 *
 * WHY 0.6: this is the midpoint between "all bullets cited" (1.0) and
 * "no bullets cited" (0.0). A score below 0.6 means more than 40% of bullets
 * couldn't be resolved to a source — worth surfacing to the trader.
 */
const CONFIDENCE_HIGH_THRESHOLD = 0.6;

/**
 * MAX_CITATION_CHIPS — maximum citation chips rendered per bullet in "full"
 * variant. Most bullets have 1-2 citations; capping at 3 prevents very long
 * bullet rows when the LLM emits many [cN] markers.
 */
const MAX_CITATION_CHIPS = 3;

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * LeadProse — renders the lead block (1-2 sentence executive summary).
 *
 * WHY a separate sub-component: the lead has different typography than the
 * sections body (slightly larger, bolder). Isolating it avoids conditional
 * class-name mixing in the parent render function.
 *
 * WHY "not animated": the lead is always visible (no expand/collapse) — it's
 * the "above the fold" context line that appears in all three variants.
 */
export function LeadProse({
  lead,
  variant = "full",
}: {
  lead: string;
  variant?: StructuredBriefVariant;
}) {
  // WHY different sizes per variant: "full" is a card with plenty of vertical
  // space; "compact" is a dense workspace panel; "inline" is a single-line band.
  const textClass =
    variant === "full"
      ? "text-[11px] leading-snug text-foreground/90 font-medium"
      : variant === "compact"
        ? "text-[10px] leading-snug text-foreground/90"
        : // "inline" — single line, truncated
          "truncate text-[11px] leading-none text-foreground/90";

  // WHY strip [cN]: the backend intentionally keeps [cN] markers in the lead
  // field for inline display, but the frontend uses citation chips on bullets
  // instead of inline superscripts. Raw "[c6][c7]" leaks into the rendered
  // text when no chip rendering is wired to the lead block.
  const cleanLead = lead.replace(/\[c\d+\]/g, "").replace(/\s{2,}/g, " ").trim();

  return (
    // WHY border-l: visual signal that the lead is the primary takeaway from
    // the brief — mirrors Bloomberg's "lead paragraph" left-rail design pattern.
    <p
      className={`border-l-2 border-primary/60 pl-2 ${textClass}`}
      data-testid="brief-lead"
    >
      {cleanLead}
    </p>
  );
}

/**
 * CitationChips — renders a row of compact source chips for a single bullet.
 *
 * WHY chips (not inline [N] superscripts):
 * Chips show the source domain at a glance — traders can evaluate source
 * credibility (Bloomberg vs. generic feed) without clicking. Superscripts
 * require looking up a footnote; chips are self-contained.
 *
 * WHY max={MAX_CITATION_CHIPS}: prevents pathological cases where the LLM
 * emits [c1][c2][c3][c4][c5] for a single bullet, which would overflow the
 * row in compact panels.
 */
export function CitationChips({
  citations,
  max = MAX_CITATION_CHIPS,
}: {
  citations: (BriefCitation | BriefingCitation)[];
  max?: number;
}) {
  // WHY slice before map: we compute the overflow count BEFORE slicing for the
  // "+N more" indicator, then render only the first `max` chips.
  const visible = citations.slice(0, max);
  const overflow = citations.length - visible.length;

  return (
    // WHY flex-wrap: on narrow panels (workspace) chips may need to wrap to a
    // second line rather than forcing horizontal scroll.
    <div className="mt-0.5 flex flex-wrap items-center gap-1" data-testid="citation-chips">
      {visible.map((cit) => {
        const id = getCitationSourceId(cit);
        const domain = getCitationDomain(cit);
        const link = resolveCitationLink(cit);

        if (link.kind === "external") {
          return (
            <Link
              key={id}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              // WHY title={cit.title}: tooltip shows full article headline on hover,
              // since the chip body is truncated to the domain name only.
              title={cit.title}
              className="inline-flex max-w-[180px] items-center gap-0.5 rounded border border-border/60 bg-muted/50 px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-[0.06em] text-muted-foreground/80 hover:bg-muted hover:text-foreground"
            >
              {/* WHY truncate: long domains like "finance.yahoo.com" would overflow
                  the compact chip if not constrained. */}
              <span className="truncate">{domain}</span>
            </Link>
          );
        }

        // WHY "none" citations render as non-interactive chips: events and alerts
        // don't yet have navigable detail pages. We still show the source domain
        // so the trader knows what type of document backed the claim.
        return (
          <span
            key={id}
            title={cit.title}
            className="inline-flex max-w-[180px] items-center gap-0.5 rounded border border-border/40 bg-muted/30 px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-[0.06em] text-muted-foreground/50"
          >
            <span className="truncate">{domain}</span>
          </span>
        );
      })}

      {/* WHY overflow indicator: when a bullet has > max citations we show
          "+N more" so the trader knows there are additional sources even though
          we don't render all chips inline (to preserve row height). */}
      {overflow > 0 && (
        <span className="text-[9px] text-muted-foreground/50">+{overflow} more</span>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

/**
 * StructuredBrief — shared renderer for PLAN-0062-W4 brief schema.
 *
 * Renders:
 *  1. Optional confidence badge (full variant only, when confidence < threshold)
 *  2. Lead block (LeadProse sub-component) — when lead is present
 *  3. Sections grid — BriefSection[] with BriefBullet citations (compact/full)
 *
 * The "inline" variant renders ONLY the lead (or a citation-count chip when
 * lead is absent) — suitable for the InstrumentAISubheader horizontal band.
 *
 * @example
 * // Full variant (default) — dashboard card expanded view:
 * <StructuredBrief
 *   lead={brief.lead}
 *   sections={brief.sections}
 *   confidence={brief.confidence}
 * />
 *
 * // Compact variant — workspace panel:
 * <StructuredBrief
 *   lead={brief.lead}
 *   sections={brief.sections}
 *   variant="compact"
 * />
 *
 * // Inline variant — chat message bubble:
 * <StructuredBrief lead={brief.lead} variant="inline" />
 */
export function StructuredBrief({
  sections = [],
  lead,
  confidence,
  variant = "full",
  className = "",
  briefId,
  token,
}: StructuredBriefProps) {
  // ── Confidence badge ─────────────────────────────────────────────────────
  // WHY only in "full": compact and inline variants are space-constrained —
  // a confidence badge would clutter a workspace panel or chat bubble.
  // WHY only when below threshold: high-confidence briefs (the normal case)
  // shouldn't distract the trader with a green "confidence: 0.95" badge.
  const showConfidenceBadge =
    variant === "full" &&
    confidence !== undefined &&
    confidence < CONFIDENCE_HIGH_THRESHOLD;

  // ── Inline variant — lead-only render path ───────────────────────────────
  // WHY a separate early-return: the inline variant needs no sections, no
  // dividers, and no confidence badge — returning early avoids cluttering
  // the main render path with three-way conditionals.
  if (variant === "inline") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        {lead ? (
          <LeadProse lead={lead} variant="inline" />
        ) : (
          // WHY citation count fallback: when no lead is available (pre-W4 brief
          // or instrument brief that didn't produce a lead block), show the
          // total number of cited sources as a minimal inline indicator.
          <span className="text-[11px] text-muted-foreground/70">
            {sections.reduce((n, s) => n + s.bullets.length, 0)} points
          </span>
        )}
        {/* WHY citation total chip: a compact indicator of how many source
            documents backed this brief — meaningful in a single-line band
            where the full chip-per-bullet layout doesn't fit. */}
        {confidence !== undefined && (
          <ConfidenceIndicator confidence={confidence} inline />
        )}
      </div>
    );
  }

  // ── Full / compact render path ──────────────────────────────────────────
  return (
    <div
      className={`flex flex-col gap-1.5 ${className}`}
      data-testid="structured-brief"
    >
      {/* ── Confidence badge (full variant only, low confidence) ─────────── */}
      {showConfidenceBadge && (
        <ConfidenceIndicator confidence={confidence} />
      )}

      {/* ── Lead block ───────────────────────────────────────────────────── */}
      {lead && <LeadProse lead={lead} variant={variant} />}

      {/* ── Sections ─────────────────────────────────────────────────────── */}
      {sections.length > 0 && (
        <div
          className={`flex flex-col ${variant === "full" ? "gap-2" : "gap-1"}`}
          data-testid="brief-sections"
        >
          {sections.map((sec, i) => (
            <BriefSectionBlock
              key={`${sec.title}-${i}`}
              section={sec}
              sectionIdx={i}
              variant={variant}
              briefId={briefId}
              token={token}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── BriefSectionBlock ─────────────────────────────────────────────────────────

/**
 * BriefSectionBlock — renders a single BriefSection (title + bullets).
 *
 * WHY separate from StructuredBrief: keeps the section-level rendering isolated
 * so it can be unit-tested independently. Also makes the variant-specific
 * class logic easier to follow than one large conditional inside StructuredBrief.
 */
function BriefSectionBlock({
  section,
  sectionIdx,
  variant,
  briefId,
  token,
}: {
  section: BriefSection;
  sectionIdx: number;
  variant: StructuredBriefVariant;
  briefId?: string | null;
  token?: string;
}) {
  const headingClass =
    variant === "full"
      ? "mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
      : "mb-0 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/70";

  return (
    // WHY border-l in "full": the primary/40 left rail is the W4 canonical
    // visual marker for a structured brief section (mirrors MorningBriefCard).
    // "compact" uses a thinner/muted rail to fit more sections in less space.
    <section
      className={
        variant === "full"
          ? "border-l-2 border-primary/40 pl-2"
          : "border-l border-border/60 pl-1.5"
      }
      data-testid="brief-section"
    >
      <h3 className={headingClass}>{section.title}</h3>
      <ul className="m-0 list-none p-0">
        {section.bullets.map((bullet: BriefBullet, j: number) => (
          <BriefBulletItem
            key={j}
            bullet={bullet}
            bulletIdx={j}
            sectionIdx={sectionIdx}
            variant={variant}
            briefId={briefId}
            token={token}
          />
        ))}
      </ul>
    </section>
  );
}

// ── BriefBulletItem ────────────────────────────────────────────────────────────

/**
 * BriefBulletItem — renders a single BriefBullet with optional citation chips.
 *
 * WHY citations below the text (not inline): inline superscripts break the
 * reading flow of a dense 10px brief. Chips below the bullet text are visually
 * subordinate (smaller, muted) and don't interrupt the main claim.
 *
 * WHY hide citations in "compact": compact variant is used in the workspace
 * panel where vertical space is precious — showing all citation chips would
 * double the height of each bullet. The section structure (with bullet text)
 * is still shown; citations are accessible via the "full" variant instead.
 */
function BriefBulletItem({
  bullet,
  bulletIdx,
  sectionIdx,
  variant,
  briefId,
  token,
}: {
  bullet: BriefBullet;
  bulletIdx: number;
  sectionIdx: number;
  variant: StructuredBriefVariant;
  briefId?: string | null;
  token?: string;
}) {
  const bulletClass =
    variant === "full"
      ? "relative pl-2 text-[10px] leading-snug text-foreground/90 before:absolute before:left-0 before:top-1.5 before:h-[3px] before:w-[3px] before:rounded-full before:bg-primary/60"
      : "relative pl-2 text-[9px] leading-snug text-foreground/80 before:absolute before:left-0 before:top-1.5 before:h-[2px] before:w-[2px] before:rounded-full before:bg-muted-foreground/60";

  // WHY bullet.citations ?? []: citations is technically optional in BriefBullet
  // (see the type definition) to support legacy string-bullet adapters in tests.
  // In W4+ production responses citations is always populated (≥1 citation).
  const citations = bullet.citations ?? [];

  return (
    // WHY "group": enables the BulletFeedback hover reveal via Tailwind's
    // "group-hover:opacity-100" pattern. Without "group" on the parent <li>,
    // the opacity-0 BulletFeedback would never become visible on hover.
    <li className={`${bulletClass} group`}>
      <span>
        {bullet.text}
        {/* PLAN-0066 Wave F T-W10-F-03: thumbs up/down feedback on hover.
            WHY only in "full" + briefId: compact/inline variants are space-constrained
            (workspace panels, chat bubbles) where feedback buttons are intrusive.
            briefId is required to POST the feedback — without it we have no brief
            to attach the reaction to. */}
        {variant === "full" && briefId && token && (
          <BulletFeedback
            token={token}
            briefId={briefId}
            sectionIdx={sectionIdx}
            bulletIdx={bulletIdx}
          />
        )}
      </span>
      {/* WHY only in "full": citation chips add height — suppress in compact */}
      {variant === "full" && citations.length > 0 && (
        <CitationChips citations={citations} />
      )}
    </li>
  );
}

// ── ConfidenceIndicator ───────────────────────────────────────────────────────

/**
 * ConfidenceIndicator — a compact badge showing the citation confidence score.
 *
 * WHY amber color: the design system reserves amber (#FFD60A, CSS var --warning)
 * for informational signals that need attention but are not errors. A low
 * confidence score is a caution, not a failure — amber matches the visual
 * language already used for "stale" and "delayed" badges elsewhere.
 *
 * WHY show the numeric score: traders are quantitatively minded. A "Low
 * confidence (0.42)" message is more actionable than just "Low confidence" —
 * they can decide whether 0.42 is acceptable for a quick skim vs. 0.08 for
 * a trading decision.
 *
 * @param inline - When true renders as a compact chip (for the "inline" variant).
 */
function ConfidenceIndicator({
  confidence,
  inline = false,
}: {
  confidence: number;
  inline?: boolean;
}) {
  // WHY toFixed(2): the score is a float in [0.0, 1.0] with 4 decimal places
  // (e.g. 0.4231). Two decimal places (0.42) is precise enough for a badge
  // without being unnecessarily verbose.
  const label = `${Math.round(confidence * 100)}%`;

  if (inline) {
    return (
      <span
        className="shrink-0 rounded border border-warning/40 px-1 py-0.5 font-mono text-[9px] text-warning/80"
        title={`Citation confidence: ${label}`}
        data-testid="confidence-indicator"
      >
        {label}
      </span>
    );
  }

  return (
    // WHY bg-warning/5: very subtle tinted background so the badge doesn't
    // look like a critical error — just a heads-up.
    <div
      className="flex items-center gap-1.5 rounded border border-warning/30 bg-warning/5 px-2 py-1"
      data-testid="confidence-indicator"
    >
      {/* WHY triangular warning icon as a Unicode char (not SVG): avoids an
          extra lucide import that would bloat the component bundle. The ⚠
          character is universally supported and matches the muted amber palette. */}
      <span className="text-[10px] text-warning/80" aria-hidden="true">⚠</span>
      <span className="text-[10px] text-warning/80">
        Low confidence ({label})
      </span>
      <span className="text-[9px] text-muted-foreground/60">
        — some claims may lack full citation coverage
      </span>
    </div>
  );
}
