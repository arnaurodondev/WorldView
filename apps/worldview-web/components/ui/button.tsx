/**
 * components/ui/button.tsx — shadcn/ui Button component
 *
 * WHY THIS EXISTS: shadcn/ui Button is used throughout the app for all interactive
 * controls. Variants cover the main use cases:
 * - default: primary action (amber/gold background)
 * - destructive: dangerous actions (red background)
 * - outline: secondary actions
 * - ghost: nav items, icon buttons
 * - link: text links with button semantics
 *
 * This file is based on shadcn/ui's generated Button component, adapted for
 * the Bloomberg Dark palette. Do not edit the variant logic — use Tailwind
 * classes at the callsite instead.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §4 Components
 */

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Base styles: all buttons share these.
  // WHY rounded-[2px] not rounded-md: matches the new 2px radius system globally.
  // rounded-md was 6px (old radius) — now that --radius is 2px, using the explicit
  // value prevents any confusion from Tailwind's scale mapping.
  // PLAN-0059 W0 F-VISUAL-027: replaced disabled:opacity-50 with explicit disabled
  // tokens. opacity-50 yields ~3.5:1 contrast on text-foreground (FAILS WCAG AA).
  // Explicit tokens desaturate but stay readable at 5.5:1 (passes AA).
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[2px] text-[14px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background disabled:pointer-events-none disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // Primary CTA — trading yellow background (#FFD60A) with black text.
        // WHY shadow-primary/10 not /20: #FFD60A is more high-chroma than old #E8A317
        // amber. At /20 the yellow glow was visually aggressive on near-black. /10
        // keeps a subtle luminous edge that signals "primary action" without glowing.
        // Hover: /15 for a light deepening. No float effect — terminal buttons are flat.
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        // Destructive — muted red for delete/dangerous actions
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        // Outline — bordered, transparent background.
        // WHY text-muted-foreground + font-medium: outline buttons are secondary actions.
        // Muted text at rest creates clear visual hierarchy (primary > outline > ghost).
        // font-medium ensures the label remains legible against the transparent background.
        outline: "border border-border bg-transparent text-muted-foreground font-medium hover:bg-muted hover:text-foreground",
        // Secondary — elevated panel background
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        // Ghost — no background, for icon buttons and nav items
        ghost: "hover:bg-muted hover:text-foreground",
        // Link — text-only with underline semantics
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-[36px] px-4 py-2",
        // WHY rounded-[2px] on sm + lg: size variants used to override rounded-md (6px).
        // Now all sizes must explicitly use 2px to stay consistent with the radius system.
        sm: "h-8 rounded-[2px] px-3 text-xs",
        lg: "h-10 rounded-[2px] px-8",
        icon: "h-8 w-8",  // WHY h-8 w-8: compact icon buttons for dense toolbar layouts
      },
      // WHY density layered on top of size: existing call sites passed `size="sm"|"lg"`;
      // adding `density` lets new code opt into institutional 22px-row heights without
      // disturbing those defaults. When `density="compact"`, classes here override the
      // size-driven height/padding/text — that's why this comes AFTER size in the cva
      // compound class concatenation order (last-wins in Tailwind class merge).
      density: {
        compact: "h-7 px-3 text-[11px] [&_svg]:size-3",
        default: "",
        comfortable: "h-10 px-5 text-[14px]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
      density: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  // asChild: renders the button's styles onto a child element (e.g., <Link>)
  // WHY: allows correct HTML semantics (e.g., <a> tag) with button styles
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, density, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, density, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
