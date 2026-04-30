/**
 * components/shell/HotkeyCheatSheet.tsx — `?` overlay enumerating registered chords.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 closes F-LAYOUT-001 (StatusBar dead-shortcut
 * fraud). The cheat sheet displays exactly what is registered — auto-derived
 * from the registry. It is structurally impossible to advertise an unwired
 * chord because the rendered list IS the binding list.
 *
 * USAGE: rendered once at the layout root. The `?` chord (registered by
 * GlobalHotkeyBindings) calls a global toggle function exposed via React
 * context — keeping open/close state in this component.
 *
 * WHY native <dialog>: gives accessible focus-trap, Esc-to-close, and inert
 * backdrop semantics for free. Radix Dialog also works but we don't need its
 * portaling/animation here; the cheat sheet is a single short-lived overlay.
 *
 * KEYBOARD:
 *   - Open:  `?` (registered by GlobalHotkeyBindings)
 *   - Close: Esc, click outside, or `?` again
 */

"use client";
// WHY "use client": uses useState (open), useEffect (registration), and ref to dialog.

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";
import {
  formatChordForDisplay,
  type HotkeyBinding,
  type HotkeyGroup,
} from "@/lib/hotkey-registry";
import { useHotkeyBindings, useHotkeyScope } from "@/contexts/HotkeyContext";

// ── Group ordering ────────────────────────────────────────────────────────────

/**
 * Display order for groups in the cheat sheet. Navigation is shown first
 * (most frequently used), then symbol-context, action, view, editing.
 */
const GROUP_ORDER: readonly HotkeyGroup[] = [
  "Navigation",
  "Symbol",
  "Action",
  "View",
  "Editing",
];

// ── Component ─────────────────────────────────────────────────────────────────

export function HotkeyCheatSheet() {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const bindings = useHotkeyBindings();
  const { registry } = useHotkeyScope();
  const pathname = usePathname();

  // Register the toggle binding once. We do this here (not in
  // GlobalHotkeyBindings) so the open/close state and registration co-located.
  useEffect(() => {
    return registry.register({
      id: "shell.help.cheatsheet",
      chord: "?",
      scope: "global",
      group: "View",
      label: "Show keyboard shortcuts",
      handler: () => setOpen((v) => !v),
    });
  }, [registry]);

  // Esc closes when open. The keydown chord listener already handles the
  // Esc-clears-buffer case, but it doesn't toggle this component, so we add
  // a local listener while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Focus the filter input on open. requestAnimationFrame defers focus until
  // the dialog is mounted in the DOM.
  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  // Reset filter on close so re-opening starts fresh.
  useEffect(() => {
    if (!open) setFilter("");
  }, [open]);

  // Group bindings for rendering. Filter by the user's search term, then
  // bucket by group, then sort each bucket alphabetically for stable display.
  const grouped = useMemo(() => {
    const lower = filter.trim().toLowerCase();
    const currentPath = pathname ?? "";
    const filtered = bindings.filter((b) => {
      // Hide page-scoped bindings that don't apply to the current route. This
      // prevents instrument mnemonics (D/F/N/I) from appearing in the cheat
      // sheet when the user opens `?` on a different page. The bindings are
      // correctly unregistered when their page unmounts, but this filter adds
      // a second layer in case of concurrent-mount edge cases.
      if (b.scope === "page" && b.page !== undefined) {
        const pg = b.page;
        if (typeof pg === "string") {
          if (pg.endsWith("/") && !currentPath.startsWith(pg)) return false;
          if (!pg.endsWith("/") && currentPath !== pg) return false;
        } else if (pg instanceof RegExp && !pg.test(currentPath)) {
          return false;
        }
      }
      if (!lower) return true;
      return (
        b.label.toLowerCase().includes(lower) ||
        b.chord.toLowerCase().includes(lower) ||
        b.group.toLowerCase().includes(lower)
      );
    });
    const buckets = new Map<HotkeyGroup, HotkeyBinding[]>();
    for (const b of filtered) {
      const arr = buckets.get(b.group) ?? [];
      arr.push(b);
      buckets.set(b.group, arr);
    }
    for (const arr of buckets.values()) {
      arr.sort((a, b) => a.label.localeCompare(b.label));
    }
    return GROUP_ORDER.map((g) => [g, buckets.get(g) ?? []] as const).filter(
      ([, arr]) => arr.length > 0,
    );
  }, [bindings, filter, pathname]);

  if (!open) return null;

  return (
    <div
      // WHY position fixed + z-[9998]: above the StatusBar (z-default), below
      // FlashOverlay (z-[9999]) so a critical alert can still pre-empt the help.
      className="fixed inset-0 z-[9998] flex items-start justify-center bg-black/60 p-6 backdrop-blur-sm"
      onClick={(e) => {
        // Click outside the dialog closes — but only if the click target IS
        // the backdrop (not a child of the dialog body).
        if (e.target === e.currentTarget) setOpen(false);
      }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-label="Keyboard shortcuts"
        aria-modal="true"
        className="mt-12 w-full max-w-2xl overflow-hidden rounded-[2px] border border-border bg-card text-foreground shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <div className="flex flex-col">
            <h2 className="text-sm font-semibold">Keyboard shortcuts</h2>
            <p className="text-[10px] text-muted-foreground">
              Auto-derived from the live registry — every shortcut listed here is wired.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-[2px] p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close keyboard shortcuts"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {/* Filter input */}
        <div className="border-b border-border px-4 py-2">
          <input
            ref={inputRef}
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter shortcuts (e.g. dashboard, ⌘K, navigation)"
            className="h-7 w-full rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            // No type=search — we don't want the browser's clear-X button.
          />
        </div>

        {/* Body — 3-column grid grouped by section. */}
        <div
          className="max-h-[60vh] overflow-y-auto px-4 py-3"
          // Programmatic focus management: pressing Tab moves through dialog
          // children in DOM order. The filter input is first, the close button
          // last — that's the natural reading order.
        >
          {grouped.length === 0 ? (
            <p className="px-1 py-4 text-center text-xs text-muted-foreground">
              No shortcuts match &ldquo;{filter}&rdquo;.
            </p>
          ) : (
            <div className="space-y-4">
              {grouped.map(([group, items]) => (
                <section key={group}>
                  <h3 className="mb-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                    {group}
                  </h3>
                  <ul className="grid grid-cols-1 gap-y-1 sm:grid-cols-2">
                    {items.map((b) => (
                      <li
                        key={b.id}
                        className="flex items-center justify-between gap-3 px-1 py-1 text-[11px]"
                      >
                        <span className="truncate text-foreground">{b.label}</span>
                        <kbd className="ml-auto whitespace-nowrap rounded-[2px] border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-foreground">
                          {formatChordForDisplay(b.chord)}
                        </kbd>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
          <span>Press <kbd className="rounded-[2px] bg-muted px-1 font-mono">?</kbd> anywhere to toggle.</span>
          <span>
            <kbd className="rounded-[2px] bg-muted px-1 font-mono">Esc</kbd> to close.
          </span>
        </div>
      </div>
    </div>
  );
}
