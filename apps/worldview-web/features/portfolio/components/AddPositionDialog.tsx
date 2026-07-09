"use client"; // WHY: useForm + useMutation + useQuery require browser-side state and event handlers

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
 * PLAN-0122 W-C (§6.3) upgrades this dialog with two casual-user unlocks:
 *   1. A TRADE-DATE picker (R-11) so a manual buy can be back-dated to the day it
 *      actually happened — the gateway already accepts `executed_at`, this was a
 *      pure frontend omission.
 *   2. An inline DEBOUNCED TICKER TYPEAHEAD (R-12) over the existing
 *      `searchInstruments` endpoint so the user gets a dropdown of matches as they
 *      type (instead of the old cold 2–4 s submit-time-only resolution). Picking a
 *      row stashes the resolved `instrument_id` so submit skips the redundant
 *      search; typing a ticker without picking still resolves at submit (the
 *      original behaviour is preserved as a fallback — R-14).
 *
 * TICKER RESOLUTION FLOW:
 *   1. User types a ticker (e.g. "AAPL") → debounced dropdown of matches appears.
 *   2a. User PICKS a row → instrument_id is stashed, submit skips the search.
 *   2b. User does NOT pick → submit resolves via searchInstruments("AAPL", 1).
 *   3. Zod validates ticker + quantity + tradeDate before the network round-trip.
 *   4. addPosition(portfolioId, instrument_id, qty, price, tradeDate) → POST /v1/transactions.
 *   5. onSuccess() → parent invalidates ["holdings", portfolioId].
 *
 * DATA SOURCE: S9 → S3 (instrument search, public), S9 → S1 (transaction POST).
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useDebounce } from "@/hooks/useDebounce";
import type { SearchResult } from "@/types/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { NumberInput } from "@/components/ui/number-input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Command,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";

// ── Local-date helper ────────────────────────────────────────────────────────

/**
 * localTodayStr — today's date as `YYYY-MM-DD` in the USER'S LOCAL timezone.
 *
 * WHY not new Date().toISOString().slice(0,10): toISOString() is UTC, so a user
 * in UTC-5 late in the evening would get *tomorrow's* date. Building the string
 * from local date parts (the same builder ClosePositionDialog uses) keeps the
 * default trade date aligned with the calendar day the user actually sees.
 * WHY a function (not a module const): computing it fresh at each validation /
 * default-value read means the dialog is correct even across a midnight rollover.
 */
function localTodayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

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
 *
 * WHY the tradeDate refine (PLAN-0122 R-11): you cannot have bought shares in the
 * future. We compare the `YYYY-MM-DD` strings lexicographically — for zero-padded
 * ISO dates this is equivalent to a chronological comparison, so no Date parsing
 * is needed. The check runs against localTodayStr() at validation time so it
 * stays correct across a midnight rollover.
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
  tradeDate: z
    .string()
    .min(1, "Trade date is required")
    .refine((d) => d <= localTodayStr(), {
      message: "Trade date can't be in the future.",
    }),
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
      // WHY default today: most manual adds are same-day; defaulting to today keeps
      // the common case one field the user never has to touch (PLAN-0122 R-11).
      tradeDate: localTodayStr(),
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

  // ── Ticker typeahead state (PLAN-0122 §6.3, R-12) ────────────────────────
  //
  // WHY a stashed instrument_id: when the user PICKS a dropdown row we already
  // know its instrument_id, so submit can skip the redundant searchInstruments
  // round-trip. When the user types a ticker and submits without picking, this
  // stays null and submit falls back to the submit-time resolve (R-14).
  const [resolvedInstrumentId, setResolvedInstrumentId] = useState<string | null>(null);
  // WHY a separate open flag: we only want the dropdown visible while the user is
  // actively searching (after typing, before picking). Picking a row closes it.
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Live ticker text drives the debounced query. We read it from RHF (the single
  // source of truth) so the input and the query never drift apart.
  const tickerValue = form.watch("ticker");
  // WHY 250 ms: the CommandPalette / GlobalSearch convention (DS §6.15). S3's
  // instrument search is a cold ILIKE (2–4 s worst case); debouncing to 250 ms
  // means one request fires per typing pause instead of one per keystroke, and
  // the shared TanStack cache key below reuses GlobalSearch's cached results.
  const debouncedTicker = useDebounce(tickerValue, 250);

  const { data: searchData, isFetching: isSearching } = useQuery({
    // WHY this exact key: shared with GlobalSearch/CommandPalette
    // (["instrument-search", q]) so a query the user already ran elsewhere is
    // served from cache — no duplicate network call.
    queryKey: ["instrument-search", debouncedTicker],
    queryFn: () => createGateway(accessToken).searchInstruments(debouncedTicker, 8),
    // WHY enabled guards:
    //   - length >= 1: ticker prefixes are short ("V", "F") so 1 char is useful,
    //     and we never fire a search on an empty box.
    //   - dropdownOpen: don't keep re-searching after the user has picked/closed.
    //   - resolvedInstrumentId === null: once a row is picked we already have the
    //     id, so there is nothing left to search for.
    enabled:
      debouncedTicker.trim().length >= 1 &&
      dropdownOpen &&
      resolvedInstrumentId === null,
    // Search results are stable for a short window; cache avoids re-fetching the
    // same prefix while the user pauses.
    staleTime: 30_000,
  });

  const results: SearchResult[] = searchData?.results ?? [];

  /**
   * handlePickInstrument — the user selected a dropdown row.
   *
   * Sets the ticker field to the canonical symbol and STASHES the resolved
   * instrument_id so submit skips the redundant search, then closes the dropdown.
   * WHY shouldValidate: filling the ticker programmatically must re-run Zod so the
   * submit button's enabled state reflects the new (valid) ticker immediately.
   */
  function handlePickInstrument(result: SearchResult) {
    form.setValue("ticker", result.ticker, { shouldValidate: true });
    setResolvedInstrumentId(result.instrument_id);
    setDropdownOpen(false);
  }

  async function onSubmit(values: AddPositionFormValues) {
    const gw = createGateway(accessToken);

    try {
      // Step 1: resolve ticker → instrument_id.
      // WHY prefer the stashed id: if the user picked a dropdown row we already
      // resolved the instrument during the typeahead — reusing it skips a second
      // (cold) search round-trip. Only when no row was picked do we fall back to
      // the submit-time resolve, so behaviour never regresses (PLAN-0122 R-14).
      let instrumentId = resolvedInstrumentId;

      if (!instrumentId) {
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
        instrumentId = instrument.instrument_id;
      }

      // Step 2: add the position via a BUY transaction, back-dated to the chosen
      // trade date. WHY `${tradeDate}T00:00:00Z`: S1 expects a datetime, not a bare
      // date; the transaction-date filter casts executed_at to a DATE so the time
      // component is not meaningful for manual entries (same convention as Close).
      await gw.addPosition(
        portfolioId,
        instrumentId,
        values.quantity,
        // WHY default 0: avgPrice is optional in the schema but required by the
        // gateway call. Zod's .nonnegative() already guarantees >= 0, so NaN
        // can't reach here, but the nullish coalesce is a safety net.
        values.avgPrice ?? 0,
        `${values.tradeDate}T00:00:00Z`,
      );

      form.reset();
      setResolvedInstrumentId(null);
      setDropdownOpen(false);

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
      // Reset the typeahead so the next open starts clean (no stale pick/dropdown).
      setResolvedInstrumentId(null);
      setDropdownOpen(false);
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
            {/* Ticker — debounced typeahead over the existing searchInstruments
                endpoint (PLAN-0122 §6.3, R-12). We keep the RHF `ticker` field as
                the single source of truth and drive a cmdk Command combobox from it. */}
            <FormField
              control={form.control}
              name="ticker"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Ticker
                  </FormLabel>
                  <FormControl>
                    {/* WHY relative wrapper: the results dropdown is absolutely
                        positioned under the input so it overlays the form without
                        pushing the other fields down as matches stream in. */}
                    <div className="relative">
                      {/* WHY shouldFilter={false}: we filter SERVER-SIDE via
                          searchInstruments; leaving cmdk's fuzzy filter on would
                          re-filter our already-filtered rows against their `value`
                          strings and hide everything the moment the user types
                          (the same trap GlobalSearch avoids). DS §6.15. */}
                      <Command
                        shouldFilter={false}
                        className="overflow-visible bg-transparent"
                      >
                        <CommandInput
                          // WHY value={field.value}: controlled by RHF so the input
                          // and the debounced query never drift.
                          value={field.value}
                          onValueChange={(v) => {
                            // WHY toUpperCase: tickers are always uppercase; converting
                            // as-you-type avoids "aapl" failing S3 search.
                            field.onChange(v.toUpperCase());
                            // WHY clear the stash on every keystroke: any manual edit
                            // invalidates a previously-picked instrument_id, so submit
                            // must re-resolve. (Picking a row goes through
                            // handlePickInstrument, which does NOT fire onValueChange,
                            // so the stash it sets survives.) This is the SEARCH-001 /
                            // label-vs-lookup guard: never post a stale instrument_id.
                            setResolvedInstrumentId(null);
                            setDropdownOpen(true);
                          }}
                          // WHY reopen on focus: lets the user re-open the dropdown
                          // after an accidental close without retyping.
                          onFocus={() => setDropdownOpen(true)}
                          placeholder="Search ticker or company… e.g. AAPL"
                          autoFocus
                          disabled={form.formState.isSubmitting}
                          className="h-8 text-[11px] font-mono"
                        />

                        {/* Dropdown — only while actively searching an un-picked
                            ticker. Once a row is picked (resolvedInstrumentId set),
                            or the box is empty, it collapses. */}
                        {dropdownOpen &&
                          field.value.trim().length >= 1 &&
                          resolvedInstrumentId === null && (
                            <div className="absolute left-0 top-full z-50 mt-1 w-full rounded-[2px] border border-border bg-popover shadow-lg">
                              <CommandList>
                                {/* Loading — a skeleton row communicates the cold
                                    ILIKE latency instead of a blank flash. */}
                                {isSearching && (
                                  <div className="space-y-1 p-2">
                                    <Skeleton className="h-5 w-full" />
                                    <Skeleton className="h-5 w-full" />
                                  </div>
                                )}

                                {/* Empty — muted "no match" message (no crash). */}
                                {!isSearching && results.length === 0 && (
                                  <p className="p-2 font-mono text-[10px] text-muted-foreground">
                                    No instruments match &quot;{field.value}&quot;.
                                  </p>
                                )}

                                {/* Matches — keyboard-navigable (↑/↓/Enter via cmdk)
                                    AND mouse-selectable. WHY both onSelect + onClick:
                                    cmdk's onSelect fires on keyboard Enter when the row
                                    is highlighted; onClick fires on mouse click, which
                                    onSelect does not always cover — wiring both makes
                                    selection work in every interaction mode
                                    (SEARCH-001 dual-handler rule, DS §6.15). */}
                                {!isSearching &&
                                  results.map((result) => (
                                    <CommandItem
                                      key={result.instrument_id}
                                      // WHY value={ticker}: cmdk uses `value` for
                                      // keyboard-highlight matching.
                                      value={result.ticker}
                                      onSelect={() => handlePickInstrument(result)}
                                      onClick={() => handlePickInstrument(result)}
                                      className="cursor-pointer text-[11px] font-mono"
                                    >
                                      <span className="text-primary">{result.ticker}</span>
                                      <span className="ml-2 min-w-0 flex-1 truncate text-foreground/70">
                                        {result.name}
                                      </span>
                                    </CommandItem>
                                  ))}
                              </CommandList>
                            </div>
                          )}
                      </Command>
                    </div>
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

            {/* Trade Date — PLAN-0122 §6.3 (R-11). Native date input (same chrome as
                ClosePositionDialog's date field); default today, cannot be future. */}
            <FormField
              control={form.control}
              name="tradeDate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    Trade Date
                  </FormLabel>
                  <FormControl>
                    <input
                      type="date"
                      value={field.value}
                      onChange={(e) => {
                        field.onChange(e.target.value);
                        // Re-validate immediately so a future date surfaces its error
                        // (and disables submit) as soon as it is picked.
                        void form.trigger("tradeDate");
                      }}
                      onBlur={field.onBlur}
                      name={field.name}
                      ref={field.ref}
                      // WHY max={today}: the native picker greys out future days as a
                      // first line of defence; the Zod refine is the authoritative guard.
                      max={localTodayStr()}
                      disabled={form.formState.isSubmitting}
                      aria-label="Trade date"
                      className="h-7 w-full rounded-[2px] border border-border bg-background px-2 font-mono text-[12px] text-foreground"
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
