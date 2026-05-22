/**
 * sidebar/AIBriefPanel.tsx — AI brief summary panel with expand dialog
 *
 * WHY THIS EXISTS (T-22): The AI brief is the highest-signal artifact on the
 * Financials tab: 2-3 bullets distilling the last 24h of news and fundamentals
 * into actionable insights. Showing it in the sidebar ensures analysts see it
 * alongside the metrics grid without needing to navigate to the Intelligence tab.
 *
 * WHY useInstrumentBrief (not a direct fetch): T-22 spec says "uses existing
 * useInstrumentBrief(id) (W5)". This hook manages the lazy-generate lifecycle
 * (GET → POST /generate → poll) so the panel never blocks on brief generation.
 *
 * WHY "Expand →" dialog: the sidebar is 240px wide — only 2-3 bullets fit at
 * 11px. The full brief (lead + all sections + citations) needs more space.
 * A shadcn Dialog is the canonical fullscreen overlay for this use case.
 *
 * RISK CHIP: risk_summary.concentration_score [0,1] → LOW/MEDIUM/HIGH label
 * with semantic color. Missing risk_summary → chip hidden.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: useInstrumentBrief(instrumentId) → S8 GET /v1/briefings/instrument/{id}.
 */

"use client";
// WHY "use client": useInstrumentBrief + Dialog state require client runtime.

import { useState } from "react";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AIBriefPanelProps {
  instrumentId: string;
}

function riskLabel(score: number): { label: string; color: string } {
  if (score >= 0.7) return { label: "HIGH RISK", color: "text-negative" };
  if (score >= 0.4) return { label: "MED RISK",  color: "text-warning" };
  return { label: "LOW RISK", color: "text-positive" };
}

export function AIBriefPanel({ instrumentId }: AIBriefPanelProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: brief, status } = useInstrumentBrief(instrumentId);

  // Extract up to 3 bullets from the first non-empty section.
  const firstSection = brief?.sections?.find((s) => s.bullets?.length > 0);
  const bullets = firstSection?.bullets?.slice(0, 3) ?? [];
  // Fall back to narrative preview if no structured bullets yet.
  const narrativeLines = brief?.narrative
    ? brief.narrative.split("\n").filter(Boolean).slice(0, 3)
    : [];

  const showBullets = bullets.length > 0;
  const showNarrative = !showBullets && narrativeLines.length > 0;
  const riskScore = brief?.risk_summary?.concentration_score;
  const risk = riskScore != null ? riskLabel(riskScore) : null;

  return (
    <div className="flex flex-col gap-1.5 px-2 py-2 border-b border-border">
      <div className="flex items-center justify-between">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          AI BRIEF
        </span>
        {risk && (
          <span className={`text-[9px] font-mono font-semibold ${risk.color}`}>
            {risk.label}
          </span>
        )}
      </div>

      {(status === "loading" || status === "generating") && (
        <span className="text-[10px] text-muted-foreground/40">
          {status === "generating" ? "Generating…" : "Loading…"}
        </span>
      )}

      {status === "unavailable" && (
        <span className="text-[10px] text-muted-foreground/40">Brief unavailable.</span>
      )}

      {status === "ready" && (
        <>
          {showBullets && (
            <ul className="flex flex-col gap-0.5 pl-0 list-none">
              {bullets.map((bullet, i) => (
                <li key={i} className="flex gap-1 items-start">
                  <span className="text-muted-foreground/40 text-[10px] shrink-0 mt-[1px]">•</span>
                  <span className="text-[10px] text-foreground leading-[14px] line-clamp-2">
                    {typeof bullet === "string" ? bullet : bullet.text}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {showNarrative && (
            <ul className="flex flex-col gap-0.5 pl-0 list-none">
              {narrativeLines.map((line, i) => (
                <li key={i} className="flex gap-1 items-start">
                  <span className="text-muted-foreground/40 text-[10px] shrink-0 mt-[1px]">•</span>
                  <span className="text-[10px] text-foreground leading-[14px] line-clamp-2">
                    {line}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <button
            onClick={() => setDialogOpen(true)}
            className="text-[9px] text-primary/70 hover:text-primary transition-colors text-left mt-0.5"
          >
            Expand →
          </button>
        </>
      )}

      {/* Full brief dialog — shown on "Expand →" click. */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-mono text-[13px]">AI Brief</DialogTitle>
          </DialogHeader>

          {brief?.lead && (
            <p className="text-[12px] text-foreground leading-relaxed mb-3">
              {brief.lead}
            </p>
          )}

          {brief?.sections?.map((section, i) => (
            <div key={i} className="mb-3">
              <h4 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground mb-1">
                {section.title}
              </h4>
              <ul className="space-y-1">
                {section.bullets.map((b, j) => (
                  <li key={j} className="flex gap-1.5 text-[11px] text-foreground leading-[16px]">
                    <span className="text-muted-foreground/50 shrink-0">•</span>
                    <span>{typeof b === "string" ? b : b.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {!brief?.sections?.length && brief?.narrative && (
            <p className="text-[11px] text-foreground leading-relaxed whitespace-pre-wrap">
              {brief.narrative}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
