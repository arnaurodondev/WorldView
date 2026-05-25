/**
 * components/docs/mdx/components.tsx — MDX component map (T-B-2-05)
 *
 * WHY THIS EXISTS: next-mdx-remote/rsc accepts a `components` map that
 * substitutes JSX renderers for HTML tags emitted by MDX. We use it to:
 *   1. Style raw markdown elements (h1/h2/h3, p, ul, ol, blockquote, …)
 *      consistently with the design system.
 *   2. Inject heading anchors so the TOC scroll-spy can find them.
 *   3. Make our custom components (Callout, CodeBlock, DocsTabs, Steps)
 *      available in MDX without explicit imports per-file.
 *
 * WHY HEADING ANCHORS: <DocsTableOfContents> renders an aside with links
 * pointing to #slug; without IDs on the headings the links lead nowhere.
 */

import type { ReactNode } from "react";
import Link from "next/link";

import { Callout } from "./Callout";
import { CodeBlock } from "./CodeBlock";
import { DocsTabs, DocsTab } from "./DocsTabs";
import { Steps, Step } from "./Steps";
// QA iter-1 (bugs m-4): use the shared slugifyHeading from lib/docs.ts
// so TOC anchors and rendered heading IDs cannot drift apart.
import { slugifyHeading as slugify } from "@/lib/docs";

/**
 * sanitiseHref — block javascript:/data:/vbscript: schemes from MDX
 * authored links. The trusted-author threat model accepts MDX execution
 * server-side, but a stray javascript: URL in body content would still
 * fire on click. Defense-in-depth.
 *
 * QA iter-1 (security m-9).
 */
function sanitiseHref(href: string | undefined): string {
  if (!href) return "#";
  const lower = href.trim().toLowerCase();
  if (lower.startsWith("javascript:") || lower.startsWith("data:") || lower.startsWith("vbscript:")) {
    return "#";
  }
  return href;
}

/**
 * textOf — extract plain text from a React node tree. Used to compute
 * heading IDs when the heading children are MDX nodes (e.g., a heading
 * containing inline code or links). Falls back to empty string.
 */
function textOf(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

/**
 * mdxComponents — passed to next-mdx-remote/rsc's <MDXRemote components={…} />.
 * Every entry's key is either a raw HTML tag name (h2, p, ul, …) or a
 * custom component name MDX authors can reference (Callout, etc.).
 */
export const mdxComponents = {
  // ── Headings ──────────────────────────────────────────────────────────
  // QA iter-1 (design M-D2): differentiate h1 (orphan) from h2 so authors
  // get a visible cue when they accidentally write `# Title` in MDX.
  // Page-level h1 is rendered by page.tsx outside the MDX body. The amber
  // left-border on orphan h1 makes the lint failure obvious in dev.
  h1: ({ children }: { children?: ReactNode }) => (
    <h2 id={slugify(textOf(children))} className="mt-9 mb-2 border-l-2 border-primary pl-3 text-[24px] font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h2>
  ),
  // QA iter-1 (design M-D2): tighter rhythm — mt-10 → mt-9 / mb-3 → mb-2.
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 id={slugify(textOf(children))} className="mt-9 mb-2 text-[24px] font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 id={slugify(textOf(children))} className="mt-6 mb-1.5 text-[18px] font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h3>
  ),
  h4: ({ children }: { children?: ReactNode }) => (
    <h4 id={slugify(textOf(children))} className="mt-5 mb-2 text-[16px] font-semibold text-foreground scroll-mt-24">
      {children}
    </h4>
  ),

  // ── Body text ────────────────────────────────────────────────────────
  // QA iter-1 (design M-D1): bumped from text-muted-foreground +
  // leading-relaxed (consumer-SaaS) to text-foreground/90 + leading-6
  // (Bloomberg-grade — full-strength reading text, tight rhythm).
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-3 text-[14px] leading-6 text-foreground/90">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-3 list-disc space-y-1 pl-5 text-[14px] leading-6 text-foreground/90 marker:text-primary/60">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-3 list-decimal space-y-1 pl-5 text-[14px] leading-6 text-foreground/90 marker:text-primary/60">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="leading-6">{children}</li>,
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="my-5 border-l-2 border-primary/40 bg-muted/20 px-4 py-2 italic text-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-8 border-border/40" />,

  // ── Inline ───────────────────────────────────────────────────────────
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }: { children?: ReactNode }) => <em className="italic">{children}</em>,
  code: ({ children }: { children?: ReactNode }) => (
    // Inline `code` only (block code is handled by rehype-pretty-code <pre>).
    // QA iter-1 (design M-D3): bumped from text-[12px] / bg-muted/60 to
    // text-[13px] / bg-muted/80 — was reading as a downsize against 14px
    // body. Stripe/Vercel use ~0.9em with stronger bg differentiation.
    <code className="rounded-[2px] bg-muted/80 px-1 py-0.5 font-mono text-[13px] text-foreground">
      {children}
    </code>
  ),
  a: ({ href, children }: { href?: string; children?: ReactNode }) => {
    // QA iter-1 (security m-9): block javascript:/data:/vbscript: schemes.
    const safe = sanitiseHref(href);
    // QA iter-1 (design POLISH): always-underline body links so they're
    // scannable inside paragraphs. underline-offset-2 keeps it crisp.
    const cls =
      "text-primary underline decoration-primary/30 underline-offset-2 hover:decoration-primary";
    // Internal links use next/link for prefetching; external open in new tab.
    if (safe.startsWith("/")) {
      return (
        <Link href={safe} className={cls}>
          {children}
        </Link>
      );
    }
    return (
      <a href={safe} target="_blank" rel="noopener noreferrer" className={cls}>
        {children}
      </a>
    );
  },

  // ── Tables ───────────────────────────────────────────────────────────
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-5 overflow-x-auto rounded-[2px] border border-border/40">
      <table className="w-full text-left text-[14px]">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border-b border-border/40 bg-muted/40 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="border-b border-border/20 px-3 py-2 text-[14px] text-foreground">{children}</td>
  ),

  // ── Custom components ────────────────────────────────────────────────
  Callout,
  CodeBlock,
  DocsTabs,
  DocsTab,
  Steps,
  Step,
};
