/**
 * components/alerts/AddToWatchlistDialog.tsx — minimal "add entity to a watchlist" dialog.
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-05):
 * The "Add to watchlist" suggested action on the AlertDetailSheet needs a
 * lightweight picker — list the user's watchlists, let them pick one, fire
 * the gateway call. There is no pre-existing dialog for this in the
 * codebase, so we ship a minimal, focused one here. Future waves can lift
 * it into a generic component if more surfaces (search results, dashboard
 * tiles) need the same picker.
 *
 * WHY CONTROLLED open: the parent AlertDetailSheet already manages the
 * "selected alert" state, and routing close-paths through one onClose
 * keeps focus restoration correct (Radix lifts focus back to the trigger).
 */

"use client";
// WHY "use client": uses useQuery (data) + useMutation (gateway calls) +
// useState (form state).

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { cn } from "@/lib/utils";

// ── Props ──────────────────────────────────────────────────────────────────

interface AddToWatchlistDialogProps {
  /** Externally-controlled open state. */
  open: boolean;
  /** Called when the user closes the dialog (any path). */
  onClose: () => void;
  /** Entity to add. May be null when the alert lacks an entity_id. */
  entityId: string | null;
  /** Human-readable label for the entity (ticker preferred). */
  entityLabel: string | null;
}

// ── Component ──────────────────────────────────────────────────────────────

export function AddToWatchlistDialog({
  open,
  onClose,
  entityId,
  entityLabel,
}: AddToWatchlistDialogProps) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // Local message bubble — green on success, red on error. Cleared on close.
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // ── Watchlist list query ───────────────────────────────────────────────
  // WHY enabled: only fetch when the dialog is open + we have a token. No
  // background polling — the list isn't going to change between alerts.
  const { data: watchlists = [], isLoading } = useQuery({
    queryKey: ["watchlists-for-add"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: open && Boolean(accessToken),
    staleTime: 60_000, // watchlist list changes rarely; 60s avoids re-fetch on every open
  });

  // ── Add-member mutation ────────────────────────────────────────────────
  // WHY useMutation (not raw fetch): centralises loading + error states and
  // lets us invalidate dependent queries in one place.
  const addMember = useMutation({
    mutationFn: async ({ watchlistId, entId }: { watchlistId: string; entId: string }) => {
      const gw = createGateway(accessToken);
      return gw.addWatchlistMember(watchlistId, entId);
    },
    onSuccess: async (_, vars) => {
      // Invalidate the watchlist queries that will now show the new member.
      await queryClient.invalidateQueries({ queryKey: ["watchlist", vars.watchlistId] });
      await queryClient.invalidateQueries({ queryKey: ["watchlists-for-add"] });
      setStatus({ kind: "ok", text: "Added to watchlist." });
    },
    onError: (err) => {
      setStatus({ kind: "err", text: err instanceof Error ? err.message : "Failed to add." });
    },
  });

  /** handleAdd — fire the mutation if we have an entity. */
  function handleAdd(watchlistId: string) {
    if (!entityId) return;
    setStatus(null);
    addMember.mutate({ watchlistId, entId: entityId });
  }

  /** handleClose — clear status + delegate to parent. */
  function handleClose() {
    setStatus(null);
    onClose();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) handleClose();
      }}
    >
      <DialogContent className="w-full max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            ADD TO WATCHLIST
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-2 pt-1">
          {/* Entity label header — confirms what we're about to add */}
          <div className="rounded-[2px] border border-border/40 bg-muted/10 p-2 text-[11px] text-foreground">
            {entityLabel ?? "(unnamed entity)"}
          </div>

          {/* Status banner */}
          {status && (
            <div
              role="status"
              className={cn(
                "rounded-[2px] border p-2 text-[11px]",
                status.kind === "ok"
                  ? "border-positive/40 bg-positive/10 text-positive"
                  : "border-destructive/40 bg-destructive/10 text-destructive",
              )}
            >
              {status.text}
            </div>
          )}

          {/* Watchlist list */}
          {isLoading ? (
            <p className="py-3 text-center text-[11px] text-muted-foreground">Loading watchlists…</p>
          ) : watchlists.length === 0 ? (
            <p className="py-3 text-center text-[11px] text-muted-foreground">
              No watchlists yet. Create one from the Watchlists page first.
            </p>
          ) : (
            <ul role="list" className="max-h-64 divide-y divide-border/30 overflow-y-auto">
              {watchlists.map((w) => (
                <li key={w.watchlist_id}>
                  <button
                    type="button"
                    onClick={() => handleAdd(w.watchlist_id)}
                    disabled={!entityId || addMember.isPending}
                    className={cn(
                      "flex w-full items-center justify-between px-2 py-1.5 text-[11px] text-foreground",
                      "hover:bg-muted/40 disabled:cursor-not-allowed disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]",
                    )}
                    aria-label={`Add to watchlist ${w.name}`}
                  >
                    <span className="truncate">{w.name}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {w.members?.length ?? 0} members
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-[2px] px-3 py-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              Done
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
