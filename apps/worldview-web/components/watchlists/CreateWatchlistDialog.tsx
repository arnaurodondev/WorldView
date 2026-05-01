/**
 * components/watchlists/CreateWatchlistDialog.tsx — Watchlist creation dialog
 *
 * PLAN-0059 I-1: minimal "name + submit" dialog used by the /watchlists hub.
 * Members are added separately via the detail page (matches S1's two-step
 * "create then populate" API contract).
 */

"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Watchlist } from "@/types/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the created watchlist after success — typically navigates to it. */
  onCreated?: (wl: Watchlist) => void;
}

const NAME_MAX = 80;

export function CreateWatchlistDialog({ open, onOpenChange, onCreated }: Props) {
  const gateway = useApiClient();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");

  const createMut = useMutation({
    mutationFn: (n: string) => gateway.createWatchlist(n),
    onSuccess: (wl) => {
      // Invalidate the list so the hub refreshes.
      void qc.invalidateQueries({ queryKey: qk.watchlists.list() });
      toast.success(`Watchlist "${wl.name}" created`);
      setName("");
      onOpenChange(false);
      onCreated?.(wl);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to create watchlist");
    },
  });

  const trimmed = name.trim();
  const valid = trimmed.length > 0 && trimmed.length <= NAME_MAX;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Create watchlist</DialogTitle>
          <DialogDescription>
            Group instruments to track them across alerts, dashboard, and
            screener. You can add members on the next screen.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid || createMut.isPending) return;
            createMut.mutate(trimmed);
          }}
        >
          <div className="space-y-2 py-2">
            <label htmlFor="wl-name" className="text-[11px] text-muted-foreground">
              Name
            </label>
            <Input
              id="wl-name"
              density="compact"
              autoFocus
              autoComplete="off"
              maxLength={NAME_MAX}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Mega-cap tech"
              aria-invalid={name.length > 0 && !valid || undefined}
            />
            <p className="text-[10px] text-muted-foreground">
              {trimmed.length}/{NAME_MAX} characters
            </p>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              density="compact"
              onClick={() => onOpenChange(false)}
              disabled={createMut.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              density="compact"
              disabled={!valid || createMut.isPending}
            >
              {createMut.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
