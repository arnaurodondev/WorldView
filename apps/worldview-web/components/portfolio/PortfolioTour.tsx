/**
 * components/portfolio/PortfolioTour.tsx — dismissible, non-blocking onboarding
 * tour (PLAN-0122 W-F, PRD-0122 §6.8).
 *
 * WHY THIS EXISTS: a first-time user who just created their first portfolio needs
 * a 20-second orientation — where to add a position, how to switch to the full
 * analytics layout, that a brokerage connects read-only. This is that guided tour.
 *
 * WHY CUSTOM (not react-joyride / shepherd.js): the design system mandates
 * shadcn/ui-only components and `pnpm audit` 0 CVEs with exact versions (PRD §7).
 * A five-step popover tour does not justify a new dependency + its transitive CVE
 * surface, so we build a tiny state machine over the shadcn `Popover` (Radix). No
 * package.json change.
 *
 * WHY A RADIX POPOVER WITH A VIRTUAL-ISH ANCHOR: each step points at an existing
 * element tagged `data-tour-target="…"` (mode toggle, Add Position button, column
 * toggle — added across W-A/W-C/W-E/W-F). There is no trigger button; instead we
 * measure the target's bounding rect and render a zero-size `PopoverAnchor` at
 * that position, so Radix positions the step popover beside the real element.
 *
 * NON-BLOCKING (R-30): the Popover is opened with `modal={false}` — Radix then
 * does NOT trap focus and does NOT block clicks outside the popover, so the user
 * can keep using the page while the tour is visible. It is a guide layer, never a
 * gate.
 *
 * DISMISSIBLE (R-31): ×, "Skip tour", Escape, or an outside click each end the
 * tour and set the persisted flag to "done" so it never re-shows. The flag is set
 * to "done" the MOMENT the tour starts (not on completion) so an abandoned tour is
 * never re-triggered.
 *
 * TRIGGER (R-28): `CreatePortfolioDialog` writes the flag "pending" on a user's
 * first-ever portfolio create. On the next /portfolio render this component reads
 * "pending" in an effect and auto-starts. Users who already had a portfolio before
 * the feature shipped are BACKFILLED to "done" on first mount (never surprised).
 *
 * SSR-SAFETY: client-only ("use client"); localStorage + querySelector are touched
 * only inside effects, never during render.
 *
 * A11Y — KEYBOARD FOCUS-STEPPING (W-F deferred item): because the tour is
 * non-blocking (`modal={false}` + `onOpenAutoFocus` prevented so we never yank
 * focus on open), Radix places NO focus inside the popover. That left a keyboard
 * user unable to conveniently reach Next / Back / Skip. FIX: on each rendered
 * step we move focus to the primary advance button ("Next", or "Done" on the last
 * step) via a ref, so the user can press Enter to advance and Tab to Back/Skip.
 * This is deliberately NOT a focus trap — we do a one-shot `.focus({preventScroll})`
 * (preventScroll so it never scroll-jumps or fights the anchor positioning); the
 * page stays fully interactive and Escape/Skip/× still dismiss. Focus lands on the
 * step that actually renders, including after a missing-anchor self-skip, because
 * the focus effect keys off the resolved `stepIndex` (a "previous step" ref
 * tracks the last-focused step so we move focus only on a REAL step change).
 *
 * A11Y — NO FOCUS-STEAL ON SCROLL/RESIZE (Defect 1): the per-step focus effect
 * MUST NOT depend on `rect`. `rect` is re-set on every scroll/resize by the reflow
 * listener, so depending on it would re-run the focus effect and yank focus back
 * to the advance button — stealing it from wherever the user moved it (this is a
 * non-modal popover). The effect therefore keys strictly off `stepIndex`.
 *
 * A11Y — FOCUS RESTORE ON CLOSE (Defect 2): there is no `Popover.Trigger` (the
 * anchor is an aria-hidden, pointerEvents:none div), so on dismiss Radix would
 * drop focus to <body>. We capture `document.activeElement` at open time and
 * restore it in `onCloseAutoFocus` (falling back to a stable page control if the
 * prior element was unmounted), keeping the keyboard user oriented.
 */

"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";

// ── Persisted-flag contract ──────────────────────────────────────────────────

/**
 * localStorage key for the tour lifecycle. Versioned (`:v1`) like the repo's
 * other `worldview:*:vN` keys so a future shape change can migrate cleanly.
 * Exported so CreatePortfolioDialog writes the SAME key (single source of truth).
 */
