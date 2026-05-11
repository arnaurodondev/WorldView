/**
 * components/docs/mdx/CodeBlock.tsx — syntax-highlighted code with copy (T-B-2-05)
 *
 * WHY THIS EXISTS: Wraps the highlighted <pre> output from rehype-pretty-code
 * (Shiki) with a copy-to-clipboard button and an optional file-name label.
 * MDX authors write fenced code blocks normally:
 *
 *     ```ts title="lib/foo.ts"
 *     export const x = 1;
 *     ```
 *
 * and rehype-pretty-code emits the highlighted markup which this component
 * then chrome-wraps.
 *
 * WHY CLIENT COMPONENT: the Copy button uses navigator.clipboard, which
 * requires "use client". The <pre>/<code> highlighted children are passed
 * through unchanged so they remain server-rendered.
 */

"use client";

import { useState, useRef, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface CodeBlockProps {
  /** Optional filename rendered as a top-bar label. */
  title?: string;
  /** The Shiki-highlighted <pre><code>...</code></pre> children. */
  children: ReactNode;
  /** Optional language label (e.g. "ts", "py") rendered top-right. */
  lang?: string;
}

export function CodeBlock({ title, children, lang }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  // We hold a ref to the rendered <pre> so we can read its text content
  // for the clipboard write — we don't have direct access to the source.
  const preRef = useRef<HTMLDivElement | null>(null);

  async function handleCopy() {
    const text = preRef.current?.innerText ?? "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      // Reset the icon after 1.5s — long enough to register, short enough
      // that another copy doesn't feel "stuck" in success state.
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Older browsers / blocked permissions — silently no-op (user can
      // still select the text manually). No alert popup; we don't want
      // to interrupt reading flow over a non-critical failure.
    }
  }

  return (
    <div className="my-5 overflow-hidden rounded-[2px] border border-border/40 bg-card">
      {(title || lang) && (
        <div className="flex items-center justify-between border-b border-border/40 bg-muted/40 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {/* QA iter-1 (design m-D7): only render the title span when set;
              an empty span made flex layout asymmetric. */}
          {title ? <span>{title}</span> : <span aria-hidden="true" />}
          {lang ? <span className="text-muted-foreground/60">{lang}</span> : null}
        </div>
      )}
      {/* QA iter-1 (bugs m-3, a11y m-3): the copy button uses
          group-hover:opacity-100; the `group` MUST sit on an ancestor that
          contains BOTH the button and the code. The previous arrangement
          had `group` on the inner div (button's sibling), so the button
          was effectively invisible on desktop. focus-within reveals the
          button when keyboard users tab to it. */}
      <div className="group relative">
        {/* Visually-hidden live region announces clipboard success to
            screen readers — required to make the copy action perceivable
            without sight. QA iter-1 (a11y M-A5). */}
        <span role="status" aria-live="polite" className="sr-only">
          {copied ? "Copied to clipboard" : ""}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label="Copy code"
          className={cn(
            "absolute right-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-[2px] border border-border/40 bg-card/80 text-muted-foreground opacity-0 transition-opacity hover:text-foreground",
            "group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100",
            // Always visible on touch devices where hover-reveal doesn't work.
            "[@media(hover:none)]:opacity-100",
          )}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-positive" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </button>
        <div ref={preRef}>{children}</div>
      </div>
    </div>
  );
}
