"use client"; // WHY: useForm + useMutation require browser-side state and event handlers

/**
 * features/portfolio/components/AddPositionDialog.tsx
 *
 * WHY THIS EXISTS: Modal for manually adding a new position to a portfolio.
 *
 * Migrated to RHF + Zod in PLAN-0059 F-2 to fix:
 *   - BP-328: quantity=0 and avgPrice=0 passed the old client-side gate
 *     (`parsedQty <= 0` only caught negative, not zero). A zero-quantity BUY
 *     transaction is meaningless and creates a phantom holding at 0 shares.
 *   - BP-330: missing aria-invalid + aria-describedby — screen readers couldn't
 *     announce validation errors.
 *
 * WHY NumberInput instead of <Input type="number">: NumberInput parses
 * TradingView shorthand ("1.5k" → 1500, "25%" → 0.25) which institutional
 * traders expect from any number input in a finance terminal. The old Input
 * type="number" also had a browser-native stepper widget that cluttered the UI.
 *
 * TICKER RESOLUTION FLOW (unchanged from pre-migration):
 *   1. User types a ticker (e.g. "AAPL") + quantity + optional avg price.
 *   2. Zod validates all three fields before the network round-trip.
 *   3. On valid submit → searchInstruments("AAPL") → gets instrument_id.
 *   4. addPosition(portfolioId, instrument_id, qty, price) → POST /v1/transactions.
 *   5. onSuccess() → parent invalidates ["holdings", portfolioId].
 *
 * DATA SOURCE: S9 → S3 (instrument search), S9 → S1 (transaction POST).
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { createGateway } from "@/lib/gateway";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
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
 * WHY positive() for quantity (not just nonnegative()):
 * A BUY transaction with quantity=0 creates a holding record with 0 shares.
 * S1 won't reject it (it's a valid BUY), but it produces a phantom row in
 * the holdings table. Blocking at the form level is the right place (BP-328).
 *
 * WHY nonnegative() for avgPrice (not positive()):
 * Some users deliberately enter positions at cost=0 — gifted shares, inherited
 * positions, or when exact cost basis is unknown. Zero is a valid average price
 * in S1's data model. The old guard also allowed 0, so this preserves behaviour.
 * Only negative prices are semantically wrong (can't buy shares at a negative
 * price in a long portfolio).
 */
const addPositionSchema = z.object({
  ticker: z
    .string()
    .min(1, "Ticker is required")
    .max(12, "Too long")
    .transform((s) => s.toUpperCase()),
  quantity: z
    .number({ invalid_type_error: "Must be a number" })
    .positive("Must be greater than 0")
    .max(1_000_000, "Max 1,000,000"),
  // WHY optional(): avgPrice is labelled "(optional)" in the UI — users adding
  // gifted shares or positions with unknown cost basis leave it blank. z.number()
  // without .optional() would reject undefined and block submit for those cases.
  avgPrice: z
    .number({ invalid_type_error: "Must be a number" })
    .nonnegative("Must be 0 or greater")
    .optional(),
});

type AddPositionFormValues = z.infer<typeof addPositionSchema>;

// ── Component ──────────────────────────────────────────────────────────────

export interface AddPositionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  portfolioId: string;
  accessToken: string | null | undefined;
  /**
   * PRD-0114 W4 (FR-8 / G-8): drives the success toast copy so MANUAL portfolio
   * users see "within seconds" (async W1 Kafka consumer path) while BROKERAGE
   * users see a generic success message.
   * WHY lowercase: PortfolioKind StrEnum serialises to lowercase ("manual", "brokerage", "root").
   * Optional — existing call sites keep working.
   */
  portfolioKind?: "manual" | "brokerage" | "root" | null;
}

