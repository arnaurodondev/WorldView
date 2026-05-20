/**
 * components/portfolio/watchlists/WatchlistTabBar.tsx — Watchlist tab bar with rename/delete menus
 *
 * WHY EXTRACTED: The tab bar (including CreateWatchlistInput, RenameTabInput, and
 * the DropdownMenu controls) is a self-contained UI region that was embedded in
 * WatchlistsTabPanel. Extracting it keeps the parent under 400 lines and makes
 * the tab-bar logic independently readable.
 *
 * WHY custom tab bar (not shadcn Tabs): the outer portfolio page already uses
 * shadcn Tabs, and nesting Radix Tabs inside Tabs causes keyboard navigation
 * conflicts.
 *
 * WHO USES IT: WatchlistsTabPanel — never directly by pages.
 */

"use client";
// WHY "use client": uses useState, useEffect, useRef for inline create/rename inputs.

import { useState, useRef, useEffect } from "react";
import { Loader2, X, Plus, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Watchlist } from "@/types/api";

// ── CreateWatchlistInput ───────────────────────────────────────────────────────
// WHY inline (not a separate file): only used by WatchlistTabBar; no other
// consumer exists. Keeping it here avoids a third micro-file for a 30-line form.

function CreateWatchlistInput({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (name: string) => void;
}) {
  const [name, setName] = useState("");

  // WHY autoFocus via ref: the input should be focused immediately when the inline
  // create form appears, so the user can type the name without an extra click.
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && name.trim()) {
      onCreate(name.trim());
    } else if (e.key === "Escape") {
      onCancel();
    }
  }

  return (
    <div className="flex h-[36px] items-center gap-1 px-2">
      <input
        ref={inputRef}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Watchlist name…"
        maxLength={64}
        className="h-6 flex-1 min-w-0 bg-background border border-border rounded-[2px] px-2 font-mono text-[11px] text-foreground outline-none focus:border-primary placeholder:text-muted-foreground/60"
        aria-label="New watchlist name"
      />
      <button
        disabled={!name.trim()}
        onClick={() => name.trim() && onCreate(name.trim())}
        className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
      >
        Create
      </button>
      <button
        onClick={onCancel}
        aria-label="Cancel"
        className="h-6 w-6 flex items-center justify-center text-muted-foreground hover:text-foreground shrink-0"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── RenameTabInput ─────────────────────────────────────────────────────────────
// WHY separate component: isolates the focused input state so that the parent
// tab bar doesn't re-render on every keystroke (only the rename cell does).

function RenameTabInput({
  currentName,
  isPending,
  onConfirm,
  onCancel,
}: {
  currentName: string;
  isPending: boolean;
  onConfirm: (newName: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(currentName);
  const inputRef = useRef<HTMLInputElement>(null);

  // WHY select-on-mount: pre-selects the existing name so the user can immediately
  // type a replacement without manually clearing it first.
  useEffect(() => {
    inputRef.current?.select();
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      onConfirm(value.trim());
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="flex items-center h-full px-1">
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        // WHY blur-confirm: committing on blur means clicking elsewhere saves the rename
        // without needing Enter — matches standard spreadsheet/terminal editing conventions.
        // WHY isPending guard: disabled inputs can still fire blur in some browsers;
        // skip the confirm call when the mutation is already in-flight.
        onBlur={() => { if (!isPending) onConfirm(value.trim()); }}
        disabled={isPending}
        maxLength={64}
        className={cn(
          "h-6 w-[120px] bg-background border border-primary rounded-[2px] px-2",
          "font-mono text-[11px] text-foreground outline-none",
          isPending && "opacity-60 cursor-not-allowed",
        )}
        aria-label="Rename watchlist"
      />
      {isPending && <Loader2 className="ml-1 h-3 w-3 animate-spin text-muted-foreground shrink-0" />}
    </div>
  );
}

// ── WatchlistTabBar types ─────────────────────────────────────────────────────

export interface WatchlistTabBarProps {
  watchlists: Watchlist[];
  activeWatchlistId: string | null;
  /** Whether the inline "create watchlist" input is currently visible */
  creating: boolean;
  createIsPending: boolean;
  /** ID of the watchlist currently being renamed (null = none) */
  renamingWatchlistId: string | null;
  renameMutationIsPending: boolean;
  deleteWatchlistMutationIsPending: boolean;
  activeWatchlistMemberCount?: number;
  onSelectWatchlist: (watchlistId: string) => void;
  onStartCreate: () => void;
  onCancelCreate: () => void;
  onConfirmCreate: (name: string) => void;
  onStartRename: (watchlistId: string) => void;
  onConfirmRename: (watchlistId: string, newName: string) => void;
  onCancelRename: () => void;
  onDeleteWatchlist: (watchlistId: string) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistTabBar({
  watchlists,
  activeWatchlistId,
  creating,
  createIsPending,
  renamingWatchlistId,
  renameMutationIsPending,
  deleteWatchlistMutationIsPending,
  activeWatchlistMemberCount,
  onSelectWatchlist,
  onStartCreate,
  onCancelCreate,
  onConfirmCreate,
  onStartRename,
  onConfirmRename,
  onCancelRename,
  onDeleteWatchlist,
}: WatchlistTabBarProps) {
  if (creating) {
    // Inline create form replaces the tab bar while creating
    return (
      <div className="border-b border-border">
        <CreateWatchlistInput
          onCancel={onCancelCreate}
          onCreate={onConfirmCreate}
        />
        {createIsPending && (
          <div className="flex items-center gap-1 px-2 py-0.5 text-[10px] text-muted-foreground">
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
            Creating…
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-[36px] items-center gap-0 border-b border-border overflow-x-auto shrink-0">
      {watchlists.map((wl) => (
        <div
          key={wl.watchlist_id}
          className={cn(
            "flex items-center gap-0.5 h-full border-b-2 shrink-0 group/tab",
            wl.watchlist_id === activeWatchlistId
              ? "border-primary"
              : "border-transparent",
          )}
        >
          {/* WHY conditional render: when this tab is in rename mode, replace the
              read-only label with an inline text input pre-filled with the current
              name. Enter commits, Escape cancels. Blur also commits if a name was
              typed (consistent with Bloomberg's in-place rename pattern). */}
          {renamingWatchlistId === wl.watchlist_id ? (
            <RenameTabInput
              currentName={wl.name}
              isPending={renameMutationIsPending}
              onConfirm={(newName) => {
                if (newName && newName !== wl.name) {
                  onConfirmRename(wl.watchlist_id, newName);
                } else {
                  onCancelRename();
                }
              }}
              onCancel={onCancelRename}
            />
          ) : (
            <button
              role="tab"
              aria-selected={wl.watchlist_id === activeWatchlistId}
              onClick={() => onSelectWatchlist(wl.watchlist_id)}
              className={cn(
                "h-full px-3 text-[11px] font-mono transition-colors whitespace-nowrap",
                wl.watchlist_id === activeWatchlistId
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {wl.name}
            </button>
          )}

          {/* ··· dropdown for rename/delete — visible on tab hover, hidden during rename */}
          {renamingWatchlistId !== wl.watchlist_id && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  aria-label={`Options for ${wl.name}`}
                  className={cn(
                    "h-5 w-5 flex items-center justify-center rounded-[2px] mr-1",
                    "opacity-0 group-hover/tab:opacity-100 transition-opacity",
                    "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                  )}
                  // WHY stopPropagation on mousedown: prevent the dropdown trigger from
                  // also activating the tab button and triggering an unintended tab switch.
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <MoreHorizontal className="h-3 w-3" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[120px]">
                <DropdownMenuItem
                  className="text-[11px]"
                  onClick={() => {
                    onSelectWatchlist(wl.watchlist_id);
                    onStartRename(wl.watchlist_id);
                  }}
                >
                  <Pencil className="h-3 w-3 mr-1.5" />
                  Rename
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-[11px] text-negative focus:text-negative"
                  disabled={deleteWatchlistMutationIsPending}
                  onClick={() => onDeleteWatchlist(wl.watchlist_id)}
                >
                  <Trash2 className="h-3 w-3 mr-1.5" />
                  Delete watchlist
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      ))}

      {/* [+ New] button — always on the right side of the tab bar */}
      <button
        onClick={onStartCreate}
        aria-label="Create new watchlist"
        className="ml-1 h-6 w-6 flex items-center justify-center rounded-[2px] text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors shrink-0"
        title="New watchlist"
      >
        <Plus className="h-3.5 w-3.5" />
      </button>

      {/* Member count badge — shows count for the active watchlist */}
      {activeWatchlistMemberCount !== undefined && (
        <span className="ml-auto px-2 font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
          {activeWatchlistMemberCount} symbols
        </span>
      )}
    </div>
  );
}
