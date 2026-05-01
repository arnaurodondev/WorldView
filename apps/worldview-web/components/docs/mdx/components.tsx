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

/**
 * slugify — turn heading text into an HTML id slug. Mirrors the same
 * logic used by lib/docs.ts:extractHeadings so TOC anchors and rendered
 * heading IDs always agree.
 */
function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-");
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
  // h1 is reserved for the page title rendered outside of MDX, so we treat
  // any h1 in MDX as an h2 to preserve hierarchy. Real authors should not
  // use h1 in MDX content — we accept it gracefully.
  h1: ({ children }: { children?: ReactNode }) => (
    <h2 id={slugify(textOf(children))} className="mt-10 mb-3 text-2xl font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h2>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 id={slugify(textOf(children))} className="mt-10 mb-3 text-2xl font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 id={slugify(textOf(children))} className="mt-7 mb-2 text-lg font-semibold tracking-tight text-foreground scroll-mt-24">
      {children}
    </h3>
  ),
  h4: ({ children }: { children?: ReactNode }) => (
    <h4 id={slugify(textOf(children))} className="mt-5 mb-2 text-base font-semibold text-foreground scroll-mt-24">
      {children}
    </h4>
  ),

  // ── Body text ────────────────────────────────────────────────────────
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-3 text-sm leading-relaxed text-muted-foreground">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-3 list-disc space-y-1 pl-5 text-sm text-muted-foreground marker:text-primary/60">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-3 list-decimal space-y-1 pl-5 text-sm text-muted-foreground marker:text-primary/60">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="leading-relaxed">{children}</li>,
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
    <code className="rounded-[2px] bg-muted/60 px-1 py-0.5 font-mono text-[12px] text-foreground">
      {children}
    </code>
  ),
  a: ({ href, children }: { href?: string; children?: ReactNode }) => {
    // Internal links use next/link for prefetching; external open in new tab.
    if (href?.startsWith("/")) {
      return (
        <Link href={href} className="text-primary underline-offset-2 hover:underline">
          {children}
        </Link>
      );
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline-offset-2 hover:underline"
      >
        {children}
      </a>
    );
  },

  // ── Tables ───────────────────────────────────────────────────────────
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-5 overflow-x-auto rounded-[2px] border border-border/40">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border-b border-border/40 bg-muted/40 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="border-b border-border/20 px-3 py-2 text-sm text-foreground">{children}</td>
  ),

  // ── Custom components ────────────────────────────────────────────────
  Callout,
  CodeBlock,
  DocsTabs,
  DocsTab,
  Steps,
  Step,
};
