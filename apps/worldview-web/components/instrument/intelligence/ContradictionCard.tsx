/**
 * components/instrument/intelligence/ContradictionCard.tsx
 *
 * WHY THIS EXISTS:
 * Single-card renderer for one NLP-extracted contradiction. Extracted from
 * IntelligenceTab.tsx (was inline at lines 156-231) to keep each sub-component
 * focused and under 100 lines. The card has two visual states:
 *
 *   - COLLAPSED: a 22px-tall Bloomberg-style row showing severity badge,
 *     truncated claim-A text, and timestamp. Clicking expands it.
 *   - EXPANDED: full two-claim comparison with "Claim A vs Claim B" layout,
 *     evidence sources, and a collapse button.
 *
 * WHY SEVERITY_STYLES here (not in a shared token file): they are only consumed
 * by this component and the severity filter strip in IntelligenceTab. Keeping
 * them co-located avoids an over-engineered constants module for 3 entries.
 *
 * WHO USES IT: components/instrument/intelligence/ContradictionsSection.tsx
 *   (which is rendered by IntelligenceTab.tsx)
 */

"use client";

import { AlertTriangle, ChevronRight, ChevronDown } from "lucide-react";
import { formatRelativeTime } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

// ── Severity → badge / icon styles ───────────────────────────────────────────
// WHY explicit Record (not dynamic): text-negative / text-warning are Tailwind
// design-token aliases defined in tailwind.config.ts; the compiler tree-shakes
// classes that aren't statically present in the codebase, so we cannot build
// class strings dynamically from severity strings.
export const SEVERITY_STYLES: Record<
  Contradiction["severity"],
  { icon: string; badge: string; text: string }
> = {
  HIGH: {
    icon: "text-negative",
    badge: "bg-destructive/15 text-negative",
    text: "HIGH",
  },
  MEDIUM: {
    icon: "text-warning",
    badge: "bg-warning/15 text-warning",
    text: "MED",
  },
  LOW: {
    icon: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    text: "LOW",
  },
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface ContradictionCardProps {
  item: Contradiction;
  isExpanded: boolean;
  onToggle: () => void;
}

// ── ContradictionCard ─────────────────────────────────────────────────────────

export function ContradictionCard({ item, isExpanded, onToggle }: ContradictionCardProps) {
  const styles = SEVERITY_STYLES[item.severity];

  // ── Collapsed row (22px Bloomberg-style) ──────────────────────────────────
  if (!isExpanded) {
    return (
      <div
        onClick={onToggle}
        className="flex items-center h-[22px] border-b border-border/30 hover:bg-muted/40 cursor-pointer"
        role="presentation"
      >
        <button
          type="button"
          className="w-full flex items-center h-[22px] px-2 gap-1.5 text-left"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          aria-expanded={false}
          aria-label={`Expand contradiction: ${item.claim_a.slice(0, 40)}`}
        >
          <span className={`rounded-[2px] px-1 py-0 text-[9px] font-semibold uppercase ${styles.badge}`}>
            {styles.text}
          </span>
          <span className="text-[11px] text-foreground flex-1 truncate">
            {item.claim_a.slice(0, 60)}{item.claim_a.length > 60 ? "…" : ""}
          </span>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
            {formatRelativeTime(item.detected_at)}
          </span>
          <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" strokeWidth={1.5} />
        </button>
      </div>
    );
  }

  // ── Expanded card: full claim A vs B comparison ───────────────────────────
  return (
    <div className="rounded-[2px] border border-border/40 bg-card/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded-[2px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {formatRelativeTime(item.detected_at)}
          </span>
          <button onClick={onToggle} className="text-muted-foreground hover:text-foreground" aria-label="Collapse contradiction">
            <ChevronDown className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>
      <div className="space-y-2">
        <div className="rounded-[2px] bg-positive/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim A</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
        </div>
        <div className="rounded-[2px] bg-negative/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim B</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_b}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_b}</p>
        </div>
      </div>
    </div>
  );
}
