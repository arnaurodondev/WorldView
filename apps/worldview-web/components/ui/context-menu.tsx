/**
 * components/ui/context-menu.tsx — shadcn/ui-style ContextMenu primitive + ActionContextMenu
 *
 * WHY THIS EXISTS: Right-click context menus are an institutional-terminal staple.
 * Bloomberg, FactSet, and TradingView all expose row-level actions ("Add to
 * watchlist", "Open in window", "Copy as TSV") via right-click. shadcn's
 * generated component template is a thin styled wrapper over @radix-ui/react-context-menu.
 *
 * TWO EXPORTS:
 *   1. Raw shadcn primitives (ContextMenu, ContextMenuTrigger, etc.) — for one-off
 *      custom menus that don't use the action registry.
 *   2. ActionContextMenu — registry-driven wrapper that reads from useContextMenuActions()
 *      and renders grouped, mnemonic-underlined items automatically. This is the
 *      component to use for all table rows (holdings, screener, watchlist).
 *
 * USED BY: SemanticHoldingsTable rows (right-click), ScreenerTable rows, watchlist rows.
 *
 * KEYBOARD:
 *   - Radix handles Esc, ↑↓ navigation, Enter activate.
 *   - ActionContextMenu adds mnemonic key handling: pressing a single letter
 *     (e.g., "W" for "Add to Watchlist") triggers the corresponding action while
 *     the menu is open, matching Bloomberg DES/GP/CN single-key conventions.
 *
 * a11y: roles wired by Radix; we only style.
 *
 * PLAN-0059 F-3: ActionContextMenu is the deliverable for this wave.
 */

"use client";
// WHY "use client": uses useRouter (Next.js navigation) and useContextMenuActions
// (which calls usePathname()). Both are browser-only APIs unavailable in Server Components.

import * as React from "react";
import * as ContextMenuPrimitive from "@radix-ui/react-context-menu";
import { Check, ChevronRight, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useContextMenuActions } from "@/hooks/useContextMenuActions";
import { extractMnemonicParts, type ActionContext, type RowContextKind } from "@/lib/command-actions";

const ContextMenu = ContextMenuPrimitive.Root;
const ContextMenuTrigger = ContextMenuPrimitive.Trigger;
const ContextMenuGroup = ContextMenuPrimitive.Group;
const ContextMenuPortal = ContextMenuPrimitive.Portal;
const ContextMenuSub = ContextMenuPrimitive.Sub;
const ContextMenuRadioGroup = ContextMenuPrimitive.RadioGroup;

const ContextMenuSubTrigger = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.SubTrigger>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubTrigger> & { inset?: boolean }
>(({ className, inset, children, ...props }, ref) => (
  <ContextMenuPrimitive.SubTrigger
    ref={ref}
    className={cn(
      "flex cursor-default select-none items-center rounded-[2px] px-2 py-1 text-[11px] outline-none focus:bg-accent focus:text-accent-foreground data-[state=open]:bg-accent data-[state=open]:text-accent-foreground",
      inset && "pl-6",
      className,
    )}
    {...props}
  >
    {children}
    <ChevronRight className="ml-auto h-3 w-3" />
  </ContextMenuPrimitive.SubTrigger>
));
ContextMenuSubTrigger.displayName = ContextMenuPrimitive.SubTrigger.displayName;

const ContextMenuSubContent = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.SubContent>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubContent>
>(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.SubContent
    ref={ref}
    className={cn(
      "z-50 min-w-[8rem] overflow-hidden rounded-[2px] border border-border bg-popover p-0.5 text-popover-foreground  " +
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 " +
        "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
      className,
    )}
    {...props}
  />
));
ContextMenuSubContent.displayName = ContextMenuPrimitive.SubContent.displayName;

const ContextMenuContent = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Content>
>(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.Portal>
    <ContextMenuPrimitive.Content
      ref={ref}
      // WHY z-50: lifts above the dialog/sheet stack (z-40).
      className={cn(
        "z-50 min-w-[10rem] overflow-hidden rounded-[2px] border border-border bg-popover p-0.5 text-popover-foreground  " +
          "font-mono " + // institutional terminal look
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 " +
          "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        className,
      )}
      {...props}
    />
  </ContextMenuPrimitive.Portal>
));
ContextMenuContent.displayName = ContextMenuPrimitive.Content.displayName;

const ContextMenuItem = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Item> & { inset?: boolean; destructive?: boolean }
>(({ className, inset, destructive, ...props }, ref) => (
  <ContextMenuPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center gap-2 rounded-[2px] px-2 py-1 text-[11px] outline-none transition-colors " +
        "focus:bg-accent focus:text-accent-foreground " +
        // PLAN-0059 W0 F-VISUAL-027: explicit disabled tokens, not opacity-50.
        "data-[disabled]:pointer-events-none data-[disabled]:text-[hsl(var(--disabled-foreground))]",
      destructive && "text-destructive focus:bg-destructive/10 focus:text-destructive",
      inset && "pl-6",
      className,
    )}
    {...props}
  />
));
ContextMenuItem.displayName = ContextMenuPrimitive.Item.displayName;

