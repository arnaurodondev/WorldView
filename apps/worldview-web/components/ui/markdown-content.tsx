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
  /**
   * P2C-5: When true, pre-processes the source to render `[N]` citation
   * markers as styled `<sup>` elements rather than plain text.
   *
   * WHY opt-in (not default): citation markers appear only in S8 RAG chat
   * responses. Enabling citation rendering on morning briefs, earnings cards,
   * or other surfaces could incorrectly style content like "[12]" in financial
   * notation (e.g. footnote refs in PDF-extracted text). Chat message bubbles
   * pass `withCitationSups` explicitly; all other callers get plain text.
   *
   * WHY pre-process (not a custom remark plugin): react-markdown v9 doesn't
   * expose a text-node component override. The sentinel-prefix approach
   * (`__cite__N`) is a deliberate internal encoding: the prefix cannot appear
   * in real markdown source text, so the `code` component can detect it safely
   * and short-circuit to a `<sup>` element without risk of collisions.
   */
  withCitationSups?: boolean;
  /**
   * Wave 3 (chat hardening): how many citations actually exist for this
   * message. When provided alongside `withCitationSups`, any `[N]` marker
   * with N > citationCount renders as a MUTED "dead" badge with a
   * "Source not available" tooltip instead of the primary-tinted live chip.
   *
   * WHY: the backend can emit inline markers ([5], [8]) that exceed the
   * citations array it delivered (observed live: markers up to [11] over a
   * 4-item list — a known S8 bug owned by the backend). The frontend must
   * degrade gracefully: a marker with no matching source must never look
   * like a clickable/trustworthy reference.
   *
   * WHY optional: callers that don't know the citation list (or render
   * non-chat content) omit it and get the legacy behaviour — every marker
   * styled as a live chip.
   */
  citationCount?: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * MarkdownContent — render LLM markdown with consistent dark-theme styling.
 *
 * Usage:
 *   <MarkdownContent size="compact">{briefText}</MarkdownContent>
 */
// ── Citation sentinel ─────────────────────────────────────────────────────────

/**
 * CITE_SENTINEL — internal prefix used to encode `[N]` citation markers for
 * the `withCitationSups` feature. Must be a string that:
 *   1. Cannot appear in normal markdown source (no `__` in real content).
 *   2. Produces valid inline code when backtick-wrapped: `__cite__1`
 *   3. Is detectable in the `code` component override below.
 *
 * WHY backtick-wrapped inline code as the transport: react-markdown v9 has no
 * text-node component override. Wrapping the sentinel in backticks produces an
 * `<code>` node, which the `code` component can intercept. The alternative
 * (rehype-raw + HTML passthrough) requires installing `rehype-raw`.
 */
const CITE_SENTINEL = "__cite__";

/**
 * preprocessCitations — replace `[N]` markers with backtick-wrapped sentinels
 * before passing to ReactMarkdown.
 *
 * Input:  "See the analysis [1] and the SEC filing [2]."
 * Output: "See the analysis `__cite__1` and the SEC filing `__cite__2`."
 *
 * WHY only 1-30 range: citation indices beyond 30 are unrealistic for a RAG
 * response (the retriever returns at most 15-20 chunks). Limiting the range
 * prevents false matches on "[31]" in financial data (e.g. "P/E [31.5x]").
 */
function preprocessCitations(source: string): string {
  return source.replace(/\[(\d{1,2})\]/g, (_match, num) => {
    const n = parseInt(num, 10);
    // Only encode 1–30 to avoid false positives on large numbers.
    if (n < 1 || n > 30) return _match;
    return `\`${CITE_SENTINEL}${num}\``;
  });
}

