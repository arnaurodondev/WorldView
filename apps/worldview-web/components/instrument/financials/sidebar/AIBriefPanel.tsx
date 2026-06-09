/**
 * sidebar/AIBriefPanel.tsx — AI-generated instrument brief panel (T-22)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 §4.7 — the AI brief panel surfaces the 3 most
 * decision-relevant bullets from the RAG-generated instrument brief. Hedge fund
 * analysts use this as a "30-second brief" before diving into the full earnings
 * model — the kind:bull / kind:bear / kind:risk labelling mirrors the framing
 * S8 uses in its instrument briefing prompt (Δ28 rendering contract).
 *
 * WHY lazy-generate flow (GET→POST→poll): instrument briefs are generated
 * on-demand and cached for 1h (not pre-generated nightly like morning briefs).
 * The first user to open the tab for a ticker triggers generation; subsequent
 * users within 1h hit the Valkey cache. The hook (useInstrumentBrief) encapsulates
 * this complexity so this component stays purely presentational.
 *
 * WHY BriefBullet kind rendering (Δ28): `sections[0..N].bullets[0..2]` are
 * used to populate the panel. Since BriefBullet doesn't carry a `kind` field
 * natively, we infer kind from the section title if it contains BULL/BEAR/RISK.
 * If no sections are available, we fall back to the narrative field parsed as
 * bullet lines.
 *
 * WHO USES IT: AnalystSidebar.tsx composition shell (T-24).
 * DATA SOURCE: useInstrumentBrief(entityId) → S9 GET/POST /v1/briefings/instrument/{id}
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.7
 */

"use client";
// WHY "use client": useInstrumentBrief uses useState/useEffect/useQuery which
// require the browser runtime. The expand Dialog also uses event handlers.

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";
import type { BriefSection } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface AIBriefPanelProps {
  /**
   * entityId — the KG entity ID (same UUID as instrumentId post-F2).
   * WHY entityId (not instrumentId): the briefing endpoint is keyed on entity_id
   * in S8. Post-F2 they are the same UUID, so the prop name is cosmetic only
   * (Δ8 from the plan removes the old comment block in FinancialsTab).
   */
  entityId: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** extractBullets — pull up to 3 bullets from sections or narrative. */
function extractBullets(
  sections: BriefSection[] | undefined,
  narrative: string,
): Array<{ kind: string | null; text: string }> {
  // WHY prefer sections: structured sections carry more precision than the
  // raw narrative text. S8 W4+ responses always populate sections.
  if (sections && sections.length > 0) {
    const bullets: Array<{ kind: string | null; text: string }> = [];
    for (const section of sections) {
      for (const bullet of section.bullets) {
        if (bullets.length >= 3) break;
        // WHY infer kind from section.title: BriefBullet has no `kind` field.
        // S8 sections are titled e.g. "BULL CASE", "BEAR CASE", "RISK FACTORS".
        // Mapping section title → kind gives the Δ28 rendering contract.
        const titleUpper = section.title.toUpperCase();
        const kind =
          titleUpper.includes("BULL") ? "bull" :
          titleUpper.includes("BEAR") ? "bear" :
          titleUpper.includes("RISK") ? "risk" :
          null;
        bullets.push({ kind, text: bullet.text });
      }
      if (bullets.length >= 3) break;
    }
    return bullets;
  }

  // Fallback: split narrative into sentences, take first 3 as bullet lines.
  // WHY max 200 chars per bullet: avoids overflowing the compact sidebar panel.
  return narrative
    .split(/\.\s+/)
    .filter((s) => s.trim().length > 0)
    .slice(0, 3)
    .map((sentence) => ({
      kind: null,
      text: sentence.trim().slice(0, 200),
    }));
}

/** kindChipClass — design token color for each bullet kind. */
function kindChipClass(kind: string | null): string {
  if (kind === "bull") return "text-[color:var(--color-positive)] bg-[color:var(--color-positive)]/10";
  if (kind === "bear") return "text-[color:var(--color-negative)] bg-[color:var(--color-negative)]/10";
  if (kind === "risk") return "text-[color:var(--color-warning)] bg-[color:var(--color-warning)]/10";
  return "text-muted-foreground bg-muted/30";
}

/** riskLevelClass — color token for risk_summary.concentration_score bucket. */
function riskLevelClass(score: number): string {
  if (score >= 0.7) return "text-[color:var(--color-negative)]";
  if (score >= 0.4) return "text-[color:var(--color-warning)]";
  return "text-[color:var(--color-positive)]";
}

function riskLabel(score: number): string {
  if (score >= 0.7) return "HIGH RISK";
  if (score >= 0.4) return "MED RISK";
  return "LOW RISK";
}

// ── Status sub-components ─────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="flex flex-col gap-1.5 px-2 py-2">
      {/* WHY animate-pulse on divs (not Skeleton): the sidebar is too narrow for
          Skeleton's default height; custom divs match the actual bullet height. */}
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-[28px] rounded-[2px] bg-muted/30 animate-pulse" />
      ))}
    </div>
  );
}

