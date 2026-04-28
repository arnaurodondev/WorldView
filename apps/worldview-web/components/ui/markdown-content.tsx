/**
 * components/ui/markdown-content.tsx — Centralized markdown renderer
 *
 * WHY THIS EXISTS: Multiple surfaces in the app render LLM/markdown content
 * (morning brief, instrument briefs, intelligence tab, AI chat). Each one had
 * its own copy of the same ReactMarkdown configuration with subtly different
 * styling — drift produced inconsistent looks (different code-block colours,
 * different table borders). Centralising the renderer here gives every surface
 * the same Bloomberg/terminal-style typography and removes the drift risk.
 *
 * SIZE VARIANTS (per PLAN-0049 T-B-2-08):
 *   - "compact"     — 10px base font, tighter spacing, used inside dense
 *                     widgets (morning brief card, intelligence tab summary).
 *   - "comfortable" — 12px base font, slightly looser spacing, used on full
 *                     pages (briefing detail, instrument intelligence page).
 *
 * STYLING TOKENS (DESIGN_SYSTEM.md):
 *   - rounded-[2px] only (no rounded-md)
 *   - Tables: border-collapse + border-border/40 + zebra rows
 *   - Code:   bg-muted/30 + font-mono + rounded-[2px] px-1
 *
 * WHO USES IT: future Wave D consumers (T-D-4-01..03), and the existing
 * ReactMarkdown call sites should migrate to this.
 */

// WHY no "use client": pure presentational. ReactMarkdown is a client-safe
// React component that does not touch browser APIs at the module top level.

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface MarkdownContentProps {
  /** Markdown source text. */
  children: string;
  /**
   * Density variant.
   * - "compact"     — 10px base, dense widgets (default-tighter morning brief)
   * - "comfortable" — 12px base, full-width detail pages (default)
   */
  size?: "compact" | "comfortable";
  /** Optional extra Tailwind classes appended to the wrapper. */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * MarkdownContent — render LLM markdown with consistent dark-theme styling.
 *
 * Usage:
 *   <MarkdownContent size="compact">{briefText}</MarkdownContent>
 */
export function MarkdownContent({
  children,
  size = "comfortable",
  className,
}: MarkdownContentProps): ReactNode {
  // WHY size-keyed token bag: keeps every override below readable — it would
  // be unreadable to interleave conditional class strings inside each override.
  const t =
    size === "compact"
      ? {
          base: "text-[10px] leading-[1.5]",
          h2: "mt-2 mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-foreground",
          h3: "mt-2 mb-0.5 text-[10px] font-semibold text-foreground",
          p: "my-1 text-muted-foreground",
          li: "ml-3 list-disc text-muted-foreground",
          tableText: "text-[10px]",
        }
      : {
          base: "text-[12px] leading-[1.6]",
          h2: "mt-3 mb-1.5 text-[13px] font-semibold uppercase tracking-[0.06em] text-foreground",
          h3: "mt-2.5 mb-1 text-[12px] font-semibold text-foreground",
          p: "my-1.5 text-muted-foreground",
          li: "ml-4 list-disc text-muted-foreground",
          tableText: "text-[12px]",
        };

  return (
    <div
      // WHY font-mono on the wrapper: Bloomberg/terminal aesthetic — IBM Plex
      // Mono is the canonical font for data + prose alike. Per-element overrides
      // (e.g. code blocks) layer further tokens on top.
      className={cn("font-mono tabular-nums", t.base, className)}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // ── Headings ───────────────────────────────────────────────────────
          h2: ({ children: c }) => <h2 className={t.h2}>{c}</h2>,
          h3: ({ children: c }) => <h3 className={t.h3}>{c}</h3>,
          // ── Paragraph & list ───────────────────────────────────────────────
          p: ({ children: c }) => <p className={t.p}>{c}</p>,
          li: ({ children: c }) => <li className={t.li}>{c}</li>,
          // ── Links — primary colour, underline on hover only ────────────────
          a: ({ children: c, href }) => (
            <a
              href={href}
              className="text-primary hover:underline"
              // WHY noopener+noreferrer: any LLM-rendered link could be hostile;
              // strip referrer + opener to avoid leaking session info.
              target={href?.startsWith("http") ? "_blank" : undefined}
              rel={href?.startsWith("http") ? "noopener noreferrer" : undefined}
            >
              {c}
            </a>
          ),
          // ── Tables — border-collapse + zebra rows ──────────────────────────
          table: ({ children: c }) => (
            <table
              className={cn(
                "my-2 w-full border-collapse border border-border/40",
                t.tableText,
              )}
            >
              {c}
            </table>
          ),
          // WHY zebra via odd:bg-muted/20: cleaner than alternating thead/tbody
          // rules; preserved across nested tables (rare but possible).
          tr: ({ children: c }) => (
            <tr className="border-b border-border/40 odd:bg-muted/20">{c}</tr>
          ),
          th: ({ children: c }) => (
            <th className="border border-border/40 bg-muted/40 px-2 py-1 text-left font-semibold text-foreground">
              {c}
            </th>
          ),
          td: ({ children: c }) => (
            <td className="border border-border/40 px-2 py-1 text-muted-foreground">
              {c}
            </td>
          ),
          // ── Inline code & code blocks ─────────────────────────────────────
          // WHY split on `className`: ReactMarkdown sets `language-foo` on
          // block code (inside <pre>); inline code has no className. We use
          // the presence of className (or the parent <pre>) to tell them apart
          // and apply different padding.
          code: ({ className: cls, children: c }) => {
            const isBlock = !!cls;
            return (
              <code
                className={cn(
                  "rounded-[2px] bg-muted/30 px-1 font-mono",
                  isBlock ? "block py-1" : "py-0",
                )}
              >
                {c}
              </code>
            );
          },
          pre: ({ children: c }) => (
            <pre className="my-2 overflow-x-auto rounded-[2px] border border-border/40 bg-muted/30 p-2">
              {c}
            </pre>
          ),
          // ── Blockquote — left-rule, muted text ─────────────────────────────
          blockquote: ({ children: c }) => (
            <blockquote className="my-2 border-l-2 border-primary/40 pl-2 italic text-muted-foreground">
              {c}
            </blockquote>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