export function AddPositionDialog({
  open,
  onOpenChange,
  onSuccess,
  portfolioId,
  accessToken,
  portfolioKind,
}: AddPositionDialogProps) {
  const form = useForm<AddPositionFormValues>({
    resolver: zodResolver(addPositionSchema),
    defaultValues: {
      ticker: "",
      // WHY undefined for quantity: NumberInput.value is number | null. null
      // means "empty" — RHF stores undefined; Zod's z.number() with
      // invalid_type_error surfaces "Must be a number" on submit if untouched.
      quantity: undefined as unknown as number,
      // WHY undefined for avgPrice: field is optional; onSubmit coalesces to 0.
      avgPrice: undefined,
    },
    mode: "onChange",
    // WHY onChange mode: live per-field validation as the user types catches
    // BP-328 (quantity=0) immediately rather than only on submit. This is the
    // standard UX for Bloomberg order-entry forms — errors appear as you type.
  });

  // WHY errors.root (not errors.root.serverError): `root` is RHF's canonical
  // slot for server-side errors that don't map to a specific field. Using the
  // flat `root` key (T-5-03, PLAN-0108) lets us call setError("root", …) and
  // read errors.root?.message in one place, consistent with RHF docs.
  const serverError = form.formState.errors.root?.message;

  async function onSubmit(values: AddPositionFormValues) {
    const gw = createGateway(accessToken);

    try {
      // Step 1: resolve ticker → instrument_id.
      // WHY limit=1: we only need the best match. S3's instrument search ranks
      // exact ticker matches first.
      const searchResult = await gw.searchInstruments(values.ticker, 1);
      const instrument = searchResult.results[0];

      if (!instrument) {
        form.setError("ticker", {
          message: `"${values.ticker}" not found. Check the symbol and try again.`,
        });
        return;
      }

      // Step 2: add the position via a BUY transaction.
      await gw.addPosition(
        portfolioId,
        instrument.instrument_id,
        values.quantity,
        // WHY default 0: avgPrice is optional in the schema but required by the
        // gateway call. Zod's .nonnegative() already guarantees >= 0, so NaN
        // can't reach here, but the nullish coalesce is a safety net.
        values.avgPrice ?? 0,
      );

      form.reset();

      // PRD-0114 W4 (FR-8): portfolio-kind-aware success toast.
      // "within seconds" sets the correct expectation for the async W1 consumer.
      // WHY no duration override: centralized Toaster config in app/providers.tsx
      // pins duration=4000 for all call sites (toast-config.test.ts enforces this).
      if (portfolioKind === "manual") {
        toast.success("Transaction recorded", {
          description: "Holdings will reflect this trade within seconds.",
        });
      } else {
        toast.success("Position added successfully.");
      }

      onSuccess();
    } catch (err) {
      // WHY setError("root"): surfaces the backend error inside the form itself
      // (T-5-03, PLAN-0108). A 422 from S1 (e.g. invalid instrument_id or
      // out-of-range quantity) should appear inline next to the Submit button,
      // not just in a transient toast that the user might miss.
      const message =
        err instanceof Error ? err.message : "Failed to add position.";
      form.setError("root", { message });
    }
  }

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
          <DialogTitle className="text-[11px] font-mono uppercase tracking-[0.08em]">
            Add Position
          </DialogTitle>
        </DialogHeader>

        <Form {...form}>
          <div className="space-y-4 py-2">
            {/* Ticker — the primary identifier traders use */}
            <FormField
              control={form.control}
              name="ticker"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Ticker
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. AAPL"
                      autoFocus
                      // WHY toUpperCase on change: tickers are always uppercase.
                      // Converting as-you-type avoids "aapl" failing S3 search.
                      onChange={(e) => field.onChange(e.target.value.toUpperCase())}
                      onBlur={field.onBlur}
                      value={field.value}
                      name={field.name}
                      ref={field.ref}
                      disabled={form.formState.isSubmitting}
                      className="h-8 text-[11px] font-mono bg-background border-border"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Quantity — NumberInput for shorthand parsing + BP-328 validation.
                WHY NumberInput: "1.5k" → 1500, "25%" → 0.25 (with percent=false
                here since we want literal share count). The old <Input type="number">
                had no shorthand parsing and the browser stepper widget cluttered
                the compact layout. */}
            <FormField
              control={form.control}
              name="quantity"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Quantity
                  </FormLabel>
                  <FormControl>
                    <NumberInput
                      // WHY percent=false: we want the literal share count, not
                      // a fraction. "50%" should NOT become 0.5 for a quantity field.
                      percent={false}
                      bps={false}
                      value={field.value ?? null}
                      onValueChange={(v) => {
                        // WHY trigger("quantity") after setValue: onChange mode
                        // re-validates on RHF's internal change, but NumberInput
                        // commits on blur (not onChange). We setValue + trigger
                        // to get immediate live validation as the user types shorthand.
                        field.onChange(v);
                        void form.trigger("quantity");
                      }}
                      disabled={form.formState.isSubmitting}
                      density="compact"
                      aria-label="Quantity"
                      className="w-full"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Average price — optional, 0 is allowed (BP-328: negative is not) */}
            <FormField
              control={form.control}
              name="avgPrice"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Avg Price{" "}
                    <span className="text-muted-foreground/60 normal-case">(optional)</span>
                  </FormLabel>
                  <FormControl>
                    <NumberInput
                      percent={false}
                      bps={false}
                      value={field.value ?? null}
                      onValueChange={(v) => {
                        field.onChange(v);
                        void form.trigger("avgPrice");
                      }}
                      disabled={form.formState.isSubmitting}
                      density="compact"
                      aria-label="Average price"
                      className="w-full"
                    />
                  </FormControl>
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
              // WHY disable when ticker is empty: quantity+price have defaults,
              // but a ticker-less submit always fails at the S3 search step.
              // Disable early to prevent a wasted network round-trip.
              disabled={
                form.formState.isSubmitting ||
                !form.getValues("ticker").trim()
              }
              className="text-[11px] font-mono"
            >
              {form.formState.isSubmitting ? "Adding…" : "Add Position"}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
