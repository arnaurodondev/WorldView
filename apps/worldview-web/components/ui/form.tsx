/**
 * components/ui/form.tsx — React Hook Form + shadcn/ui bridge
 *
 * WHY THIS EXISTS: Finance forms (portfolio creation, position entry, trade
 * tickets) have strict validation requirements that go beyond what raw HTML5
 * `required` / `min` / `pattern` provides. React Hook Form (RHF) gives us:
 *   - Per-field error tracking without re-rendering the whole form
 *   - Zod schema integration via @hookform/resolvers for type-safe validation
 *   - Uncontrolled inputs (avoids keystroke re-renders in large forms)
 *
 * This file is the shadcn/ui form glue layer: it wires RHF's Controller/
 * FormProvider to our design system's Label, Input, and error display.
 * Consumers only need to import from here — they never touch RHF directly.
 *
 * WHO USES IT: Any dialog or form that validates user input before mutating
 * S1/S9 data (CreatePortfolioDialog, AddPositionDialog, CreateWatchlistDialog,
 * future trade-ticket slide-in).
 *
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

"use client"; // WHY: uses React.createContext + hooks (FormItemContext, FormFieldContext)

import * as React from "react";
import {
  Controller,
  FormProvider,
  useFormContext,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
} from "react-hook-form";
import { Slot } from "@radix-ui/react-slot";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// ── Re-export FormProvider as "Form" ─────────────────────────────────────────
// WHY re-export: consumers shouldn't need to know about FormProvider's import
// path or that it's from react-hook-form. A single `@/components/ui/form`
// import surface keeps form code tidy.
const Form = FormProvider;

// ── FormField — Controller wrapper with context ───────────────────────────────
// WHY context: FormItem's Label + FormMessage need the field NAME and ERROR
// but live deep in the JSX tree without a direct prop path. Context lets them
// reach up without prop drilling.
interface FormFieldContextValue<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> {
  name: TName;
}

const FormFieldContext = React.createContext<FormFieldContextValue>(
  {} as FormFieldContextValue,
);

function FormField<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>({ ...props }: ControllerProps<TFieldValues, TName>) {
  return (
    <FormFieldContext.Provider value={{ name: props.name }}>
      <Controller {...props} />
    </FormFieldContext.Provider>
  );
}

// ── FormItem — container with auto-generated id ────────────────────────────
// WHY id generation: FormLabel and FormMessage need matching htmlFor / id
// attributes so screen readers associate the label and error with the input.
// Generating the id here once (inside FormItem) avoids mismatches when the
// same form is mounted multiple times (e.g. two add-position dialogs).
interface FormItemContextValue {
  id: string;
}

const FormItemContext = React.createContext<FormItemContextValue>(
  {} as FormItemContextValue,
);

const FormItem = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  // WHY useId: React 18's useId generates stable IDs per component instance
  // without needing a counter or random value. SSR-safe.
  const id = React.useId();
  return (
    <FormItemContext.Provider value={{ id }}>
      <div ref={ref} className={cn("space-y-1.5", className)} {...props} />
    </FormItemContext.Provider>
  );
});
FormItem.displayName = "FormItem";

// ── useFormField — internal hook used by FormLabel, FormControl, FormMessage ─
// WHY centralise state reads: the three leaf components (Label, Control,
// Message) all need the same field state (name, error, id). One hook prevents
// each from independently calling useFormContext() and diverging.
function useFormField() {
  const fieldContext = React.useContext(FormFieldContext);
  const itemContext = React.useContext(FormItemContext);
  const { getFieldState, formState } = useFormContext();

  const fieldState = getFieldState(fieldContext.name, formState);

  if (!fieldContext) {
    throw new Error("useFormField must be used within <FormField>");
  }

  const { id } = itemContext;

  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-form-item`,
    formDescriptionId: `${id}-form-item-description`,
    formMessageId: `${id}-form-item-message`,
    ...fieldState,
  };
}

// ── FormLabel — Label that turns red when the field has an error ──────────────
// WHY visual error state on the label: finance users scan quickly. A red label
// instantly tells them "this field is wrong" before they even read the message.
const FormLabel = React.forwardRef<
  React.ElementRef<typeof Label>,
  React.ComponentPropsWithoutRef<typeof Label>
>(({ className, ...props }, ref) => {
  const { error, formItemId } = useFormField();

  return (
    <Label
      ref={ref}
      // WHY text-destructive when error: maps to our Midnight Pro `--destructive`
      // token (#EF5350 red) so error state is visually consistent across the app.
      className={cn(error && "text-destructive", className)}
      htmlFor={formItemId}
      {...props}
    />
  );
});
FormLabel.displayName = "FormLabel";

// ── FormControl — Slot that wires aria-invalid + aria-describedby ────────────
// WHY Slot: wraps whatever input the consumer passes (Input, Select, NumberInput,
// Checkbox, Switch) without adding an extra DOM element. Slot merges its own
// props (aria-invalid, aria-describedby) with the child's props.
//
// WHY aria-invalid: required by WCAG 4.1.3 — screen readers need this flag to
// announce "this field has an error". Without it, the FormMessage text exists
// in the DOM but isn't associated with the input.
//
// WHY aria-describedby pointing to formDescriptionId + formMessageId: lets the
// screen reader read both the helper text AND the error message when the input
// is focused.
const FormControl = React.forwardRef<
  React.ElementRef<typeof Slot>,
  React.ComponentPropsWithoutRef<typeof Slot>
>(({ ...props }, ref) => {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField();

  return (
    <Slot
      ref={ref}
      id={formItemId}
      aria-describedby={
        !error
          ? `${formDescriptionId}`
          : `${formDescriptionId} ${formMessageId}`
      }
      aria-invalid={error ? "true" : undefined}
      {...props}
    />
  );
});
FormControl.displayName = "FormControl";

// ── FormDescription — muted helper text below the input ──────────────────────
// WHY a separate description component (not just a <p>): gives us the stable
// id that FormControl's aria-describedby points to. The description is always
// in the DOM (even when empty) so aria-describedby stays valid.
const FormDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => {
  const { formDescriptionId } = useFormField();

  return (
    <p
      ref={ref}
      id={formDescriptionId}
      className={cn("text-[10px] text-muted-foreground", className)}
      {...props}
    />
  );
});
FormDescription.displayName = "FormDescription";

// ── FormMessage — per-field error text ───────────────────────────────────────
// WHY role="alert": WCAG 1.3.3 — error messages that appear after user
// interaction must be announced by screen readers. role="alert" triggers an
// aria-live="assertive" announcement without requiring the element to have
// focus. The finance user doesn't miss the error even if they've tabbed away.
//
// WHY id tied to formMessageId: matches the aria-describedby wired in
// FormControl, so the relationship between input and its error is explicit in
// the accessibility tree.
const FormMessage = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, children, ...props }, ref) => {
  const { error, formMessageId } = useFormField();
  const body = error ? String(error?.message) : children;

  // WHY always render (even when empty): FormControl wires aria-describedby to
  // formMessageId. If this element is absent from the DOM, the reference is
  // dangling — technically invalid per ARIA spec. We keep it rendered but
  // aria-hidden + visually hidden so it occupies no space and is inert to AT.
  return (
    <p
      ref={ref}
      id={formMessageId}
      role="alert"
      aria-hidden={!body}
      className={cn(
        "text-[11px] font-mono",
        error ? "text-destructive" : "text-muted-foreground",
        !body && "hidden",
        className,
      )}
      {...props}
    >
      {body ?? ""}
    </p>
  );
});
FormMessage.displayName = "FormMessage";

export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
};
