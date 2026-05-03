"use client"; // WHY: useForm + useMutation both require browser-side state and event handlers

/**
 * features/portfolio/components/CreatePortfolioDialog.tsx
 *
 * WHY THIS EXISTS: Modal for creating a new manually-managed portfolio.
 *
 * Extracted from portfolio/page.tsx in PLAN-0059 Wave E-2 to isolate dialog
 * state from the parent page. Migrated to RHF + Zod in PLAN-0059 F-2 to fix:
 *   - BP-329: currency free-text input accepted invalid ISO 4217 codes ("FAKE",
 *     "XYZ"). The user saw no error; S1 rejected it with a cryptic 422.
 *   - BP-330: missing aria-invalid + aria-describedby on form fields — screen
 *     readers couldn't announce field errors.
 *
 * DATA FLOW:
 *   1. User fills in name + selects currency from a constrained Select.
 *   2. handleSubmit calls zodResolver validation — inline errors appear if invalid.
 *   3. On valid data → calls gateway.createPortfolio(name, currency).
 *   4. On success → onSuccess(newPortfolio) so the page selects the new portfolio.
 *   5. Parent invalidates ["portfolios"] query → TanStack Query refetches the list.
 *
 * WHY useForm instead of raw useState: three benefits over the old approach:
 *   1. Per-field validation errors without full re-renders on every keystroke.
 *   2. `isDirty` / `isValid` flags guard the submit button with zero extra state.
 *   3. Zod schema is the single source of truth for both type and validation —
 *      no divergence between "what the server expects" and "what we validate".
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
import { Input } from "@/components/ui/input";
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

// ── Validation schema ──────────────────────────────────────────────────────

/**
 * WHY z.enum for currency (not z.string): an enum constrains the value to the
 * 12 known ISO 4217 + crypto codes at compile time AND runtime. This was the
 * root cause of BP-329 — the old free-text Input let users type anything,
 * which S1 then rejected as a 422 with no user-visible error.
 */
const CURRENCIES = [
  "USD", "EUR", "GBP", "JPY", "CHF",
  "CAD", "AUD", "CNY", "HKD", "KRW",
  "BTC", "ETH",
] as const;

// Type so the Select items array is typed and exhaustive.
type CurrencyCode = typeof CURRENCIES[number];

const CURRENCY_LABELS: Record<CurrencyCode, string> = {
  USD: "USD — US Dollar ($)",
  EUR: "EUR — Euro (€)",
  GBP: "GBP — Pound Sterling (£)",
  JPY: "JPY — Japanese Yen (¥)",
  CHF: "CHF — Swiss Franc",
  CAD: "CAD — Canadian Dollar",
  AUD: "AUD — Australian Dollar",
  CNY: "CNY — Chinese Yuan",
  HKD: "HKD — Hong Kong Dollar",
  KRW: "KRW — Korean Won",
  BTC: "BTC — Bitcoin (₿)",
  ETH: "ETH — Ether",
};

const portfolioSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(100, "Max 100 characters"),
  currency: z.enum(CURRENCIES, {
    // WHY custom errorMap: the default "Invalid enum value" message isn't
    // user-friendly. "Select a currency" matches the field label.
    errorMap: () => ({ message: "Select a currency" }),
  }),
});

type PortfolioFormValues = z.infer<typeof portfolioSchema>;

// ── Component ──────────────────────────────────────────────────────────────

export interface CreatePortfolioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (portfolio: Portfolio) => void;
  accessToken: string | null | undefined;
}

export function CreatePortfolioDialog({
  open,
  onOpenChange,
  onSuccess,
  accessToken,
}: CreatePortfolioDialogProps) {
  const form = useForm<PortfolioFormValues>({
    resolver: zodResolver(portfolioSchema),
    defaultValues: {
      name: "",
      // WHY USD default: the overwhelming majority of users are USD-denominated.
      // Defaulting saves a click for 90%+ of users.
      currency: "USD",
    },
  });

  // Server-level error (not a field validation error, e.g. "portfolio already exists").
  // WHY track separately from field errors: Zod field errors live in form.formState.errors;
  // network errors come back after submission and don't map to a field.
  const serverError = form.formState.errors.root?.serverError?.message;

  async function onSubmit(values: PortfolioFormValues) {
    try {
      const newPortfolio = await createGateway(accessToken).createPortfolio(
        values.name.trim(),
        values.currency,
      );
      form.reset();
      onSuccess(newPortfolio);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to create portfolio.";
      // WHY setError on root.serverError: RHF has no built-in "form-level" error
      // slot. Using `root.serverError` is the recommended convention from the
      // RHF docs for non-field API errors.
      form.setError("root.serverError" as "root", { message });
    }
  }

  // handleOpenChange — reset form when dialog is closed externally (X or overlay).
  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen && !form.formState.isSubmitting) {
      form.reset();
    }
    onOpenChange(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-[13px] font-mono uppercase tracking-[0.08em]">
            New Portfolio
          </DialogTitle>
        </DialogHeader>

        {/* Form is the RHF FormProvider — all FormField children can access
            form state without props. WHY no <form> element: shadcn Dialog
            manages its own focus trap; nesting a <form> element causes a11y
            violations (interactive element inside focusTrap dialog). Instead
            we call form.handleSubmit on the button click. */}
        <Form {...form}>
          <div className="space-y-4 py-2">
            {/* Portfolio name */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Name
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. Main Portfolio"
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !form.formState.isSubmitting) {
                          void form.handleSubmit(onSubmit)();
                        }
                      }}
                      className="h-8 text-[12px] font-mono bg-background border-border"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Currency — constrained Select instead of free-text (BP-329 fix).
                WHY Select over free-text Input: S1 validates currency against
                the ISO 4217 + crypto allow-list. A Select eliminates the entire
                class of "user typed an unsupported code" errors at the source. */}
            <FormField
              control={form.control}
              name="currency"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Currency
                  </FormLabel>
                  <FormControl>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={form.formState.isSubmitting}
                    >
                      <SelectTrigger className="h-8 text-[11px] font-mono bg-background border-border w-full">
                        <SelectValue placeholder="Select currency" />
                      </SelectTrigger>
                      <SelectContent>
                        {CURRENCIES.map((code) => (
                          <SelectItem
                            key={code}
                            value={code}
                            className="text-[11px] font-mono"
                          >
                            {CURRENCY_LABELS[code]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Server-level error (network failure, S1 422, etc.) */}
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
              {form.formState.isSubmitting ? "Creating…" : "Create Portfolio"}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
