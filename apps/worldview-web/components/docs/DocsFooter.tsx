/**
 * components/docs/DocsFooter.tsx — page-bottom meta + edit link (T-B-2-06)
 *
 * WHY THIS EXISTS: Docs visitors expect three things at the bottom of a
 * page:
 *   1. Last-updated date — establishes how stale the doc is.
 *   2. Edit-on-GitHub link — ships unblocking community contributions.
 *   3. (Optional, mounted by the route) the DocsFeedback widget so
 *      readers can flag bad content.
 *
 * WHY SERVER COMPONENT: pure render — values are page-level props.
 */

import { ExternalLink } from "lucide-react";

interface DocsFooterProps {
  /** ISO-8601 date string from frontmatter, or undefined if absent. */
  updated?: string;
  /** GitHub edit URL (built from repo + relative path in the parent). */
  editUrl?: string;
}

/**
 * formatDate — render an ISO date as "Apr 30, 2026" for the footer line.
 * Uses Intl.DateTimeFormat with the en-US locale for stable across-zone
 * output that doesn't shift between server and client renders.
 */
function formatDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
}

export function DocsFooter({ updated, editUrl }: DocsFooterProps) {
  const updatedLabel = formatDate(updated);
  if (!updatedLabel && !editUrl) return null;

  return (
    <footer className="mt-12 flex flex-wrap items-center justify-between gap-3 border-t border-border/40 pt-5 text-xs text-muted-foreground">
      {updatedLabel ? (
        <span>
          Last updated <time dateTime={updated}>{updatedLabel}</time>
        </span>
      ) : (
        <span />
      )}
      {editUrl ? (
        <a
          href={editUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-primary hover:underline"
        >
          Edit this page on GitHub
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      ) : null}
    </footer>
  );
}
