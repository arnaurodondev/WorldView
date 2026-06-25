/**
 * components/instrument/header/InstrumentAlertButton.tsx — "＋ Alert" entry point
 * on the instrument detail header (PLAN-0113 Wave 5, T-5-01 / PRD-0113 FR-11).
 *
 * WHY THIS EXISTS:
 * Journey A/B/E (PRD-0113 §2): a trader on the AAPL page should be able to set a
 * price / fundamental / news alert *for the instrument they are looking at*
 * without re-searching for it in a generic wizard. This button opens the existing
 * type-first `AlertWizard` PRE-SCOPED to this instrument:
 *   - the wizard opens on a PRICE_CROSS rule (the most common instrument alert),
 *   - the instrument is seeded into the editor (chip already filled, showing the
 *     ticker), so the user only chooses direction + price.
 * The user can still switch type via the wizard's "← Back" → other instrument
 * types (FUNDAMENTAL_CROSS / NEWS_*) also key on this instrument/entity.
 *
 * ARCHITECTURE: this is pure UI wiring — all persistence flows through the wizard's
 * gateway hooks (R14, Frontend → S9 only). No direct backend calls here.
 *
 * WHY a self-contained component (not inline in InstrumentHeader): InstrumentHeader
 * is a tight, unit-tested 36px layout component with a narrow prop surface. Folding
 * wizard open-state + the dialog into it would bloat it and couple it to the alert
 * feature. A small sibling keeps the header presentational and this concern local.
 */

"use client";
// WHY "use client": owns the wizard open/close useState and mounts the wizard.

import { useState } from "react";
import { BellPlus } from "lucide-react";
import { AlertWizard } from "@/components/alerts/AlertWizard";

export interface InstrumentAlertButtonProps {
  /**
   * The S3 instrument_id (price/fundamental rules key on this). When null (the
   * page-bundle is still loading) the button is disabled — we can't seed a rule
   * without an id.
   */
  readonly instrumentId: string | null;
  /** Ticker for the seeded chip + NL summary label (e.g. "AAPL"). */
  readonly ticker?: string | null;
  /** Company name, used as a richer chip label when present. */
  readonly name?: string | null;
}

export function InstrumentAlertButton({
  instrumentId,
  ticker,
  name,
}: InstrumentAlertButtonProps) {
  const [open, setOpen] = useState(false);

  // Display label for the seeded chip / summary: prefer the ticker (terse, what
  // a trader scans for); fall back to the name, then a generic "this instrument".
  const displayName = ticker ?? name ?? "this instrument";

  return (
    <>
      <button
        type="button"
        // No instrument id yet → nothing to scope the rule to.
        disabled={!instrumentId}
        onClick={() => setOpen(true)}
        data-testid="instrument-alert-button"
        aria-label="Create an alert for this instrument"
        className="flex items-center gap-1 rounded-[2px] border border-border/50 bg-muted/20 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:border-primary/50 hover:bg-muted/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
      >
        <BellPlus className="size-3" aria-hidden="true" />
        Alert
      </button>

      {/* The wizard only mounts the heavy editor tree while open. We pre-scope it
          to PRICE_CROSS and seed the instrument_id; the chip shows `displayName`
          via prefillNames. Save / cancel close it (controlled). */}
      {instrumentId && (
        <AlertWizard
          open={open}
          onOpenChange={setOpen}
          initialRuleType="PRICE_CROSS"
          prefillCondition={{ instrument_id: instrumentId }}
          prefillNames={{ [instrumentId]: displayName }}
        />
      )}
    </>
  );
}
