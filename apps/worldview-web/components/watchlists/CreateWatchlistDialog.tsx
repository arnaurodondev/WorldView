/**
 * components/watchlists/CreateWatchlistDialog.tsx — Watchlist creation dialog
 *
 * PLAN-0059 I-1: minimal "name + submit" dialog used by the /watchlists hub.
 * Members are added separately via the detail page (matches S1's two-step
 * "create then populate" API contract).
 *
 * Migrated to RHF + Zod in PLAN-0059 F-2 to fix:
 *   - BP-330: missing aria-invalid + aria-describedby — screen readers couldn't
 *     announce the "Name is required" error.
 *
 * WHY keep the existing useMutation pattern: the mutation itself is correct;
 * we only needed RHF to own validation and error wiring. The mutation's
 * onSuccess/onError handlers are unchanged.
 *
 * WHY char count stays: finance users naming watchlists by strategy (e.g.
 * "US large-cap momentum Q2 2026") need to see the character budget to avoid
 * truncation in the sidebar nav where names are displayed at ~150px.
 */

"use client"; // WHY: useForm + useMutation both require browser-side state

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useApiClient } from "@/lib/api-client";
import { GatewayError } from "@/lib/gateway";
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
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import type { Watchlist } from "@/types/api";

const NAME_MAX = 80;

const watchlistSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(NAME_MAX, `Max ${NAME_MAX} characters`),
});

type WatchlistFormValues = z.infer<typeof watchlistSchema>;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the created watchlist after success — typically navigates to it. */
  onCreated?: (wl: Watchlist) => void;
}

export function CreateWatchlistDialog({ open, onOpenChange, onCreated }: Props) {
  const gateway = useApiClient();
  const qc = useQueryClient();

  const form = useForm<WatchlistFormValues>({
    resolver: zodResolver(watchlistSchema),
    defaultValues: { name: "" },
  });

  const createMut = useMutation({
    mutationFn: (n: string) => gateway.createWatchlist(n),
    // WHY only retry GatewayError 5xx: non-GatewayErrors (plain Error, business
    // logic) and 4xx (409 duplicate, 422 invalid) are deterministic — retrying
    // re-surfaces the same user error and delays the onError UI feedback.
    retry: (count: number, err: Error) => {
      if (!(err instanceof GatewayError)) return false;
      if (err.status < 500) return false;
      return count < 3;
    },
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: (wl) => {
      // Invalidate the list so the hub refreshes.
      void qc.invalidateQueries({ queryKey: qk.watchlists.list() });
      toast.success(`Watchlist "${wl.name}" created`);
      form.reset();
      onOpenChange(false);
      onCreated?.(wl);
    },
    onError: (err) => {
      // WHY setError on root.serverError: maps the network/API error to the
      // RHF root error slot so FormMessage can surface it as a role="alert".
      form.setError("root.serverError" as "root", {
        message: err instanceof Error ? err.message : "Failed to create watchlist",
      });
    },
  });

  function onSubmit(values: WatchlistFormValues) {
    createMut.mutate(values.name.trim());
  }

  // Current trimmed length for the character counter.
  const trimmedLength = form.watch("name").trim().length;

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

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="space-y-4"
          >
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] text-muted-foreground">
                    Name
                  </FormLabel>
                  <FormControl>
                    <Input
                      density="compact"
                      autoFocus
                      autoComplete="off"
                      placeholder="e.g. Mega-cap tech"
                      {...field}
                    />
                  </FormControl>
                  {/* WHY always render the char counter (not only on error):
                      finance users naming watchlists need to see the budget;
                      an error that disappears the counter as they type is
                      more confusing than one that coexists with it. */}
                  <p className="text-[10px] text-muted-foreground tabular-nums">
                    {trimmedLength}/{NAME_MAX} characters
                  </p>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Server-level error — stored at errors.root.serverError.message
                (setError uses "root.serverError" as the dotted path). */}
            {form.formState.errors.root?.serverError && (
              <p role="alert" className="text-[11px] text-destructive font-mono">
                {String(form.formState.errors.root.serverError.message ?? "")}
              </p>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                density="compact"
                onClick={() => {
                  form.reset();
                  onOpenChange(false);
                }}
                disabled={createMut.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                density="compact"
                disabled={createMut.isPending || !form.formState.isValid}
              >
                {createMut.isPending ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