function TriggeringState() {
  return (
    <div className="flex items-center gap-2 px-2 py-3">
      <div className="h-[8px] w-[8px] rounded-full bg-primary animate-pulse" />
      <span className="text-[10px] font-mono text-muted-foreground">Generating brief…</span>
    </div>
  );
}

function PollingState({ attempt, max }: { attempt?: number; max?: number }) {
  return (
    <div className="flex flex-col gap-1 px-2 py-2">
      <div className="flex items-center gap-2">
        <div className="h-[8px] w-[8px] rounded-full bg-primary animate-pulse" />
        <span className="text-[10px] font-mono text-muted-foreground">Generating…</span>
      </div>
      {attempt != null && max != null && (
        <span className="text-[9px] font-mono text-muted-foreground/50">
          Attempt {attempt}/{max} · ~30s per check
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AIBriefPanel({ entityId }: AIBriefPanelProps) {
  const { brief, status, errorMessage, retry } = useInstrumentBrief(entityId);
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div className="flex flex-col border-b border-border">
      {/* Panel header */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          AI BRIEF
        </span>
        {brief && (
          // WHY Dialog trigger here (not a Link): the full brief is a modal
          // overlay, not a separate page. This avoids a full navigation for
          // what is essentially a read-more interaction.
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <button
                className="text-[9px] font-mono text-primary hover:text-primary/80 transition-colors"
                aria-label="Expand AI brief"
              >
                Expand →
              </button>
            </DialogTrigger>
            <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle className="text-[12px] uppercase tracking-widest font-mono">
                  AI INSTRUMENT BRIEF
                </DialogTitle>
              </DialogHeader>
              {/* Full narrative in the dialog */}
              <div className="text-[11px] font-mono leading-relaxed text-foreground whitespace-pre-wrap">
                {brief.narrative}
              </div>
              {brief.risk_summary && (
                <div className="mt-4 border-t border-border pt-3">
                  <span className={`text-[10px] font-mono font-semibold ${riskLevelClass(brief.risk_summary.concentration_score)}`}>
                    {riskLabel(brief.risk_summary.concentration_score)}
                  </span>
                  <div className="mt-1 flex flex-col gap-1">
                    {brief.risk_summary.top_risk_signals.map((sig) => (
                      <span key={sig.signal_id} className="text-[10px] font-mono text-muted-foreground">
                        · {sig.description}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {brief.generated_at && (
                <div className="mt-2 text-[9px] font-mono text-muted-foreground/50">
                  Generated {brief.generated_at.slice(0, 10)}
                </div>
              )}
            </DialogContent>
          </Dialog>
        )}
      </div>

      {/* Panel body — varies by status */}
      {(status === "loading") && <LoadingState />}
      {(status === "triggering") && <TriggeringState />}
      {(status === "polling") && <PollingState />}

      {status === "error" && (
        <div className="flex flex-col gap-2 px-2 py-2">
          <span className="text-[10px] font-mono text-[color:var(--color-negative)]">
            {errorMessage ?? "Brief unavailable"}
          </span>
          <button
            onClick={retry}
            className="self-start text-[9px] font-mono text-primary hover:text-primary/80 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {status === "ready" && brief && (() => {
        const bullets = extractBullets(brief.sections, brief.narrative);
        return (
          <div className="flex flex-col gap-1 px-2 py-2">
            {/* Risk chip — from risk_summary if present */}
            {brief.risk_summary && (
              <span className={`self-start text-[8px] font-mono px-1 py-0.5 rounded-full ${riskLevelClass(brief.risk_summary.concentration_score)} bg-current/10`}>
                {riskLabel(brief.risk_summary.concentration_score)}
              </span>
            )}

            {/* Bullets — up to 3 with Δ28 kind prefix */}
            {bullets.length === 0 ? (
              <span className="text-[10px] font-mono text-muted-foreground italic">
                No bullets available.
              </span>
            ) : (
              bullets.map((bullet, idx) => (
                <div key={idx} className="flex items-start gap-1.5">
                  {/* WHY kind chip on bullet (not just text color): a chip
                      makes the bull/bear/risk label scannable at a glance even
                      when the text wraps to two lines. */}
                  {bullet.kind && (
                    <span
                      className={`shrink-0 mt-0.5 text-[7px] font-mono font-semibold uppercase px-1 rounded-[2px] ${kindChipClass(bullet.kind)}`}
                    >
                      {bullet.kind.toUpperCase()}
                    </span>
                  )}
                  {/* Δ28: if kind ∈ {bull, bear, risk} render "{KIND}: {text}";
                      else render plain text. The chip above handles the label. */}
                  <span className="text-[10px] font-mono leading-snug text-foreground line-clamp-3">
                    {bullet.text}
                  </span>
                </div>
              ))
            )}
          </div>
        );
      })()}
    </div>
  );
}
