"use client"; // WHY: useForm + useMutation both require browser-side state and event handlers

/**
 * features/portfolio/components/EditPortfolioDialog.tsx
 *
 * WHY THIS EXISTS: Modal for editing per-portfolio settings that don't require
 * recreating the portfolio. Currently supports:
 *   - Cost basis method (FIFO / AVCO) — PLAN-0114 W6
 *
 * This dialog was created as a SEPARATE component from CreatePortfolioDialog for
 * three reasons:
 *   1. Different API path: creation uses POST /v1/portfolios; settings use PATCH
 *      /v1/portfolios/{id}. Combining them into one component would require a
 *      conditional code path and make the submit logic harder to follow.
 *   2. Different required data: Edit needs the existing portfolio to pre-fill
 *      the form with the current values. Create starts with blank defaults.
 *   3. Separation of concerns: adding a new setting to "edit" shouldn't require
 *      touching the "create" flow (open-closed principle).
 *
 * DATA FLOW:
 *   1. Parent passes the current Portfolio object to pre-fill the form.
 *   2. User changes cost_basis_method via Select.
 *   3. handleSubmit validates with Zod → calls PATCH /v1/portfolios/{id}.
 *   4. On success → onSuccess() triggers TanStack Query invalidation (parent).
 *   5. The portfolios list refetches and the selector shows the new setting.
 *
 * WHY useForm (not raw useState): same reasons as CreatePortfolioDialog —
 * per-field validation, isSubmitting guard, and Zod as single source of truth.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { createGateway } from "@/lib/gateway";
import type { Portfolio } from "@/types/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  COST_BASIS_METHODS,
  COST_BASIS_METHOD_LABELS,
  type CostBasisMethod,
} from "./CreatePortfolioDialog";

// ── Validation schema ──────────────────────────────────────────────────────

/**
 * WHY a separate schema from CreatePortfolioDialog: this schema only validates
 * the settings fields (not name + currency which are immutable after creation).
 * Keeping them separate avoids accidental coupling between the two forms.
 */
const editPortfolioSchema = z.object({
  cost_basis_method: z.enum(COST_BASIS_METHODS, {
    errorMap: () => ({ message: "Select a cost basis method" }),
  }),
});

type EditPortfolioFormValues = z.infer<typeof editPortfolioSchema>;

// ── Component ──────────────────────────────────────────────────────────────

export interface EditPortfolioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  portfolio: Portfolio;
  accessToken: string | null | undefined;
}

export function EditPortfolioDialog({
  open,
  onOpenChange,
  onSuccess,
  portfolio,
  accessToken,
}: EditPortfolioDialogProps) {
  // WHY portfolio.cost_basis_method as default: pre-fills the selector with
  // the current setting so the user immediately sees what's active and can
  // confirm or change it. Fallback to "FIFO" for portfolios created before W6.
  const currentMethod: CostBasisMethod =
    (portfolio as Portfolio & { cost_basis_method?: string }).cost_basis_method === "AVCO"
      ? "AVCO"
      : "FIFO";

  const form = useForm<EditPortfolioFormValues>({
    resolver: zodResolver(editPortfolioSchema),
    defaultValues: {
      cost_basis_method: currentMethod,
    },
  });

  // Server-level error slot (e.g. network failure, S1 422).
  const serverError = form.formState.errors.root?.serverError?.message;

  async function onSubmit(values: EditPortfolioFormValues) {
    try {
      // PATCH /v1/portfolios/{id} via S9 → S1 UpdatePortfolioUseCase.
      // WHY only patch changed fields: the patchPortfolio call accepts
      // a partial object — if only cost_basis_method changed, only that field
      // is sent over the wire (minimises payload and avoids overwriting
      // concurrent changes from another session).
      await createGateway(accessToken).patchPortfolio(portfolio.portfolio_id, {
        cost_basis_method: values.cost_basis_method,
      });
      onSuccess();
      onOpenChange(false);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to update portfolio settings.";
      form.setError("root.serverError" as "root", { message });
    }
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen && !form.formState.isSubmitting) {
      // Reset to the current portfolio values so reopening shows the real state.
      form.reset({ cost_basis_method: currentMethod });
    }
    onOpenChange(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-[11px] font-mono uppercase tracking-[0.08em]">
            Portfolio Settings
          </DialogTitle>
        </DialogHeader>

        {/* Portfolio name and currency are read-only (shown as static text)
            WHY static: renaming uses PUT /portfolios/{id} (separate endpoint
            and intentional UX — rename is a destructive-feeling action that
            warrants its own dialog in a future iteration). */}
        <div className="text-[11px] font-mono text-muted-foreground space-y-0.5 mb-2">
          <div>
            <span className="uppercase tracking-[0.06em]">Portfolio: </span>
            <span className="text-foreground">{portfolio.name}</span>
          </div>
          <div>
            <span className="uppercase tracking-[0.06em]">Currency: </span>
            <span className="text-foreground">{portfolio.currency}</span>
          </div>
        </div>

        <Form {...form}>
          <div className="space-y-4 py-2">
            {/* Cost basis method — PLAN-0114 W6.
                WHY explain the two methods inline: retail investors may not know
                the difference between FIFO and AVCO. A brief inline explanation
                avoids needing to look it up, reducing friction and support load. */}
            <FormField
              control={form.control}
              name="cost_basis_method"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Cost Basis Method
                  </FormLabel>
                  <FormControl>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={form.formState.isSubmitting}
                    >
                      <SelectTrigger className="h-8 text-[11px] font-mono bg-background border-border w-full">
                        <SelectValue placeholder="Select method" />
                      </SelectTrigger>
                      <SelectContent>
                        {COST_BASIS_METHODS.map((method) => (
                          <SelectItem
                            key={method}
                            value={method}
                            className="text-[11px] font-mono"
                          >
                            {COST_BASIS_METHOD_LABELS[method]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </FormControl>
                  {/* Contextual help text — explain the methods at the point of choice
                      so the user doesn't need to leave the dialog to understand. */}
                  <p className="text-[10px] text-muted-foreground leading-relaxed">
                    FIFO: oldest lots are sold first (default, common for tax reporting).
                    AVCO: all lots are averaged — simpler for frequent traders.
                  </p>
                  <FormMessage />
                </FormItem>
              )}
            />

            {serverError && (
              <p role="alert" className="text-[11px] text-destructive font-mono">
                {serverError}
              </p>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleOpenChange(false)}
              disabled={form.formState.isSubmitting}
              className="text-[11px] font-mono"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void form.handleSubmit(onSubmit)()}
              disabled={form.formState.isSubmitting}
              className="text-[11px] font-mono"
            >
              {form.formState.isSubmitting ? "Saving…" : "Save Settings"}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
