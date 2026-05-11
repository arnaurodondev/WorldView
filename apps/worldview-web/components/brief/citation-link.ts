/**
 * components/brief/citation-link.ts — Citation deep-link helpers (T-W4-D-03)
 *
 * WHY THIS EXISTS: BriefCitation objects arrive from S8 with a `url` field that
 * may be null (for economic events and alerts that have no external URL) or a
 * full https:// URL (for news articles). Rather than scattering null-guards and
 * fallback logic across every component that renders citations, this module
 * provides a single helper that produces the correct href for each citation type.
 *
 * WHY A PURE FUNCTION (not a React hook): citation URL resolution is pure data
 * transformation — no side effects, no component state. A plain function is
 * simpler, faster, and easier to unit-test than a hook.
 *
 * DESIGN REFERENCE: PLAN-0062-W4 T-W4-D-03
 */

import type { BriefCitation, BriefingCitation } from "@/types/api";

/**
 * CitationLinkTarget — the resolved link destination for a citation.
 *
 * WHY a discriminated union (not just `string | null`): callers need to know
 * whether to render an `<a target="_blank">` (external article URL), an internal
 * Next.js `<Link>` (event/alert route), or plain text (no navigable destination).
 *
 * - `"external"`: opens in a new tab (`target="_blank" rel="noopener noreferrer"`)
 * - `"internal"`: rendered via Next.js `<Link>` for client-side navigation
 * - `"none"`: citation has no navigable destination; render as plain text
 */
export type CitationLinkTarget =
  | { kind: "external"; href: string }
  | { kind: "internal"; href: string }
  | { kind: "none" };

/**
 * resolveCitationLink — compute the correct link target for a brief citation.
 *
 * Dispatch table:
 *   article + url    → external (opens in new tab, points to publisher)
 *   article + no url → none (shouldn't happen in W4+ responses, but guard it)
 *   event            → none (economic events have no S9 detail page yet)
 *   alert            → none (alerts link to the alert drawer, not a URL)
 *
 * WHY "external" for articles: news article URLs always point to external
 * publishers (Reuters, Bloomberg, EODHD, etc.). Opening in a new tab keeps
 * the Worldview terminal visible while the trader reads the full story.
 *
 * WHY "none" for events/alerts: the platform doesn't yet have dedicated detail
 * pages for economic events or alerts that can be deep-linked from a brief.
 * When S9 adds those routes, this function can be extended to emit "internal"
 * targets for those types.
 *
 * @param citation - The BriefCitation or BriefingCitation to resolve.
 * @returns A CitationLinkTarget discriminated union.
 */
export function resolveCitationLink(
  citation: BriefCitation | BriefingCitation,
): CitationLinkTarget {
  if (citation.source_type === "article" && citation.url) {
    return { kind: "external", href: citation.url };
  }
  // Events and alerts don't have navigable URLs in this version.
  // Guard article with missing url (shouldn't occur post-W4 but defensive).
  return { kind: "none" };
}

/**
 * getCitationSourceId — get the stable identifier from a citation.
 *
 * WHY this helper: BriefCitation (W4+) uses `document_id` as the primary key;
 * BriefingCitation (pre-W4 back-compat) uses `source_id`. Components need a
 * stable key for React list rendering without duplicating this discriminator
 * logic in every render function.
 *
 * @param citation - The BriefCitation or BriefingCitation to extract the ID from.
 * @returns The citation's stable identifier string.
 */
export function getCitationSourceId(
  citation: BriefCitation | BriefingCitation,
): string {
  // WHY "in" check (not type guard): avoids importing the full Pydantic schema
  // at runtime. The `document_id` field discriminates W4+ from pre-W4 shapes.
  if ("document_id" in citation) {
    return citation.document_id;
  }
  return citation.source_id;
}

/**
 * getCitationDomain — extract a short source domain label from a citation.
 *
 * WHY: citation chips display the publisher domain ("BLOOMBERG.COM", "REUTERS.COM")
 * as a small uppercase prefix so traders can prioritise sources at a glance. This
 * mirrors the extractDomain() helper in MorningBriefCard but is centralised here
 * for reuse across the StructuredBrief component and any future citation UI.
 *
 * Returns "source" as a fallback when the citation has no URL or the URL is
 * malformed — never throws, because a thrown URL parse error would crash the card.
 *
 * @param citation - The BriefCitation or BriefingCitation to extract the domain from.
 * @returns Short lowercase domain string (e.g. "bloomberg.com", "reuters.com").
 */
export function getCitationDomain(
  citation: BriefCitation | BriefingCitation,
): string {
  if (!citation.url) return "source";
  try {
    const host = new URL(citation.url).hostname.toLowerCase();
    // WHY strip "www.": "www.bloomberg.com" → "bloomberg.com" is cleaner
    // in the compact chip label. Other subdomains (finance.yahoo.com) are
    // kept to disambiguate sub-properties.
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    // WHY swallow: a malformed URL in the citation should never crash the
    // brief — render a generic "source" label instead.
    return "source";
  }
}
