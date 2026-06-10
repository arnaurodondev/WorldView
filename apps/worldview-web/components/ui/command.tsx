/**
 * components/ui/command.tsx — shadcn/ui Command (cmdk) component
 *
 * WHY THIS EXISTS: Used by GlobalSearch for the instrument search dropdown.
 * cmdk provides keyboard-navigable command palettes — exactly what traders expect
 * from a Bloomberg-like search interface (type ticker → navigate with arrows → Enter).
 */

"use client";

import * as React from "react";
import { type DialogProps } from "@radix-ui/react-dialog";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive
    ref={ref}
    className={cn(
      "flex h-full w-full flex-col overflow-hidden rounded-[2px] bg-popover text-popover-foreground",
      className,
    )}
    {...props}
  />
));
Command.displayName = CommandPrimitive.displayName;

// WHY CommandDialog: Some designs use a full-screen dialog for search (like ⌘K palettes).
// GlobalSearch uses inline Command (not this); the global CommandPalette
// (components/shell/CommandPalette.tsx) is the canonical consumer of this variant.
// WHY interface extends DialogProps: we add a11y + styling knobs on top of the
// underlying Radix Dialog props (open / onOpenChange / etc. pass straight through).
interface CommandDialogProps extends DialogProps {
  /**
   * Accessible dialog name. Radix Dialog REQUIRES a DialogTitle — without one
   * screen readers announce an unnamed dialog and Radix logs a console error in
   * dev/tests. We render it sr-only because the palette's visual affordance is
   * the search input itself, not a heading (Linear/Raycast do the same).
   */
  title?: string;
  /** Accessible description announced after the title (also sr-only). */
  description?: string;
  /**
   * Extra classes for the DialogContent wrapper. The palette uses this to
   * widen beyond the default sm:max-w-lg and pin near the top of the viewport
   * (command palettes anchor high so the result list grows downward).
   */
  contentClassName?: string;
  /**
   * Extra classes for the inner <Command>. The default cmdk styling below is
   * comfortable/consumer-scale (h-12 input, py-3 items); terminal-density
   * consumers override with 11px/py-1 classes via this prop. tailwind-merge
   * resolves conflicts in favour of the caller (later class wins per group).
   */
  commandClassName?: string;
  /**
   * Forwarded to cmdk's <Command>. Pass `false` when the consumer does its own
   * filtering (e.g. CommandPalette: server-side instrument search + custom nav
   * ranking). Leaving cmdk's default fuzzy filter ON in that case would
   * re-filter already-filtered items against their internal `value` strings
   * (namespaced ids like "inst:<uuid>") and hide every result the moment the
   * user types — the same trap GlobalSearch avoids with shouldFilter={false}.
   */
  shouldFilter?: boolean;
}

function CommandDialog({
  children,
  title = "Command palette",
  description,
  contentClassName,
  commandClassName,
  shouldFilter,
  ...props
}: CommandDialogProps) {
  return (
    <Dialog {...props}>
      <DialogContent className={cn("overflow-hidden p-0", contentClassName)}>
        {/* sr-only title/description: required by Radix for accessible naming,
            visually redundant with the always-focused search input. */}
        <DialogTitle className="sr-only">{title}</DialogTitle>
        {description && <DialogDescription className="sr-only">{description}</DialogDescription>}
        <Command
          shouldFilter={shouldFilter}
          className={cn(
            "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5",
            commandClassName,
          )}
        >
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  );
}

const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="flex items-center border-b border-border px-3" cmdk-input-wrapper="">
    <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
    <CommandPrimitive.Input
      ref={ref}
      className={cn(
        "flex h-[36px] w-full rounded-[2px] bg-transparent py-3 text-[14px] outline-none",
        // PLAN-0059 W0 F-VISUAL-027: explicit tokens (was opacity-50)
        "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:text-[hsl(var(--disabled-foreground))]",
        className,
      )}
      {...props}
    />
  </div>
));
CommandInput.displayName = CommandPrimitive.Input.displayName;

const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List
    ref={ref}
    className={cn("max-h-[300px] overflow-y-auto overflow-x-hidden", className)}
    {...props}
  />
));
CommandList.displayName = CommandPrimitive.List.displayName;

const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
// WHY destructure className: spreading `props` after a static className causes the
// caller's className to *replace* (not merge) the base classes. Destructuring lets
// cn() merge both, so callers can override padding/font-size without losing text-center.
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Empty
    ref={ref}
    className={cn("py-6 text-center text-[14px] text-muted-foreground", className)}
    {...props}
  />
));
CommandEmpty.displayName = CommandPrimitive.Empty.displayName;

const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group
    ref={ref}
    className={cn(
      "overflow-hidden p-1 text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
      className,
    )}
    {...props}
  />
));
CommandGroup.displayName = CommandPrimitive.Group.displayName;

const CommandSeparator = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Separator ref={ref} className={cn("-mx-1 h-px bg-border", className)} {...props} />
));
CommandSeparator.displayName = CommandPrimitive.Separator.displayName;

const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-pointer select-none items-center rounded-[2px] px-2 py-1.5 text-[14px] outline-none",
      "aria-selected:bg-accent aria-selected:text-accent-foreground",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  />
));
CommandItem.displayName = CommandPrimitive.Item.displayName;

function CommandShortcut({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("ml-auto text-xs tracking-widest text-muted-foreground", className)}
      {...props}
    />
  );
}
CommandShortcut.displayName = "CommandShortcut";

export {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandSeparator,
  CommandShortcut,
};