export const PORTFOLIO_TOUR_SEEN_KEY = "worldview:portfolioTourSeen:v1";

/** The three lifecycle states. "pending" = queued to auto-start on next render;
 *  "done" = shown or dismissed or backfilled → never show again. */
export type TourFlag = "pending" | "done";

/**
 * markTourPending — set the flag to "pending" ONLY if it is currently unset.
 * Called from the create-portfolio success path so only a user's FIRST-EVER
 * portfolio create queues the tour (R-28). A no-op if the key already exists.
 */
export function markTourPending(): void {
  try {
    if (window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY) == null) {
      window.localStorage.setItem(PORTFOLIO_TOUR_SEEN_KEY, "pending");
    }
  } catch {
    // Best-effort — a storage failure must not break portfolio creation.
  }
}

// ── Step model ───────────────────────────────────────────────────────────────

interface TourStep {
  /** Stable id (used as the React key + in tests). */
  id: string;
  /** `data-tour-target` value to anchor to. `null` → skipped if absent. */
  target: string;
  /** Popover heading (≤ short). */
  title: string;
  /** Body copy (≤ 2 sentences per PRD §6.8). */
  body: string;
}

/**
 * The ≤5 steps (PRD §6.8). Order matters — the state machine walks the array.
 * `add-position` and `column-toggle` may be ABSENT for a given render (root
 * portfolio hides Add Position; Simple hides the column toggle) — a missing
 * anchor makes the step self-skip (see `resolveFrom`).
 */
const STEPS: readonly TourStep[] = [
  {
    id: "welcome",
    target: "portfolio-header",
    title: "Welcome to your portfolio",
    body: "This is your portfolio. Here's a 20-second tour of the essentials.",
  },
  {
    id: "detail-level",
    target: "mode-toggle",
    title: "Choose your detail level",
    body: "Start in Simple for a clean overview; switch to Advanced any time for the full analytics layout.",
  },
  {
    id: "add-position",
    target: "add-position",
    title: "Add a position",
    body: "Add holdings manually here — search a ticker and set the date you actually bought.",
  },
  {
    id: "connect-brokerage",
    target: "portfolio-header",
    title: "Or connect a brokerage",
    body: "Connect a brokerage to import automatically — it's read-only and your credentials stay with SnapTrade, never Worldview.",
  },
  {
    id: "advanced-columns",
    target: "column-toggle",
    title: "Tune your columns",
    body: "In Advanced, show or hide table columns to match how you work.",
  },
];

// ── Anchor rect resolution ───────────────────────────────────────────────────

/** A measured target: its viewport rect, or `null` when the anchor is absent. */
type Rect = { top: number; left: number; width: number; height: number } | null;

/** Read the current bounding rect of the element tagged `data-tour-target=value`.
 *  Returns null when no such element is in the DOM (→ the step is skipped). */
