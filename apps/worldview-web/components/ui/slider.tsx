"use client"

/**
 * components/ui/slider.tsx — shadcn/ui Slider component (Radix primitive)
 *
 * WHY THIS EXISTS: The EntityGraph filter controls (PLAN-0059 Wave H-4) need a
 * compact slider for the edge-strength threshold (0–100%). Radix's Slider
 * primitive gives keyboard-accessible, ARIA-compliant range input with no extra
 * dependencies — it's already in package.json as @radix-ui/react-slider.
 *
 * DESIGN: Midnight Pro palette — track is bg-input (dark), range fill is
 * bg-primary (#FFD60A Bloomberg yellow), thumb matches the primary ring.
 * Sizing follows the finance terminal density (h-1.5 track, compact thumb).
 */

import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"

import { cn } from "@/lib/utils"

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn(
      // WHY relative + flex + items-center: Radix Slider root needs to be a flex
      // container so the Track and Thumb children lay out correctly on the axis.
      // w-full allows the parent to control width; touch-none prevents scroll
      // interference on mobile when dragging the thumb.
      "relative flex w-full touch-none select-none items-center",
      className
    )}
    {...props}
  >
    <SliderPrimitive.Track
      className={cn(
        // WHY h-1.5: thin track (1.5 = 6px) matches finance terminal density —
        // heavy tracks look wrong next to 10px-font labels. bg-input is the
        // dark grey defined in global.css, providing low-contrast track background.
        "relative h-1.5 w-full grow overflow-hidden rounded-full bg-input"
      )}
    >
      <SliderPrimitive.Range
        className={cn(
          // WHY bg-primary: the filled range uses Bloomberg yellow so the current
          // threshold value is immediately visible at a glance (same treatment as
          // active tabs and selected pills in this UI).
          "absolute h-full bg-primary"
        )}
      />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb
      className={cn(
        // WHY block h-3.5 w-3.5: compact 14px thumb — large enough to grab on
        // touch, small enough not to dominate the filter row visually.
        // ring-offset-background + focus-visible ring matches other interactive
        // elements in the design system (buttons, inputs).
        // WHY disabled:bg-[hsl(var(--disabled-bg))] etc. (not disabled:opacity-50):
        // PLAN-0059 W0 F-002 — blanket opacity-50 yields ~3.5:1 contrast on dark theme
        // (fails WCAG AA). Explicit disabled tokens desaturate while maintaining ≥4.5:1.
        "block h-3.5 w-3.5 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:bg-[hsl(var(--disabled-bg))] disabled:border-[hsl(var(--disabled-border))]"
      )}
    />
  </SliderPrimitive.Root>
))
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