const ContextMenuCheckboxItem = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.CheckboxItem>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
  <ContextMenuPrimitive.CheckboxItem
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center rounded-[2px] py-1 pl-6 pr-2 text-[11px] outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:text-[hsl(var(--disabled-foreground))]",
      className,
    )}
    checked={checked}
    {...props}
  >
    <span className="absolute left-1 flex h-3 w-3 items-center justify-center">
      <ContextMenuPrimitive.ItemIndicator>
        <Check className="h-3 w-3" />
      </ContextMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </ContextMenuPrimitive.CheckboxItem>
));
ContextMenuCheckboxItem.displayName = ContextMenuPrimitive.CheckboxItem.displayName;

const ContextMenuRadioItem = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <ContextMenuPrimitive.RadioItem
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center rounded-[2px] py-1 pl-6 pr-2 text-[11px] outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:text-[hsl(var(--disabled-foreground))]",
      className,
    )}
    {...props}
  >
    <span className="absolute left-1 flex h-3 w-3 items-center justify-center">
      <ContextMenuPrimitive.ItemIndicator>
        <Circle className="h-2 w-2 fill-current" />
      </ContextMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </ContextMenuPrimitive.RadioItem>
));
ContextMenuRadioItem.displayName = ContextMenuPrimitive.RadioItem.displayName;

const ContextMenuLabel = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Label> & { inset?: boolean }
>(({ className, inset, ...props }, ref) => (
  <ContextMenuPrimitive.Label
    ref={ref}
    className={cn(
      "px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
      inset && "pl-6",
      className,
    )}
    {...props}
  />
));
ContextMenuLabel.displayName = ContextMenuPrimitive.Label.displayName;

const ContextMenuSeparator = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.Separator
    ref={ref}
    className={cn("my-0.5 h-px bg-border", className)}
    {...props}
  />
));
ContextMenuSeparator.displayName = ContextMenuPrimitive.Separator.displayName;

const ContextMenuShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
  <span
    className={cn(
      "ml-auto text-[10px] tracking-widest text-muted-foreground tabular-nums",
      className,
    )}
    {...props}
  />
);
ContextMenuShortcut.displayName = "ContextMenuShortcut";

export {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuCheckboxItem,
  ContextMenuRadioItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuGroup,
  ContextMenuPortal,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuRadioGroup,
};

// ── ActionContextMenu ─────────────────────────────────────────────────────────
//
// This is the high-level component for F-3. It wraps the raw shadcn primitives
// above with the action registry so callers only provide children + scope.
//
// USAGE:
//   <ActionContextMenu row={holdingRow}>
//     <tr>...</tr>
//   </ActionContextMenu>
//
// WHY wrap (not replace): the raw primitives remain available for one-off menus
// (e.g., chart-specific context menu with tool-specific actions). ActionContextMenu
// is for the common case of registry-driven rows.

/**
 * MnemonicLabel — renders a menu item label with the Bloomberg-style underlined
 * single-character mnemonic.
 *
 * WHY underline (not bold): Bloomberg uses underline specifically because it
 * matches the HTML <u> convention for keyboard shortcuts (e.g., browser
 * native menus underline the mnemonic on Windows). Bold would look like
 * emphasis, not a keyboard shortcut.
 *
 * Example: "Copy Ticker" with mnemonic "C" renders as:
 *   <u>C</u>opy Ticker
 */
function MnemonicLabel({ label, mnemonic }: { label: string; mnemonic?: string }) {
  const parts = extractMnemonicParts(label, mnemonic);
  if (!parts) {
    // No mnemonic or mnemonic not found in label — render plain text.
    return <>{label}</>;
  }
  const [before, letter, after] = parts;
  return (
    <>
      {before}
      {/* WHY font-medium on the underlined character: Bloomberg menus show the
          mnemonic character slightly bolder than the surrounding text, which improves
          scannability when the menu has many items. */}
      <span className="underline decoration-muted-foreground font-medium">{letter}</span>
      {after}
    </>
  );
}

/**
 * ActionContextMenu — registry-driven right-click context menu.
 *
 * Props:
 *   children   — the element that triggers the menu on right-click (any ReactNode)
 *   row        — optional row context for "row"-scoped actions. When provided, row
 *                actions (Copy Ticker, Add to Watchlist, etc.) appear in the menu.
 *
 * WHY no explicit "scope" prop: the scope is derived from (1) the current pathname
 * (via usePathname inside useContextMenuActions) and (2) whether `row` is provided.
 * The caller doesn't need to specify scope manually — pass `row` for row menus.
 */
