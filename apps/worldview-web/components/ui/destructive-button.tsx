/**
 * components/ui/destructive-button.tsx — DestructiveButton with 3-tier confirm ladder
 *
 * WHY THIS EXISTS: "Delete portfolio" buttons today fire a `window.confirm()`
 * on click — disruptive, ugly, and inconsistent with the design system. PRD-0031
 * §F-4 spec'd a 3-tier confirm pattern for destructive actions:
 *
 *   T1 (low risk)    → inline two-step confirm (button toggles to "Confirm?" then
 *                      executes on the second click). 4-second timeout reverts.
 *                      Use for: dismiss, archive, mark-read.
 *
 *   T2 (medium risk) → modal AlertDialog with "Cancel / Delete" buttons.
 *                      Use for: delete watchlist row, remove holding, cancel order.
 *
 *   T3 (high risk)   → modal AlertDialog with type-to-confirm. User must type
 *                      the resource name to enable the destructive button.
 *                      Use for: delete portfolio, delete account, wipe workspace.
 *
 * USAGE:
 *   <DestructiveButton tier="t1" onConfirm={dismiss}>Dismiss</DestructiveButton>
 *
 *   <DestructiveButton tier="t2"
 *     confirmTitle="Delete watchlist?"
 *     confirmDescription="This removes 12 instruments and cannot be undone."
 *     onConfirm={() => deleteWatchlist(id)}>
 *     Delete
 *   </DestructiveButton>
 *
 *   <DestructiveButton tier="t3"
 *     confirmTitle="Delete portfolio?"
 *     confirmDescription="All 47 transactions will be lost."
 *     typeToConfirm="My Portfolio"
 *     onConfirm={() => deletePortfolio(id)}>
 *     Delete portfolio
 *   </DestructiveButton>
 */

"use client";

import * as React from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button, type ButtonProps } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Tier = "t1" | "t2" | "t3";

interface BaseProps extends Omit<ButtonProps, "onClick" | "variant"> {
  tier: Tier;
  /** Called once the user has confirmed via the tier-appropriate path. */
  onConfirm: () => void | Promise<void>;
}

interface T1Props extends BaseProps {
  tier: "t1";
}

interface T2Props extends BaseProps {
  tier: "t2";
  confirmTitle: string;
  confirmDescription?: string;
  /** Override the confirm-button label. Default: the trigger button's children. */
  confirmLabel?: string;
}

interface T3Props extends BaseProps {
  tier: "t3";
  confirmTitle: string;
  confirmDescription?: string;
  /** The exact string the user must type to enable confirmation. */
  typeToConfirm: string;
  confirmLabel?: string;
}

export type DestructiveButtonProps = T1Props | T2Props | T3Props;

export function DestructiveButton(props: DestructiveButtonProps) {
  if (props.tier === "t1") return <T1Button {...props} />;
  if (props.tier === "t2") return <T2Button {...props} />;
  return <T3Button {...props} />;
}

// ── T1: inline two-step ──────────────────────────────────────────────────────
function T1Button({ tier: _tier, onConfirm, children, className, ...rest }: T1Props) {
  void _tier;
  const [armed, setArmed] = React.useState(false);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // mountedRef guards against `setArmed(false)` after the parent removes the
  // button mid-armed-window (e.g. parent navigates away, list re-renders).
  // Without this, React 19 logs "state update on unmounted component" in dev.
  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // WHY 4-second armed window: long enough to be deliberate, short enough to
  // prevent accidental confirmation if user wanders off and clicks back later.
  React.useEffect(() => {
    if (armed) {
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) setArmed(false);
      }, 4000);
      return () => {
        if (timerRef.current) clearTimeout(timerRef.current);
      };
    }
  }, [armed]);

  return (
    <Button
      variant="destructive"
      className={cn(armed && "ring-2 ring-destructive/40", className)}
      onClick={() => {
        if (!armed) {
          setArmed(true);
          return;
        }
        if (timerRef.current) clearTimeout(timerRef.current);
        setArmed(false);
        void onConfirm();
      }}
      // SR live announcement when the label flips to "Confirm?".
      aria-live="polite"
      {...rest}
    >
      {armed ? "Confirm?" : children}
    </Button>
  );
}

// ── T2: modal confirm ────────────────────────────────────────────────────────
function T2Button({
  tier: _tier,
  onConfirm,
  confirmTitle,
  confirmDescription,
  confirmLabel,
  children,
  className,
  ...rest
}: T2Props) {
  void _tier;
  const [open, setOpen] = React.useState(false);

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" className={className} {...rest}>
          {children}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          {/* WHY always render: Radix logs an a11y warning if no <Description> exists.
              Pass an empty visually-hidden text when no description provided so the
              dialog still announces something to screen-readers. */}
          <AlertDialogDescription className={confirmDescription ? undefined : "sr-only"}>
            {confirmDescription ?? "Destructive action — please confirm."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            onClick={() => void onConfirm()}
          >
            {confirmLabel ?? (typeof children === "string" ? children : "Confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ── T3: type-to-confirm ──────────────────────────────────────────────────────
function T3Button({
  tier: _tier,
  onConfirm,
  confirmTitle,
  confirmDescription,
  typeToConfirm,
  confirmLabel,
  children,
  className,
  ...rest
}: T3Props) {
  void _tier;
  const [open, setOpen] = React.useState(false);
  const [typed, setTyped] = React.useState("");
  // WHY .normalize("NFC"): pre-composed vs decomposed Unicode (e.g. "Café"
  // typed via macOS IME could arrive as decomposed code points) would
  // otherwise fail an exact compare frustrating legitimate users. Strict
  // case-sensitivity is preserved. No bypass risk — strictly stricter.
  const matches = typed.normalize("NFC").trim() === typeToConfirm.normalize("NFC").trim();

  // Reset typed value when the dialog closes so the next open starts fresh.
  React.useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" className={className} {...rest}>
          {children}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          {/* WHY always render: Radix logs an a11y warning if no <Description> exists.
              Pass an empty visually-hidden text when no description provided so the
              dialog still announces something to screen-readers. */}
          <AlertDialogDescription className={confirmDescription ? undefined : "sr-only"}>
            {confirmDescription ?? "Destructive action — please confirm."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="my-2 space-y-2">
          <p className="text-[11px] text-muted-foreground">
            To confirm, type{" "}
            <code className="rounded-[2px] bg-muted px-1 py-0.5 font-mono text-[11px] text-foreground">
              {typeToConfirm}
            </code>{" "}
            below.
          </p>
          <Input
            density="compact"
            autoFocus
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={typeToConfirm}
            aria-label="Type to confirm"
            aria-describedby="t3-match-status"
          />
          {/* SR live announcement when match state flips */}
          <span id="t3-match-status" role="status" aria-live="polite" className="sr-only">
            {matches ? "Confirmation matches — destructive action enabled." : ""}
          </span>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))]"
            disabled={!matches}
            onClick={() => matches && void onConfirm()}
          >
            {confirmLabel ?? (typeof children === "string" ? children : "Confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