export function MarkdownContent({
  children,
  size = "comfortable",
  className,
  withCitationSups = false,
  citationCount,
}: MarkdownContentProps): ReactNode {
  // P2C-5: pre-process [N] markers → sentinel inline-code when opt-in.
  // WHY before the component body (not inside ReactMarkdown children): the
  // preprocessed string is stable per render — React will not re-run the
  // replacement unless `children` or `withCitationSups` changes.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- used in JSX at {source} below (ESLint false-positive: variable is referenced inside ReactMarkdown children)
  const source = withCitationSups ? preprocessCitations(children) : children;
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
        // P2C-5: use `source` (pre-processed when withCitationSups=true, else
        // identical to `children`) so citation markers reach the code override.
        components={{
          // ── Headings ───────────────────────────────────────────────────────
          h2: ({ children: c }) => <h2 className={t.h2}>{c}</h2>,
          h3: ({ children: c }) => <h3 className={t.h3}>{c}</h3>,
          // ── Paragraph & list ───────────────────────────────────────────────
          p: ({ children: c }) => <p className={t.p}>{c}</p>,
          li: ({ children: c }) => <li className={t.li}>{c}</li>,
          // ── Links — primary colour, underline on hover only ────────────────
          a: ({ children: c, href }) => {
            // WHY blocklist dangerous schemes (not allowlist): ReactMarkdown
            // does not sanitize href protocols. An LLM or compromised S8 backend
            // could emit `javascript:alert(1)` URIs that execute on click.
            // We block only executable-code schemes (javascript:, data:, vbscript:)
            // and allow everything else: https:, http:, mailto:, relative paths,
            // #anchors. An allowlist would incorrectly strip relative navigation.
            // `target=_blank` + `rel=noopener noreferrer` strips referrer+opener
            // on external links to prevent session-info leakage.
            const isDangerous =
              href != null && /^(javascript:|data:|vbscript:)/i.test(href.trim());
            const safeHref = isDangerous ? undefined : href;
            return (
              <a
                href={safeHref}
                className="text-primary hover:underline"
                target={safeHref?.startsWith("http") ? "_blank" : undefined}
                rel={safeHref?.startsWith("http") ? "noopener noreferrer" : undefined}
              >
                {c}
              </a>
            );
          },
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
          //
          // P2C-5 citation sentinel: when withCitationSups=true the source was
          // pre-processed to convert [N] → `__cite__N`. The code component
          // detects that prefix and short-circuits to a styled <sup> element.
          // WHY early return before isBlock check: sentinels are always inline
          // (no className), so this check is safe. If somehow a sentinel ends up
          // inside a fenced code block the isBlock path would have className set
          // and we'd fall through to normal code rendering — which is correct
          // (don't double-process).
          code: ({ className: cls, children: c }) => {
            // P2C-5: detect and render citation superscripts
            if (withCitationSups && !cls) {
              const text = typeof c === "string" ? c : "";
              if (text.startsWith(CITE_SENTINEL)) {
                const citNum = text.slice(CITE_SENTINEL.length);
                // Wave 3 (dead-marker hardening): when the caller told us how
                // many citations exist, markers beyond that range have NO
                // matching source — render a muted dead badge instead of the
                // live primary chip. line-through + muted colour + an explicit
                // tooltip make "this reference is broken upstream" legible
                // without pretending the marker is a usable link. (The marker
                // index itself is preserved so the prose still reads.)
                const isDead =
                  citationCount !== undefined &&
                  parseInt(citNum, 10) > citationCount;
                if (isDead) {
                  return (
                    <sup
                      className="cursor-default rounded-[2px] bg-muted/40 px-0.5 text-[8px] font-mono text-muted-foreground/60 line-through"
                      title="Source not available"
                      data-testid="dead-citation-marker"
                    >
                      [{citNum}]
                    </sup>
                  );
                }
                return (
                  // WHY these classes match AskAiPanel renderWithCitations:
                  // consistent citation styling across both the mini-panel and
                  // the full Chat thread (same primary/10 chip background, same
                  // font-mono 8px size). Visual vocabulary is unified.
                  <sup
                    className="cursor-default rounded-[2px] bg-primary/10 px-0.5 text-[8px] font-mono text-primary"
                    title={`Citation ${citNum}`}
                  >
                    [{citNum}]
                  </sup>
                );
              }
            }
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
        {source}
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