export interface ActionContextMenuProps {
  /** The element to right-click on. Usually a <tr> or <div> wrapping a data row. */
  children: React.ReactNode;
  /**
   * Optional row context. When provided, row-scoped actions appear in the menu.
   * Pass the full row data (ticker, entityId, etc.) so actions like "Copy Ticker"
   * have the data they need without an extra API call at action time.
   */
  row?: RowContextKind;
  /** Additional class on the trigger wrapper. */
  className?: string;
}

export function ActionContextMenu({ children, row, className }: ActionContextMenuProps) {
  const router = useRouter();
  const { groups, mnemonicMap } = useContextMenuActions(row);

  /**
   * ActionContext provided to every action's `run()` call.
   *
   * WHY build this inside the component (not at registry time):
   * Actions need `navigate` and `toast` which are hooks/APIs only available
   * at render time. The registry stores pure action descriptors; context-dependent
   * utilities are injected here when the action is triggered.
   */
  const actionCtx: ActionContext = React.useMemo(
    () => ({
      row,
      navigate: (path: string) => router.push(path),
      toast: (message: string, opts?: { description?: string }) => {
        toast(message, opts);
      },
    }),
    // WHY stable deps: router and toast are stable references; row identity is
    // the only thing that can change. Memo avoids re-creating context on every render.
    [row, router],
  );

  /**
   * handleMnemonicKeyDown — intercept single-letter keypresses while the menu is
   * open. Radix ContextMenu does NOT natively support mnemonic shortcuts (it only
   * does type-ahead search, which matches by prefix not first-character). We add
   * them explicitly via onKeyDown on the Content.
   *
   * WHY check mnemonicMap (not raw key): the map only contains keys that correspond
   * to registered actions in the current scope, so non-mnemonic keys (arrows, Esc,
   * Enter) fall through to Radix's native handling.
   */
  function handleMnemonicKeyDown(e: React.KeyboardEvent) {
    const action = mnemonicMap.get(e.key.toLowerCase());
    if (!action) return;
    // Prevent Radix from treating this as a type-ahead character (which would
    // also match items by first character, causing double-trigger).
    e.preventDefault();
    void action.run(actionCtx);
  }

  // If no actions are available for this scope, render children without a menu
  // wrapper. This avoids an invisible right-click surface that does nothing.
  if (groups.length === 0) {
    return <>{children}</>;
  }

  return (
    <ContextMenu>
      {/* WHY asChild: the trigger must be the actual <tr>/<div> — not a wrapper
          div around it — so the right-click hit area exactly matches the row.
          asChild forwards the ContextMenuPrimitive.Trigger behaviour onto
          children without adding an extra DOM element. */}
      {/* WHY children directly (no Fragment wrapper): Radix asChild uses
          SlotClone which merges Trigger props onto the single ReactElement
          child. A Fragment wrapper swallows the merged props — onContextMenu
          never reaches the DOM node, so right-click does nothing. The child
          must be a single element (SemanticHoldingsTable guarantees <tr>). */}
      <ContextMenuPrimitive.Trigger asChild className={className}>
        {children}
      </ContextMenuPrimitive.Trigger>

      <ContextMenuContent onKeyDown={handleMnemonicKeyDown}>
        {groups.map((group, groupIdx) => (
          <React.Fragment key={group.category}>
            {/* Category section separator — skip before the first group */}
            {groupIdx > 0 && <ContextMenuSeparator />}

            {/* Category label — matches Bloomberg's section headers (NAVIGATE, COPY, etc.) */}
            <ContextMenuLabel>{group.category}</ContextMenuLabel>

            {group.actions.map((action) => {
              // WHY compute enabled at render: enabled() may depend on current
              // row state (e.g., "Sell" is only enabled when qty > 0). We
              // re-evaluate on each render so the enabled state is always fresh.
              const isEnabled = action.enabled ? action.enabled(actionCtx) : true;

              return (
                <ContextMenuItem
                  key={action.id}
                  disabled={!isEnabled}
                  onSelect={() => {
                    // onSelect fires when the user clicks OR presses Enter on an item.
                    // WHY void the Promise: onSelect must return void (Radix constraint);
                    // errors from async actions are swallowed here but the action can
                    // show a toast on error internally.
                    void action.run(actionCtx);
                  }}
                >
                  {/* Mnemonic-underlined label */}
                  <span className="flex-1">
                    <MnemonicLabel label={action.label} mnemonic={action.mnemonic} />
                  </span>

                  {/* Bloomberg-style mnemonic shortcut hint (right-aligned) */}
                  {action.mnemonic && (
                    <ContextMenuShortcut>{action.mnemonic.toUpperCase()}</ContextMenuShortcut>
                  )}
                </ContextMenuItem>
              );
            })}
          </React.Fragment>
        ))}
      </ContextMenuContent>
    </ContextMenu>
  );
}
