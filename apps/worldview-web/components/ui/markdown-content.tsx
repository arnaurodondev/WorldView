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

// WHY "use client": code-block copy buttons (PLAN-0051 T-E-5-02) call
// navigator.clipboard.writeText which is browser-only. Adding the directive
// here keeps the rendering tree client-side throughout — no SSR mismatch.

"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
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
          // WHY a custom <pre>: PLAN-0051 T-E-5-02 — code blocks need a "Copy"
          // affordance in the top-right corner. Wrapping the markdown <pre>
          // in a relative container lets us absolutely-position the button
          // without disturbing existing layout.
          pre: ({ children: c }) => <CopyableCodeBlock>{c}</CopyableCodeBlock>,
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

// ── Copyable code block ──────────────────────────────────────────────────────

/**
 * CopyableCodeBlock — `<pre>` wrapper with a "Copy" icon-button overlay.
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-02): LLMs frequently emit code/JSON
 * snippets the trader wants to paste somewhere else (a query, a script,
 * a Slack message). A built-in copy button removes the manual select-all
 * + Cmd-C friction.
 *
 * WHY extract from the inline component map: ReactMarkdown's component
 * overrides cannot easily own React state. Lifting this into its own small
 * component lets us useState for the copied/idle toggle.
 *
 * WHY innerText (not the raw markdown source): ReactMarkdown renders the
 * content into DOM children, and traversing that subtree gives us the exact
 * string the user sees. Reading from the DOM also handles syntax-highlighted
 * variants if a future plugin adds them.
 */
function CopyableCodeBlock({ children }: { children: ReactNode }) {
  // WHY state: the button morphs from "Copy" to "Copied" for ~1.5s after a
  // successful click. A boolean flag is the simplest model.
  const [copied, setCopied] = useState(false);

  /**
   * onCopyClick — read the rendered code string and write to the clipboard.
   *
   * WHY data-* selector + closest(): the click bubbles from the button up
   * through the wrapper. We find the wrapping <pre> via the data-attribute
   * to read its plain-text contents. This avoids prop-drilling the source
   * string and keeps the API simple.
   *
   * WHY swallow the error: clipboard writes can fail in older browsers /
   * insecure contexts. We do not want to throw inside a render tree —
   * silently leave the button unchanged so the user can fall back to manual
   * copy.
   */
  function onCopyClick(e: React.MouseEvent<HTMLButtonElement>) {
    const wrapper = (e.currentTarget.closest("[data-md-codeblock]") ?? null) as HTMLElement | null;
    const text = wrapper?.querySelector("pre")?.innerText ?? "";
    if (!text) return;
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      // WHY 1500ms: long enough to register the success, short enough that
      // the button is back to "Copy" before the user reaches for it again.
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    // WHY data-md-codeblock: scoped selector for the click handler above.
    <div data-md-codeblock className="relative my-2">
      <pre
        // WHY rounded-[2px]: design-system 2px radius rule.
        // WHY pr-10: leave room for the absolutely-positioned Copy button.
        className="overflow-x-auto rounded-[2px] border border-border/40 bg-muted/30 p-2 pr-10"
      >
        {children}
      </pre>
      <button
        type="button"
        onClick={onCopyClick}
        // WHY top-1 right-1: hugs the corner of the code block without
        // overlapping content thanks to pr-10 above.
        className={cn(
          "absolute right-1 top-1",
          "inline-flex items-center gap-1 rounded-[2px] border border-border/60 bg-card",
          "px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em]",
          "text-muted-foreground hover:bg-muted hover:text-foreground",
          "focus:outline-none focus:ring-1 focus:ring-primary",
        )}
        aria-label="Copy code"
      >
        {copied ? (
          <>
            <Check className="h-3 w-3" />
            Copied
          </>
        ) : (
          <>
            <Copy className="h-3 w-3" />
            Copy
          </>
        )}
      </button>
    </div>
  );
}
