/**
 * components/ui/accordion.tsx — shadcn/ui Accordion primitive
 *
 * WHY THIS EXISTS: Wave A FAQ section (T-A-1-11) requires an accessible
 * accordion. @radix-ui/react-accordion is in package.json but the shadcn
 * wrapper had not been generated yet. This file is the standard shadcn
 * wrapper, lightly themed to match the Terminal Dark token system
 * (rounded-[2px], border-border, primary chevron on hover).
 *
 * WHY radix: handles keyboard nav (Up/Down/Home/End), aria-expanded,
 * and animated panel collapse out of the box — non-trivial to hand-roll.
 */

"use client";

import * as React from "react";
import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

const Accordion = AccordionPrimitive.Root;

const AccordionItem = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Item>
>(({ className, ...props }, ref) => (
  <AccordionPrimitive.Item
    ref={ref}
    className={cn("border-b border-border/40", className)}
    {...props}
  />
));
AccordionItem.displayName = "AccordionItem";

const AccordionTrigger = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Header className="flex">
    <AccordionPrimitive.Trigger
      ref={ref}
      className={cn(
        // WHY py-4 + text-sm: comfortable vertical rhythm; chevron sized 14px
        // to match the muted text weight rather than competing with copy.
        "flex flex-1 items-center justify-between py-4 text-sm font-medium",
        "text-foreground transition-color-only duration-100 hover:text-primary",
        "[&[data-state=open]>svg]:rotate-180",
        className,
      )}
      {...props}
    >
      {children}
      <ChevronDown
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200"
        aria-hidden="true"
      />
    </AccordionPrimitive.Trigger>
  </AccordionPrimitive.Header>
));
AccordionTrigger.displayName = "AccordionTrigger";

const AccordionContent = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Content
    ref={ref}
    // WHY data-state animations: radix toggles data-state="open"/"closed";
    // Tailwind keyframe utilities defined in globals.css respond to those.
    className={cn(
      "overflow-hidden text-sm text-muted-foreground",
      "data-[state=closed]:animate-accordion-up",
      "data-[state=open]:animate-accordion-down",
    )}
    {...props}
  >
    <div className={cn("pb-4 pt-0 leading-relaxed", className)}>{children}</div>
  </AccordionPrimitive.Content>
));
AccordionContent.displayName = "AccordionContent";

export { Accordion, AccordionItem, AccordionTrigger, AccordionContent };
