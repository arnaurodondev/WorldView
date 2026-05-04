"use client";
// WHY "use client": next/dynamic must be called in a Client Component.
// This file is the dedicated dynamic-import boundary for MarkdownContent
// so that MessageBubble.tsx can remain a Server Component (verified by
// server-component-audit.test.ts which asserts MessageBubble has no "use client").

/**
 * features/chat/components/LazyMarkdownContent.tsx — Lazy-loaded markdown wrapper
 *
 * WHY THIS EXISTS: PLAN-0059-G Wave G-2 requires lazy-loading react-markdown +
 * remark-gfm (~50KB) so the chat page does not parse that JS bundle on first
 * paint. next/dynamic must be called inside a "use client" component;
 * MessageBubble.tsx is a Server Component and cannot call it directly.
 *
 * This file is a thin wrapper that:
 *   1. Declares "use client" so next/dynamic works.
 *   2. Re-exports a component with the same props as MarkdownContent.
 *   3. Is imported by MessageBubble (Server Component) as the render target
 *      for assistant and streaming message text.
 *
 * WHY ssr:false: MarkdownContent has "use client" + navigator.clipboard for
 * the copy button. SSR would produce a hydration mismatch on copy-button state.
 *
 * WHY null loading fallback: chat messages appear only after the user sends a
 * query; the network round-trip to S9 (>=200ms) gives the ~50KB bundle enough
 * time to load. The blank-then-populated transition is imperceptible to users.
 *
 * WHO USES IT: MessageBubble.tsx (assistant + streaming message content)
 * DATA SOURCE: N/A — renders content passed as children prop.
 * DESIGN REFERENCE: PLAN-0059-G Wave G-2 — dynamic imports for bundle reduction.
 */

import type { ComponentType } from "react";
import dynamic from "next/dynamic";
import type { MarkdownContentProps } from "@/components/ui/markdown-content";

// WHY re-export the type: consumers of LazyMarkdownContent (MessageBubble) pass
// props typed as MarkdownContentProps. Importing the type here keeps the prop
// contract in sync with the underlying MarkdownContent component automatically —
// if MarkdownContentProps changes, TypeScript will catch the mismatch here.
export type { MarkdownContentProps };

/**
 * LazyMarkdownContent — next/dynamic wrapper around MarkdownContent.
 *
 * Drop-in replacement for <MarkdownContent> that defers the react-markdown
 * bundle load until first render. Props are identical to MarkdownContentProps.
 */
export const LazyMarkdownContent: ComponentType<MarkdownContentProps> = dynamic(
  // WHY .then(m => ({ default: m.MarkdownContent })): MarkdownContent is a
  // NAMED export (not a default export) in markdown-content.tsx. next/dynamic
  // expects a module with a `default` export, so we wrap the named export.
  () =>
    import("@/components/ui/markdown-content").then((m) => ({ default: m.MarkdownContent })),
  {
    ssr: false, // navigator.clipboard (copy button) is browser-only
    loading: () => null, // ~50KB loads in <100ms; blank->populated is imperceptible
  },
) as ComponentType<MarkdownContentProps>;
// WHY the `as` cast: next/dynamic infers ComponentType<{}> when the loader is
// typed generically. The cast restores the correct MarkdownContentProps type so
// callers get full prop checking and auto-complete. The runtime shape is correct
// because the dynamic import resolves to the real MarkdownContent component.
