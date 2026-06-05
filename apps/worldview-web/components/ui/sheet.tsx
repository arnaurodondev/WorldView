/**
 * components/ui/sheet.tsx — shadcn/ui Sheet (side-anchored modal)
 *
 * WHY THIS EXISTS (PLAN-0048 Wave B-3): we need a right-anchored panel
 * (`<Sheet side="right">`) for AlertDetailSheet so users can drill into a
 * single alert without losing the AlertsList context. Built on the same
 * Radix Dialog primitive as `dialog.tsx` — Radix Dialog is the canonical
 * "modal that traps focus" primitive; a Sheet is just a Dialog whose
 * content slides in from a side rather than zooming from the centre.
 *
 * WHY a Tailwind `cva` for the side variants: shadcn's reference Sheet
 * exposes `top|right|bottom|left` so consumers can set `<SheetContent side="…">`
 * without sprinkling raw classes through the call sites. We only need
 * "right" today but keep all four for future reuse.
 */

"use client";

import * as React from "react";
import * as SheetPrimitive from "@radix-ui/react-dialog";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// WHY these primitive aliases: matches the shadcn naming convention
// (Sheet, SheetTrigger, SheetClose, SheetPortal) so the JSX in consumers
// reads like a proper component rather than `<DialogPrimitive.Root>` etc.
const Sheet = SheetPrimitive.Root;
const SheetTrigger = SheetPrimitive.Trigger;
const SheetClose = SheetPrimitive.Close;
const SheetPortal = SheetPrimitive.Portal;

const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Overlay
    // WHY bg-black/80: matches dialog.tsx so overlay treatment is uniform
    // across all modal-like surfaces in the app.
    className={cn(
      "fixed inset-0 z-50 bg-black/80",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className,
    )}
    {...props}
    ref={ref}
  />
));
SheetOverlay.displayName = SheetPrimitive.Overlay.displayName;

// `cva` (class-variance-authority): chosen here because we want a single
// component that accepts a `side` prop and applies the right slide-in animation
// for that side. Keeping the variants in one place means consumers can't drift
// into hand-rolled animation classes.
const sheetVariants = cva(
  cn(
    "fixed z-50 gap-4 bg-background p-3",
    "transition ease-in-out",
    "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:duration-300 data-[state=open]:duration-500",
  ),
  {
    variants: {
      side: {
        top: "inset-x-0 top-0 border-b border-border data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
        bottom:
          "inset-x-0 bottom-0 border-t border-border data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
        // WHY w-full sm:max-w-md: full width on mobile so trader can read the
        // payload comfortably on a small viewport; clamped to ~28rem on desktop
        // so the AlertsList behind remains visible — better situational context.
        left: "inset-y-0 left-0 h-full w-3/4 border-r border-border data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
        right:
          "inset-y-0 right-0 h-full w-3/4 border-l border-border data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-md",
      },
    },
    defaultVariants: {
      side: "right",
    },
  },
);

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof SheetPrimitive.Content>,
    VariantProps<typeof sheetVariants> {}

const SheetContent = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Content>,
  SheetContentProps
>(({ side = "right", className, children, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <SheetPrimitive.Content
      ref={ref}
      className={cn(sheetVariants({ side }), className)}
      {...props}
    >
      {children}
      {/* WHY explicit Close: Radix doesn't ship a default close affordance —
          users would have to ESC out, which is undiscoverable. The X icon is
          the universal "dismiss" affordance. */}
      <SheetPrimitive.Close className="absolute right-4 top-4 rounded-[2px] opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </SheetPrimitive.Close>
    </SheetPrimitive.Content>
  </SheetPortal>
));
SheetContent.displayName = SheetPrimitive.Content.displayName;

function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 text-left", className)} {...props} />;
}
SheetHeader.displayName = "SheetHeader";

function SheetFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("mt-auto flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}
SheetFooter.displayName = "SheetFooter";

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Title>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Title
    ref={ref}
    // WHY text-[13px] uppercase tracking-[0.04em] (was text-base tracking-tight):
    // Bloomberg terminal panel/drawer titles use 13px ALL-CAPS — "text-base" (16px)
    // is consumer-app scale and "tracking-tight" conflicts with the uppercase
    // terminal aesthetic. 13px uppercase matches the instrument header ticker style.
    className={cn("text-[13px] font-semibold uppercase tracking-[0.04em] text-foreground", className)}
    {...props}
  />
));
SheetTitle.displayName = SheetPrimitive.Title.displayName;

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Description>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Description
    ref={ref}
    // WHY text-[10px] (was text-xs=12px): sheet description is secondary metadata —
    // 12px is too large for terminal density; 10px matches the Bloomberg caption standard
    // for supplementary text beneath panel/drawer titles.
    className={cn("text-[10px] text-muted-foreground", className)}
    {...props}
  />
));
SheetDescription.displayName = SheetPrimitive.Description.displayName;

export {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetPortal,
  SheetTitle,
  SheetTrigger,
};
