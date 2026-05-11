/**
 * components/ui/collapsible.tsx — shadcn/ui Collapsible (animated show/hide)
 *
 * WHY THIS EXISTS (PLAN-0053 Wave E T-E-5-02): the Overview tab's redesigned
 * right sidebar exposes Competitors and News zones that the analyst can collapse
 * to recover vertical space when they want to focus on Key Metrics. shadcn ships
 * a `collapsible` primitive that wraps `@radix-ui/react-collapsible` with the
 * standard Root / Trigger / Content names — using Radix directly would force
 * each call site to import three named exports from a vendor package, which
 * drifts from how every other UI primitive is consumed in this app.
 *
 * WHY just re-exports (no extra styling): unlike Sheet or Dialog, Collapsible
 * doesn't ship overlays or animation classes that need design-system tuning.
 * Each call site applies its own Tailwind to <CollapsibleContent>, so the
 * primitive stays minimal — fewer surface area = fewer chances of style drift.
 *
 * REFERENCE: https://ui.shadcn.com/docs/components/collapsible
 */

"use client";
// WHY "use client": Radix Collapsible uses React state internally and requires
// a browser context. SSR would render a static snapshot which contradicts the
// "open/close" interaction model.

import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";

// WHY direct re-export (not React.forwardRef wrapper): the underlying primitives
// already forward refs and accept className. A wrapper would add a layer for
// no functional gain. Match the pattern shadcn uses for Collapsible upstream.
const Collapsible = CollapsiblePrimitive.Root;
const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger;
const CollapsibleContent = CollapsiblePrimitive.CollapsibleContent;

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
