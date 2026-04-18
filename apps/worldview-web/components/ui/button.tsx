/**
 * components/ui/button.tsx — shadcn/ui Button component
 *
 * WHY THIS EXISTS: shadcn/ui Button is used throughout the app for all interactive
 * controls. Variants cover the main use cases:
 * - default: primary action (sky blue background)
 * - destructive: dangerous actions (red background)
 * - outline: secondary actions
 * - ghost: nav items, icon buttons
 * - link: text links with button semantics
 *
 * This file is based on shadcn/ui's generated Button component, adapted for
 * the Midnight Pro palette. Do not edit the variant logic — use Tailwind
 * classes at the callsite instead.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §4 Components
 */

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Base styles: all buttons share these
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // Primary CTA — sky-500 background matches Midnight Pro accent
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        // Destructive — muted red for delete/dangerous actions
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        // Outline — bordered, transparent background
        outline: "border border-border bg-transparent hover:bg-muted hover:text-foreground",
        // Secondary — elevated panel background
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        // Ghost — no background, for icon buttons and nav items
        ghost: "hover:bg-muted hover:text-foreground",
        // Link — text-only with underline semantics
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-8 w-8",  // WHY h-8 w-8: compact icon buttons for dense toolbar layouts
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
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
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
