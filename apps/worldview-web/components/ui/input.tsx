/**
 * components/ui/input.tsx — shadcn/ui Input with density variants
 *
 * WHY DENSITY VARIANTS: institutional terminal UIs are denser than consumer
 * SaaS. PRD-0031 §0.2 mandates 22px row heights. The `compact` density (h-7
 * px-2 text-[11px]) hits that target; `default` keeps the older shadcn shape
 * for legacy forms; `comfortable` is for marketing pages and long-form fields.
 *
 * Pre-existing call sites without `density` continue to render at the old
 * `default` height — no regressions. New components (NumberInput, screener
 * filters) opt into `compact` for institutional density.
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

export const inputVariants = cva(
  // Base — shared across all density variants.
  // WHY rounded-[2px]: matches the global 2px radius system (PRD-0031).
  // WHY disabled tokens (not opacity-50): PLAN-0059 W0 F-VISUAL-027 — opacity
  // halves contrast and fails WCAG AA on disabled inputs.
  "flex w-full rounded-[2px] border border-border bg-muted transition-colors " +
    "file:border-0 file:bg-transparent file:font-medium " +
    "placeholder:text-muted-foreground " +
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring " +
    "disabled:cursor-not-allowed disabled:text-[hsl(var(--disabled-foreground))] disabled:placeholder:text-[hsl(var(--disabled-foreground))]",
  {
    variants: {
      density: {
        compact: "h-7 px-2 py-0.5 text-[11px]",
        default: "h-[36px] px-3 py-1 text-sm",
        comfortable: "h-10 px-3 py-2 text-sm",
      },
    },
    defaultVariants: {
      // WHY default kept on `default`: protects all existing call sites that
      // don't pass density. Migration to `compact` happens opportunistically.
      density: "default",
    },
  },
);

export type InputDensity = NonNullable<VariantProps<typeof inputVariants>["density"]>;

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement>,
    VariantProps<typeof inputVariants> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, density, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(inputVariants({ density }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
