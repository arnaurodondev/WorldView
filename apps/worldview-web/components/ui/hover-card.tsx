"use client"

/**
 * hover-card.tsx — Wave K Bloomberg-terminal customization of the
 * stock shadcn HoverCard primitive.
 *
 * WHY this differs from upstream shadcn: the default ships with
 * `rounded-md` + `shadow-md`, both of which violate the
 * `no-off-palette-colors` architecture test (flat terminal palette has
 * zero corners and zero elevations). We strip the radius (rounded-none)
 * and drop the shadow entirely, replacing the elevation cue with a
 * 1px border for definition. Padding is tightened from p-4 to p-3 to
 * match the dense Bloomberg-grade rail rhythm. (QA BL-03b.)
 */

import * as React from "react"
import * as HoverCardPrimitive from "@radix-ui/react-hover-card"

import { cn } from "@/lib/utils"

const HoverCard = HoverCardPrimitive.Root

const HoverCardTrigger = HoverCardPrimitive.Trigger

const HoverCardContent = React.forwardRef<
  React.ElementRef<typeof HoverCardPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof HoverCardPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <HoverCardPrimitive.Content
    ref={ref}
    align={align}
    sideOffset={sideOffset}
    className={cn(
      // WHY rounded-none + no shadow: flat terminal palette (see file
      // header). WHY border border-border: replaces the dropped shadow
      // as the elevation cue. WHY p-3: tighter rhythm than shadcn p-4.
      "z-50 w-64 rounded-none border border-border bg-popover p-3 text-popover-foreground outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-[--radix-hover-card-content-transform-origin]",
      className
    )}
    {...props}
  />
))
HoverCardContent.displayName = HoverCardPrimitive.Content.displayName

export { HoverCard, HoverCardTrigger, HoverCardContent }
