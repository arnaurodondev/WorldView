/**
 * components/ui/select.tsx — shadcn/ui Select (Radix UI)
 *
 * WHY THIS EXISTS: Native <select> dropdowns on macOS render in the OS light
 * mode stylesheet when the options list opens — white background, dark text —
 * regardless of Tailwind dark-mode classes applied to the trigger element.
 * This breaks the Terminal Dark aesthetic (--popover: 240 10% 4% = #09090B).
 *
 * Radix SelectPrimitive renders the dropdown in a React portal using our own
 * Tailwind classes (bg-popover, text-foreground, hover:bg-muted), so every
 * part of the control — trigger, value, content, items — fully respects our
 * design tokens in dark mode.
 *
 * "use client" — WHY: Radix Select manages open/close state and keyboard
 * navigation which require browser APIs (portal, focus management, scroll).
 *
 * USAGE:
 *   import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem }
 *     from "@/components/ui/select";
 *
 *   <Select value={value} onValueChange={setValue}>
 *     <SelectTrigger><SelectValue placeholder="Pick one" /></SelectTrigger>
 *     <SelectContent>
 *       <SelectItem value="a">Option A</SelectItem>
 *     </SelectContent>
 *   </Select>
 *
 * DESIGN TOKENS (Terminal Dark):
 *   --popover:    240 10%  4%  (#09090B) — dropdown background
 *   --muted:      240  4% 11%  (#18181B) — item hover background
 *   --foreground: 240  5% 90%  (#E4E4E7) — primary text
 *   --border:     240  4% 16%  (#27272A) — dropdown border
 */

"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Root ──────────────────────────────────────────────────────────────────────
// Re-export Radix root directly — it holds the open/value state.
const Select = SelectPrimitive.Root;

// ── Group ─────────────────────────────────────────────────────────────────────
// Optional grouping of items with a shared label (SelectLabel).
const SelectGroup = SelectPrimitive.Group;

// ── Value ─────────────────────────────────────────────────────────────────────
// Renders the currently selected value (or placeholder when empty) inside
// SelectTrigger. Radix updates this automatically when value changes.
const SelectValue = SelectPrimitive.Value;

// ── Trigger ───────────────────────────────────────────────────────────────────
/**
 * SelectTrigger — the visible button that opens the dropdown.
 *
 * WHY ChevronDown icon: matches Radix's own example and communicates
 * "expandable" to users, consistent with dropdown-menu.tsx.
 * ml-auto pushes the icon to the far right regardless of value text length.
 */
const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      // Base layout: flex row, vertically centred, full-width by default
      "flex h-[36px] w-full items-center justify-between rounded-[2px]",
      // Visual style: matches Input component (border-border, bg-muted)
      "border border-border bg-muted px-3 py-2 text-[14px]",
      // Text: foreground colour so selected value is readable
      "text-foreground",
      // Focus ring: Radix applies data-[state=open] so we use focus-visible
      "focus:outline-none focus:ring-1 focus:ring-ring",
      // PLAN-0059 W0 F-VISUAL-027: explicit tokens (was opacity-50, fails WCAG AA)
      "disabled:cursor-not-allowed disabled:text-[hsl(var(--disabled-foreground))]",
      // Placeholder text: muted so it's visually lighter than real values
      "[&>span[data-placeholder]]:text-muted-foreground",
      className,
    )}
    {...props}
  >
    {children}
    {/*
      WHY SelectPrimitive.Icon: Radix's Icon wrapper handles aria-hidden and
      positions correctly relative to the value text. The ChevronDown icon
      is standard for dropdowns. aria-hidden prevents screen readers from
      announcing "chevron down" after the selected value.
    */}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

// ── ScrollUpButton ────────────────────────────────────────────────────────────
/**
 * SelectScrollUpButton — appears at the top of SelectContent when the item list
 * is taller than the viewport and there are items above the visible area.
 * Radix manages visibility automatically.
 */
const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className,
    )}
    {...props}
  >
    <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

// ── ScrollDownButton ──────────────────────────────────────────────────────────
/**
 * SelectScrollDownButton — appears at the bottom of SelectContent when there
 * are more items below the visible area. Mirrors ScrollUpButton.
 */
const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className,
    )}
    {...props}
  >
    <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

// ── Content ───────────────────────────────────────────────────────────────────
/**
 * SelectContent — the dropdown panel that holds SelectItem elements.
 *
 * WHY Portal: Radix renders this outside the DOM tree of the trigger so it
 * sits above all other content (z-50) without clipping by overflow:hidden
 * parents. This is the same approach as DropdownMenuContent.
 *
 * WHY bg-popover + border-border: matches the GlobalSearch command palette
 * (command.tsx) so all floating panels share the same Terminal Dark panel
 * aesthetic (#09090B background, subtle border).
 *
 * WHY position="popper": positions the dropdown directly below the trigger
 * (like a native select), rather than Radix's default "item-aligned" mode
 * which aligns to the selected item's position inside the list.
 */
const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      // WHY sideOffset=4: 4px gap between trigger bottom and content top —
      // same as DropdownMenuContent for visual consistency across all dropdowns.
      sideOffset={4}
      className={cn(
        // Stacking + sizing
        "relative z-50 max-h-96 min-w-[8rem] overflow-hidden",
        // Visual: dark panel matching GlobalSearch command palette
        "rounded-[2px] border border-border bg-popover text-popover-foreground",
        // Radix open/close animations — same tokens as dropdown-menu.tsx
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        "data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2",
        "data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
        // popper mode: match trigger width exactly
        position === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className,
      )}
      {...props}
    >
      <SelectScrollUpButton />
      {/*
        WHY viewport with w-full + popper width class:
        SelectPrimitive.Viewport is the scrollable container. In popper mode
        we want it to fill the full trigger width. Radix exposes a CSS variable
        --radix-select-trigger-width for this purpose.
      */}
      <SelectPrimitive.Viewport
        className={cn(
          "p-1",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]",
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

// ── Label ─────────────────────────────────────────────────────────────────────
/**
 * SelectLabel — non-interactive header for a SelectGroup.
 * Uses the same muted text style as DropdownMenuLabel.
 */
const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-xs font-medium text-muted-foreground", className)}
    {...props}
  />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

// ── Item ──────────────────────────────────────────────────────────────────────
/**
 * SelectItem — a single selectable option inside SelectContent.
 *
 * WHY CheckIcon on the left: Radix's ItemIndicator renders only when this item
 * is the currently selected value. The check gives users visual confirmation
 * of the active selection without needing to compare text. pl-8 reserves space
 * for the indicator so unselected items align with selected ones.
 *
 * WHY focus:bg-muted: matches DropdownMenuItem hover style for a unified
 * dropdown feel across all interactive menus in the app.
 */
const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      // Layout: full-width row with space for the check indicator on the left
      "relative flex w-full cursor-default select-none items-center",
      "rounded-[2px] py-1.5 pl-8 pr-2 text-[14px] outline-none",
      // Interactive states
      "focus:bg-muted focus:text-foreground",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    {/* Check indicator — only visible when this item is selected */}
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" aria-hidden="true" />
      </SelectPrimitive.ItemIndicator>
    </span>
    {/* Item text */}
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

// ── Separator ─────────────────────────────────────────────────────────────────
/**
 * SelectSeparator — horizontal divider between groups of items.
 * Matches DropdownMenuSeparator styling.
 */
const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-border", className)}
    {...props}
  />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;

// ── Exports ───────────────────────────────────────────────────────────────────
export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
};
