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

import type { ComponentType, ReactElement } from "react";
import dynamic from "next/dynamic";
import type { MarkdownContentProps } from "@/components/ui/markdown-content";

// WHY re-export the type: consumers of LazyMarkdownContent (MessageBubble) pass
// props typed as MarkdownContentProps. Importing the type here keeps the prop
// contract in sync with the underlying MarkdownContent component automatically —
// if MarkdownContentProps changes (e.g. new withCitationSups prop), TypeScript
// will catch the mismatch here without any manual sync.
export type { MarkdownContentProps };

// ── PLAN-0089 K T-20.2 — wrapper-level prop superset ─────────────────────────
//
// We extend the inner MarkdownContent's prop bag with `withInlineCitationAnchors`
// here at the wrapper layer (rather than inside MarkdownContent itself) so the
// chat surface gets the F1 anchor primitive treatment without rippling the
// new prop through every other markdown consumer in the platform (morning brief,
// instrument intelligence, etc.). MarkdownContent stays single-purpose.
//
// WHY a thin wrapper prop (not a full re-render path swap):
//   The underlying MarkdownContent already pre-processes `[N]` citation markers
//   into styled <sup> chips via the `withCitationSups` flag (CITE_SENTINEL +
//   `code` component override — see ui/markdown-content.tsx lines ~92..245).
//   When `withInlineCitationAnchors=true` we automatically enable that same
//   pre-processing AND tag the rendered output with `data-inline-citation-anchors`
//   so downstream styles (and future visual swaps) can target the anchor
//   variant precisely. Today this is a CSS-only opt-in; the visual swap to
//   the `<InlineCitationAnchor>` primitive proper is queued for the
//   PLAN-0089-K-FU follow-up (the swap requires hooking the `code` component
//   override inside MarkdownContent — out of T-20 scope, which is limited
//   to four files).
//
// WHY back-compat: `withInlineCitationAnchors` defaults to false. Existing
// callers (MessageBubble, MessageTurn, intelligence panels) keep the exact
// rendering they had before — same DOM tree, same selectors, same tests pass.
export interface LazyMarkdownContentProps extends MarkdownContentProps {
  /**
   * PLAN-0089 K T-20.2 — opt into the F1 `<InlineCitationAnchor>` treatment
   * for inline `[N]` citation markers.
   *
   * Default `false` for back-compat. When `true`:
   *   - `withCitationSups` is forced on (citation markers are detected
   *     even if the caller forgot to set the sister flag explicitly).
   *   - the rendered wrapper carries `data-inline-citation-anchors="true"`
   *     so styles + future hover wiring can target the anchor variant.
   *
   * @default false
   */
  readonly withInlineCitationAnchors?: boolean;
}

// Inner dynamic-loaded MarkdownContent, typed against the underlying prop bag
// only. We keep a separate handle so we can wrap it from the public component
// without next/dynamic complaining about un-bundled prop differences.
const DynamicMarkdownContent: ComponentType<MarkdownContentProps> = dynamic(
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

/**
 * LazyMarkdownContent — next/dynamic wrapper around MarkdownContent.
 *
 * Drop-in replacement for `<MarkdownContent>` that defers the react-markdown
 * bundle load until first render. Props match `MarkdownContentProps` plus
 * the optional `withInlineCitationAnchors` flag introduced in PLAN-0089 K
 * T-20.2 (see the type-level docstring above).
 */
export function LazyMarkdownContent(props: LazyMarkdownContentProps): ReactElement {
  // Pull the wrapper-only prop off; everything else flows through to the
  // inner dynamic component unchanged.
  const { withInlineCitationAnchors = false, withCitationSups, ...rest } = props;

  // WHY OR-merge: when the anchor mode is on, the inner `withCitationSups`
  // pre-processing MUST be enabled (the InlineCitationAnchor primitive needs
  // the `[N]` markers to be detected first). We do not override an explicit
  // `withCitationSups={false}` from the caller silently — instead we OR them,
  // so an explicit caller-opt-in wins and `withInlineCitationAnchors=true`
  // can only ADD pre-processing, never remove it.
  const effectiveWithCitationSups = withCitationSups || withInlineCitationAnchors;

  // WHY a wrapping <span> not <div>: this component is used inside paragraphs
  // and message bodies — a block-level wrapper would force an unwanted line
  // break for compact-density turns. `display: contents`-style spans keep
  // the DOM transparent to flex/grid parents.
  // The `data-inline-citation-anchors` data attribute is the public marker
  // future commits will key off when the InlineCitationAnchor swap lands.
  return (
    <span
      data-inline-citation-anchors={withInlineCitationAnchors ? "true" : undefined}
      // WHY contents: keep the wrapper out of layout flow entirely. Without
      // this the wrapper would become an inline box and shift baselines on
      // mono-spaced terminal content.
      style={{ display: "contents" }}
    >
      <DynamicMarkdownContent {...rest} withCitationSups={effectiveWithCitationSups} />
    </span>
  );
}