function measure(target: string): Rect {
  if (typeof document === "undefined") return null;
  const el = document.querySelector<HTMLElement>(`[data-tour-target="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

// ── Component ────────────────────────────────────────────────────────────────

export interface PortfolioTourProps {
  /**
   * Whether the user currently has ≥1 portfolio. Drives the BACKFILL: an existing
   * user whose flag is still unset (they created a portfolio before this feature)
   * is marked "done" on mount so the tour never surprises them (R-28 / OQ-4).
   */
  hasExistingPortfolio: boolean;
  /**
   * Test seam ONLY: force the tour to start active on mount regardless of the
   * flag. Never set in production. Lets the component be unit-tested without
   * poking localStorage timing.
   */
  forceOpenForTest?: boolean;
}

export function PortfolioTour({ hasExistingPortfolio, forceOpenForTest = false }: PortfolioTourProps) {
  // Whether the tour is currently running, and which step is showing.
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  // The measured rect for the active step's anchor (drives popover position).
  const [rect, setRect] = useState<Rect>(null);
  // Guard so the auto-start / backfill effect runs its decision exactly once.
  const decidedRef = useRef(false);
  // Ref to the primary advance button ("Next"/"Done") so we can move keyboard
  // focus to it on each step (A11Y focus-stepping — see file header).
  const advanceButtonRef = useRef<HTMLButtonElement>(null);
  // Ref holding the element that had focus at the MOMENT the tour opened, so we
  // can hand focus back to it on close. WHY: the tour has no `Popover.Trigger`
  // (its anchor is an aria-hidden, pointerEvents:none div), so when the advance
  // button unmounts on dismiss Radix has nothing to return focus to and drops it
  // to <body> — a keyboard/AT user loses their place. We restore it ourselves in
  // `onCloseAutoFocus` (Defect 2). Captured once, in `onOpenAutoFocus`.
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const totalSteps = STEPS.length;

  // ── Flag lifecycle: persist "done" ─────────────────────────────────────────
  const markDone = useCallback(() => {
    try {
      window.localStorage.setItem(PORTFOLIO_TOUR_SEEN_KEY, "done");
    } catch {
      // Best-effort — dismissal still works in-memory even if storage throws.
    }
  }, []);

  // ── Auto-start / backfill decision (runs once, in an effect) ────────────────
  // WHY in an effect (not render): reads localStorage, which is client-only.
  useEffect(() => {
    if (decidedRef.current) return;
    decidedRef.current = true;

    if (forceOpenForTest) {
      // Test seam: start immediately and pin the flag "done" (matches prod: the
      // flag is set the moment the tour STARTS, never on completion).
      markDone();
      setActive(true);
      setStepIndex(0);
      return;
    }

    let flag: string | null = null;
    try {
      flag = window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY);
    } catch {
      flag = null;
    }

    if (flag === "pending") {
      // A first-ever portfolio was just created → run the tour once, and set the
      // flag "done" NOW so an abandoned tour never re-triggers (PRD §11 / OQ-4).
      markDone();
      setActive(true);
      setStepIndex(0);
    } else if (flag == null && hasExistingPortfolio) {
      // BACKFILL: an existing user with no flag yet — mark done so they never see
      // a tour they didn't ask for. (New users hit the "pending" branch above.)
      markDone();
    }
    // flag === "done" → nothing to do.
  }, [forceOpenForTest, hasExistingPortfolio, markDone]);

  // ── End the tour (shared by ×, Skip, Escape, outside-click) ─────────────────
  const endTour = useCallback(() => {
    setActive(false);
    markDone();
  }, [markDone]);

  // ── Resolve the next renderable step starting at `from` ─────────────────────
  // Skips any step whose anchor is absent (e.g. column-toggle in Simple, or Add
  // Position on a root portfolio). Returns the resolved index + rect, or null
  // when no further step has a live anchor → the tour ends.
  const resolveFrom = useCallback(
    (from: number): { index: number; rect: NonNullable<Rect> } | null => {
      for (let i = from; i < totalSteps; i += 1) {
        const r = measure(STEPS[i].target);
        if (r) return { index: i, rect: r };
      }
      return null;
    },
    [totalSteps],
  );

  // ── When active, resolve the current step's anchor (layout effect so we read
  //    the rect after the DOM is painted). If the current step's anchor is
  //    missing, skip forward; if none remain, end the tour. ───────────────────
  useLayoutEffect(() => {
    if (!active) return;
    const resolved = resolveFrom(stepIndex);
    if (!resolved) {
      // No live anchor at or after this step → nothing to point at; end cleanly.
      endTour();
      return;
    }
    if (resolved.index !== stepIndex) {
      // The requested step had no anchor; jump to the next one that does.
      setStepIndex(resolved.index);
      return;
    }
    setRect(resolved.rect);
  }, [active, stepIndex, resolveFrom, endTour]);

  // ── Move keyboard focus to the advance button on each rendered STEP ─────────
  // WHY: with modal={false} + onOpenAutoFocus prevented, Radix places no focus in
  // the popover, so a keyboard user couldn't reach the controls. We focus the
  // primary advance button ("Next"/"Done") so Enter advances and Tab reaches
  // Back/Skip. preventScroll avoids scroll-jump / fighting the anchor. This is a
  // one-shot focus move, NOT a trap: the page stays interactive.
  //
  // Two hooks, because the timing differs:
  //   • INITIAL step — handled in `onOpenAutoFocus` below (fires right after Radix
  //     mounts the portaled content, when the ref is attached). An effect here
  //     would run before the portal content commits and miss the ref.
  //   • SUBSEQUENT steps — this effect. The advance button's DOM node is REUSED
  //     across steps (only its label flips Next→Done), so the ref is already
  //     attached; re-focusing on each real `stepIndex` change (incl. after a
  //     missing-anchor self-skip, which lands via the resolved `stepIndex`) keeps
  //     focus on the live step.
  //
  // DEFECT 1 FIX — deps are `[active, stepIndex]`, NOT `[active, rect, stepIndex]`.
  // WHY THE DEPS MATTER: `rect` is re-set on EVERY scroll/resize by the reflow
  // listener below (`setRect(measure())` allocates a fresh object each time). If
  // `rect` were a dependency, this effect would re-run on every scroll/resize and
  // YANK focus back to the advance button — stealing it from wherever the user
  // (this is a NON-modal popover) had moved it, e.g. a page input they were
  // typing in. That is a WCAG focus-on-scroll violation and breaks the
  // non-blocking contract. Keying strictly off `stepIndex` means reflow-driven
  // `rect` churn can never re-focus; only a genuine step change does.
  //
  // `focusedStepRef` records the step we last moved focus to (set here AND in
  // `onOpenAutoFocus` for the initial step). It guards against double-firing:
  // when this effect happens to run for the initial step (active flips true,
  // stepIndex 0) it's a no-op because onOpenAutoFocus already focused + recorded
  // step 0. It only acts when `stepIndex` differs from the step we last focused.
  const didInitialFocusRef = useRef(false);
  const focusedStepRef = useRef<number | null>(null);
  useEffect(() => {
    if (!active) {
      // Reset when the tour closes so the next open re-arms both the
      // initial-focus path and the per-step focus tracking.
      didInitialFocusRef.current = false;
      focusedStepRef.current = null;
      return;
    }
    // Initial focus is performed in `onOpenAutoFocus` (fires when Radix mounts the
    // portaled content, guaranteeing the button ref is attached). Until that has
    // happened, do nothing here — the button may not even be rendered yet.
    if (!didInitialFocusRef.current) return;
    // Only move focus when the STEP actually changed since we last focused. This
    // is what makes reflow-driven re-renders (which never change `stepIndex`)
    // no-ops even though the component re-rendered with a new `rect`.
    if (focusedStepRef.current === stepIndex) return;
    focusedStepRef.current = stepIndex;
    advanceButtonRef.current?.focus({ preventScroll: true });
  }, [active, stepIndex]);

  // ── Keep the popover glued to its anchor on scroll / resize ─────────────────
  useEffect(() => {
    if (!active) return;
    const reflow = () => {
      const r = measure(STEPS[stepIndex]?.target ?? "");
      if (r) setRect(r);
    };
    window.addEventListener("resize", reflow);
    window.addEventListener("scroll", reflow, true);
    return () => {
      window.removeEventListener("resize", reflow);
      window.removeEventListener("scroll", reflow, true);
    };
  }, [active, stepIndex]);

  // ── Advance to the next renderable step, or finish on the last ──────────────
  const handleNext = useCallback(() => {
    const resolved = resolveFrom(stepIndex + 1);
    if (!resolved) {
      // No further live step → this was the last → complete the tour.
      endTour();
      return;
    }
    setStepIndex(resolved.index);
  }, [stepIndex, resolveFrom, endTour]);

  // ── Go back to the previous renderable step (no-op at the first) ────────────
  const handleBack = useCallback(() => {
    for (let i = stepIndex - 1; i >= 0; i -= 1) {
      if (measure(STEPS[i].target)) {
        setStepIndex(i);
        return;
      }
    }
    // Already at the first live step — do nothing.
  }, [stepIndex]);

  // Is there any renderable step AFTER the current one? Drives Next-vs-Done copy.
  const isLastStep = useMemo(() => {
    if (!active) return false;
    return resolveFrom(stepIndex + 1) == null;
  }, [active, stepIndex, resolveFrom]);

  // Nothing to render unless active AND we have a measured anchor.
  if (!active || !rect) return null;

  const step = STEPS[stepIndex];

  return (
    <Popover
      open
      // WHY modal={false}: non-blocking (R-30). Radix skips the focus trap and
      // the outside-click SCRIM, so the page stays fully interactive under the
      // tour. onOpenChange(false) still fires on Escape / outside-click → dismiss.
      modal={false}
      onOpenChange={(next) => {
        // Any close intent (Escape, outside click) ends the tour + flags "done".
        if (!next) endTour();
      }}
    >
      {/* Zero-size anchor pinned at the target's viewport rect. Radix positions
          the step popover beside THIS, so it visually points at the real element
          without us re-implementing collision handling. `fixed` matches the
          viewport-relative getBoundingClientRect coordinates. */}
      <PopoverAnchor asChild>
        <div
          aria-hidden
          style={{
            position: "fixed",
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
            // Non-interactive: the anchor must never eat clicks meant for the
            // real element beneath it (non-blocking, R-30).
            pointerEvents: "none",
          }}
        />
      </PopoverAnchor>

      <PopoverContent
        align="start"
        sideOffset={8}
        // data-testid + role so the e2e/onboarding specs can find the tour.
        data-testid="portfolio-tour"
        data-tour-step={step.id}
        role="dialog"
        aria-label={`Onboarding tour — ${step.title}`}
        className="w-72 p-3"
        // WHY onOpenAutoFocus preventDefault: stop Radix's default FocusScope
        // auto-focus (which would grab the first focusable / the content root).
        // We then deliberately place focus on the primary advance button so a
        // keyboard user can immediately press Enter to advance and Tab to
        // Back/Skip — see the focus-stepping note in the file header. Doing it
        // here (not in an effect) guarantees the button ref is attached, because
        // this fires right after the portaled content mounts. Still non-blocking:
        // modal={false} means no focus trap, and Escape/Skip/× still dismiss.
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          // DEFECT 2: capture where focus was BEFORE we pull it into the tour, so
          // `onCloseAutoFocus` can hand it back on dismiss (Radix has no Trigger
          // to restore to). This fires once per tour open (the content stays
          // mounted across steps), so we only ever record the true pre-tour
          // element, never the advance button we're about to focus.
          returnFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
          advanceButtonRef.current?.focus({ preventScroll: true });
          didInitialFocusRef.current = true;
          // Record step 0 as already-focused so the per-step effect above does
          // not double-fire for the initial step (see focusedStepRef note).
          focusedStepRef.current = stepIndex;
        }}
        // DEFECT 2 FIX — restore focus on close. WHY: on dismiss (Escape/Skip/×/
        // Done) the advance button unmounts and there is no `Popover.Trigger` (our
        // anchor is an aria-hidden, pointerEvents:none div), so Radix's default
        // return-focus target is nothing → focus lands on <body> and the keyboard
        // user loses their place. We restore focus to the element that had it when
        // the tour opened, falling back to a stable page control if that element
        // was unmounted while the tour ran.
        onCloseAutoFocus={(e) => {
          const prior = returnFocusRef.current;
          returnFocusRef.current = null;
          // Prefer the pre-tour element, but only if it is still in the document
          // (guard against it having been detached/unmounted since open).
          let restoreTo: HTMLElement | null =
            prior && prior.isConnected ? prior : null;
          if (!restoreTo) {
            // Fallback: a stable, always-relevant control (Add Position / mode
            // toggle) so focus still lands somewhere sensible, never on <body>.
            restoreTo =
              document.querySelector<HTMLElement>('[data-tour-target="add-position"]') ??
              document.querySelector<HTMLElement>('[data-tour-target="mode-toggle"]');
          }
          if (restoreTo && typeof restoreTo.focus === "function") {
            // Prevent Radix's default (which would drop to <body>) and place focus
            // ourselves; preventScroll so restoring focus never scroll-jumps.
            e.preventDefault();
            restoreTo.focus({ preventScroll: true });
          }
          // If nothing suitable exists we let Radix do its default (no throw).
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-mono text-[11px] uppercase tracking-[0.06em] text-primary">
            {step.title}
          </h3>
          {/* × — the always-present dismiss affordance (R-31). */}
          <button
            type="button"
            aria-label="Close tour"
            data-testid="portfolio-tour-close"
            onClick={endTour}
            className="-mr-1 -mt-1 flex h-5 w-5 items-center justify-center rounded-[2px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
          </button>
        </div>

        <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">{step.body}</p>

        {/* Progress + controls */}
        <div className="mt-3 flex items-center justify-between">
          <button
            type="button"
            data-testid="portfolio-tour-skip"
            onClick={endTour}
            className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            Skip tour
          </button>

          <div className="flex items-center gap-1.5">
            {/* Back is hidden on the first live step (nothing to go back to). */}
            {stepIndex > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                data-testid="portfolio-tour-back"
                onClick={handleBack}
                className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em]"
              >
                Back
              </Button>
            )}
            <Button
              // Focus target for keyboard focus-stepping (see file header A11Y note).
              ref={advanceButtonRef}
              type="button"
              size="sm"
              data-testid="portfolio-tour-next"
              onClick={handleNext}
              className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em]"
            >
              {isLastStep ? "Done" : "Next"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
