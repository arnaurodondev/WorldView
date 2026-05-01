/**
 * components/docs/mdx/Callout.tsx — info / warn / tip MDX block (T-B-2-05)
 *
 * WHY THIS EXISTS: Long-form documentation needs visual breaks for
 * "important" / "watch out" / "pro tip" content. The Callout component
 * gives MDX authors `<Callout type="warn">…</Callout>` and renders a
 * tinted box with an icon matching the semantic.
 *
 * WHY ONLY 3 TYPES (not 6+ like Notion): proven docs convention — Stripe,
 * Vercel, Tailwind all converge on info / warn / tip. More types invite
 * authoring inconsistency without aiding scannability.
 */

import type { ReactNode } from "react";
import { Info, AlertTriangle, Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalloutType = "info" | "warn" | "tip";

interface CalloutProps {
  type?: CalloutType;
  title?: string;
  children: ReactNode;
}

/**
 * Visual + semantic configuration per callout type.
 * Border color is the strongest signal; background is a low-alpha tint of
 * the same semantic token so the page hue stays harmonized.
 */
const VARIANTS: Record<
  CalloutType,
  { icon: typeof Info; border: string; bg: string; text: string }
> = {
  info: {
    icon: Info,
    border: "border-l-primary",
    bg: "bg-primary/5",
    text: "text-primary",
  },
  warn: {
    icon: AlertTriangle,
    border: "border-l-destructive",
    bg: "bg-destructive/5",
    text: "text-destructive",
  },
  tip: {
    icon: Lightbulb,
    border: "border-l-positive",
    bg: "bg-positive/5",
    text: "text-positive",
  },
};

export function Callout({ type = "info", title, children }: CalloutProps) {
  const variant = VARIANTS[type];
  const Icon = variant.icon;

  return (
    <div
      role="note"
      aria-label={`${type} callout`}
      className={cn(
        "my-5 flex gap-3 rounded-[2px] border border-border/40 border-l-2 p-4 text-sm",
        variant.border,
        variant.bg,
      )}
    >
      <Icon
        className={cn("mt-0.5 h-4 w-4 shrink-0", variant.text)}
        aria-hidden="true"
      />
      <div className="flex-1 leading-relaxed">
        {title ? (
          <p className={cn("mb-1 font-semibold", variant.text)}>{title}</p>
        ) : null}
        <div className="text-foreground [&>p:last-child]:mb-0 [&>p]:mb-2">
          {children}
        </div>
      </div>
    </div>
  );
}
