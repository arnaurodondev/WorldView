/**
 * components/screener/SavedScreensDialog.tsx — Save / Load named screens
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-05): the screener filter set is the user's
 * intellectual capital — they spent minutes tuning it. A "Saved Screens" dialog
 * lets them name and recall those configurations without rebuilding from
 * scratch each session. This dialog is the UI surface over the localStorage
 * CRUD in `lib/saved-screens.ts`.
 *
 * WHY a single dialog with TWO tabs (Save | Load) instead of separate
 * dialogs / dropdowns:
 *   - One entry point ("Saved Screens" button) → users always know where to go.
 *   - The Save tab is the canonical "name this thing and store it" pattern;
 *     Load is the inverse. Tabs make the relationship discoverable without
 *     menu hunting.
 *   - Mirrors the macOS "Save As..." panel UX users already know.
 *
 * WHY shadcn/ui Dialog (not a hand-rolled portal):
 *   - Already in the dependency set; consistent overlay/animation tokens.
 *   - Built on Radix → focus trap + Esc-to-close + ARIA dialog role come free.
 *
 * WHY confirm-before-delete:
 *   - localStorage data is unrecoverable. A misclick on a 50-row Load list
 *     could nuke a 6-month-old screen. window.confirm is the smallest possible
 *     guard — text-only, blocks on user action, zero dependencies.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (header "Saved Screens" button)
 */

"use client";
// WHY "use client": uses useState for local form state, dispatches DOM events
// (window.confirm), and calls localStorage helpers.

import { useState, useCallback } from "react";
import { Trash2, FolderOpen, Save } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { DataTimestamp } from "@/components/ui/data-timestamp";
import {
  listSavedScreens,
  saveScreen,
  deleteScreen,
  type SavedScreen,
} from "@/lib/saved-screens";
import type { FilterState } from "./ScreenerFilterBar";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface SavedScreensDialogProps {
  /** Controlled open state. */
  open: boolean;
  /** Called when the dialog requests to close (Esc / outside click / X). */
  onOpenChange: (open: boolean) => void;
  /** The CURRENT filter state to save when the user clicks Save. */
  currentFilters: FilterState;
  /** Called after a successful save (parent can show a toast / refresh). */
  onSaved?: (screen: SavedScreen) => void;
  /** Called when the user picks a screen to load. Parent applies filters. */
  onLoad: (filters: FilterState) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export function SavedScreensDialog({
  open,
  onOpenChange,
  currentFilters,
  onSaved,
  onLoad,
}: SavedScreensDialogProps) {
  // WHY local state for the name input: typing-time state should NEVER live in
  // localStorage; we only persist on explicit Save. This decouples typing
  // latency from disk writes.
  const [name, setName] = useState("");

  // WHY local copy of the screen list (instead of computing on every render):
  // listSavedScreens reads + parses localStorage every call. Cheap, but caching
  // it in state lets us re-list ONLY after a save/delete (the events that
  // change the list).
  const [screens, setScreens] = useState<SavedScreen[]>(() => listSavedScreens());

  // WHY refresh on tab change to "load": handles the edge case where another
  // tab in the same browser saved a screen while this dialog was open.
  const refresh = useCallback(() => {
    setScreens(listSavedScreens());
  }, []);

  function handleSave() {
    const trimmed = name.trim();
    if (!trimmed) return; // WHY: never create blank-named screens (footgun)
    const created = saveScreen(trimmed, currentFilters);
    setScreens(listSavedScreens());
    setName("");
    onSaved?.(created);
  }

  function handleDelete(id: string, screenName: string) {
    // WHY confirm: see file-level "WHY confirm-before-delete".
    // eslint-disable-next-line no-alert
    if (!window.confirm(`Delete saved screen "${screenName}"? This cannot be undone.`)) {
      return;
    }
    deleteScreen(id);
    setScreens(listSavedScreens());
  }

  function handleLoad(screen: SavedScreen) {
    onLoad(screen.filters);
    onOpenChange(false); // WHY auto-close: a load action is a "commit" — getting out of the user's way is correct.
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-[11px] font-mono uppercase tracking-[0.08em]">
            Saved Screens
          </DialogTitle>
          <DialogDescription className="text-[11px]">
            Save the current filter set or load a previously saved screen.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="save" className="w-full" onValueChange={(v) => v === "load" && refresh()}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="save" className="text-[11px]">Save current</TabsTrigger>
            <TabsTrigger value="load" className="text-[11px]">
              Load screen
              {screens.length > 0 && (
                // WHY tabular-nums: keeps the digit width stable as count changes.
                <span className="ml-1 font-mono tabular-nums text-muted-foreground">
                  ({screens.length})
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          {/* ── Save tab ──────────────────────────────────────────────── */}
          <TabsContent value="save" className="mt-3 space-y-3">
            <label htmlFor="saved-screen-name" className="block text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
              Screen name
            </label>
            <input
              id="saved-screen-name"
              autoFocus
              type="text"
              placeholder="e.g. Large-cap tech with low P/E"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
              className="h-8 w-full px-2 text-[11px] font-mono bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
              aria-label="Saved screen name"
            />
            <button
              type="button"
              onClick={handleSave}
              disabled={!name.trim()}
              className={cn(
                "flex h-8 w-full items-center justify-center gap-1 px-3 text-[11px] font-mono uppercase tracking-[0.06em] rounded-[2px] border transition-colors",
                name.trim()
                  ? "bg-primary/10 border-primary/60 text-primary hover:bg-primary/20"
                  : "bg-muted/20 border-border text-muted-foreground cursor-not-allowed",
              )}
              aria-label="Save current filter set"
            >
              <Save className="h-3 w-3" aria-hidden strokeWidth={1.5} />
              Save
            </button>
          </TabsContent>

          {/* ── Load tab ──────────────────────────────────────────────── */}
          <TabsContent value="load" className="mt-3">
            {screens.length === 0 ? (
              // WHY inline empty: §0.5 bans giant centered empty-states.
              <p className="px-2 py-3 text-[11px] text-muted-foreground">
                No saved screens yet. Save the current filter set first.
              </p>
            ) : (
              <ul className="max-h-[260px] overflow-y-auto" role="list" aria-label="Saved screens">
                {screens.map((s) => (
                  <li
                    key={s.id}
                    // WHY gap-px: keeps the row separation tokenised (DESIGN_SYSTEM §0).
                    className="flex items-center gap-px px-2 py-1.5 hover:bg-white/[0.04] border-b border-border/30"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] text-foreground truncate">{s.name}</div>
                      <div className="text-[10px] text-muted-foreground">
                        Updated <DataTimestamp timestamp={s.updatedAt} />
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleLoad(s)}
                      className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors"
                      aria-label={`Load screen ${s.name}`}
                    >
                      <FolderOpen className="h-3 w-3" aria-hidden strokeWidth={1.5} />
                      Load
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(s.id, s.name)}
                      className="flex h-7 items-center justify-center px-2 text-muted-foreground hover:text-destructive transition-colors"
                      aria-label={`Delete screen ${s.name}`}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden strokeWidth={1.5} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
