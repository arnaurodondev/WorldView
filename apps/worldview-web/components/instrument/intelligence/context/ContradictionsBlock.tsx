/**
 * context/ContradictionsBlock.tsx — KG-detected contradictions for the Intelligence
 * right rail (W7 Block I, T-12).
 *
 * WHY THIS EXISTS: The knowledge-graph pipeline runs a contradiction-detection job
 * that flags pairs of conflicting claims about an entity (e.g. two sources saying
 * opposite things about whether a merger is complete). Surfacing these in the
 * Intelligence tab lets analysts immediately see data-quality signals that would
 * otherwise be buried in raw article text.
 *
 * DESIGN REFERENCE: W7 §1 checks 12/30 (Δ8 + Δ16).
 * DATA SOURCE: GET /v1/entities/{id}/contradictions → ContradictionsResponse
 *              via createKnowledgeGraphApi(token).getContradictions(entityId)
 *
 * WHO USES IT: ContextPanel (entity-overview mode, 4th block in the 5-block stack).
 */

"use client";
// WHY "use client": useQuery + useAuth + the expand/collapse useState require
// the browser runtime.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createKnowledgeGraphApi } from "@/lib/api/knowledge-graph";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
// Round-3 consolidation (DS §15.12): shared primitive + reserved copy key
// replace the local components/instrument/shared/EmptyState.tsx fork.
import { EmptyState } from "@/components/primitives/EmptyState";
import { cn, formatDate } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * normalizeSeverity — ensures the severity badge is always uppercase and falls
 * back to "LOW" for unexpected values (Δ8 from W7 design audit).
 *
 * WHY normalize here (not at the API layer): the ContradictionsResponse comes
 * directly from the S7 proxy without transformation. Normalising at the
 * rendering layer keeps the type contract permissive while the UI is strict.
 */
function normalizeSeverity(s: string | undefined | null): "HIGH" | "MEDIUM" | "LOW" {
  const upper = (s ?? "").toUpperCase();
  if (upper === "HIGH" || upper === "MEDIUM" || upper === "LOW") return upper;
  return "LOW";
}

/**
 * severityClass — maps severity → color token class.
 *
 * WHY semantic tokens: no-off-palette-colors rule bans raw Tailwind palette
 * colors (text-red-*, text-amber-*). text-negative / text-warning / text-muted-foreground
 * resolve through globals.css and stay in sync when the design system is retuned.
 */
function severityClass(s: "HIGH" | "MEDIUM" | "LOW"): string {
  if (s === "HIGH") return "text-negative bg-negative/15";
  if (s === "MEDIUM") return "text-warning bg-warning/15";
  return "text-muted-foreground bg-muted";
}

// ── Sub-component: individual contradiction card ──────────────────────────────

interface ContradictionCardProps {
  contradiction: Contradiction;
}

function ContradictionCard({ contradiction }: ContradictionCardProps) {
  const severity = normalizeSeverity(contradiction.severity);
  // Δ16: claim_type pill. The Contradiction type currently has severity but not
  // claim_type — we derive a display label from the available severity field
  // until S9 exposes claim_type in a follow-up (backend additive change, zero risk).
  const claimTypeLabel = (contradiction as { claim_type?: string }).claim_type
    ? ((contradiction as { claim_type?: string }).claim_type ?? "CLAIM").toUpperCase()
    : "CLAIM";

  return (
    // WHY border-border/40: consistent with other right-rail cards (RelationsList rows).
    <div className="border border-border/40 p-2 space-y-1">
      {/* ── Header: claim_type pill + severity badge ────────────────────────── */}
      <div className="flex items-center gap-1.5">
        {/* claim_type pill — uppercase, 9px mono (Δ16) */}
        <span className="text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {claimTypeLabel}
        </span>
        {/* severity badge (Δ8: always uppercase, fallback LOW) */}
        <span
          className={cn(
            "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px]",
            severityClass(severity),
          )}
        >
          {severity}
        </span>
        {/* Detected date — right-aligned in the header row (Round-1 req 4).
            WHY ml-auto: keeps the pills left-clustered and the date scannable
            at the row's end, matching the platform's "timestamps trail" rule. */}
        <span className="ml-auto text-[9px] font-mono tabular-nums text-muted-foreground/70">
          {formatDate(contradiction.detected_at)}
        </span>
      </div>

      {/* ── Claims: source A's claim vs source B's claim ─────────────────────
          Round-1 requirement 4: each side is attributed to its SOURCE so the
          analyst can judge credibility (Reuters vs a blog) without opening
          the underlying articles. Source renders as a 9px mono prefix. */}
      <p className="text-[10px] text-foreground/90 leading-snug">
        <span className="font-mono text-[9px] text-muted-foreground">{contradiction.source_a || "Source A"}: </span>
        {contradiction.claim_a}
      </p>
      <p className="text-[9px] text-muted-foreground font-mono uppercase">vs</p>
      <p className="text-[10px] text-foreground/90 leading-snug">
        <span className="font-mono text-[9px] text-muted-foreground">{contradiction.source_b || "Source B"}: </span>
        {contradiction.claim_b}
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface ContradictionsBlockProps {
  readonly entityId: string;
  /** Number of contradiction cards visible while COLLAPSED. Default: 5. */
  readonly limit?: number;
  /**
   * Render the block's own "CONTRADICTIONS [N]" header with the count badge
   * (Round-1 requirement 4). The count lives inside this component's query,
   * so the parent (ContextPanel) cannot render an accurate badge itself —
   * it sets showHeader instead of drawing its own label.
   */
  readonly showHeader?: boolean;
}

export function ContradictionsBlock({
  entityId,
  limit = 5,
  showHeader = false,
}: ContradictionsBlockProps) {
  const { accessToken } = useAuth();
  // Round-1 requirement 4: the list is EXPANDABLE — collapsed shows `limit`
  // cards, "Show all (N)" reveals the rest. Local state because expansion is
  // a transient view preference (not shareable/bookmarkable).
  const [expanded, setExpanded] = useState(false);

  // WHY useQuery (not useEntityContradictions hook): the hook pattern is only
  // warranted when multiple components share the same query. ContradictionsBlock
  // is the sole consumer — inline query keeps the data-fetching visible here.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.kg.contradictions(entityId),
    queryFn: () => createKnowledgeGraphApi(accessToken ?? undefined).getContradictions(entityId),
    staleTime: 2 * 60 * 1000, // 2 min — contradictions update after each KG pipeline run
    enabled: !!accessToken && !!entityId,
    retry: 1,
  });

  // ── Loading skeleton (single card) ──────────────────────────────────────────
  if (isLoading) {
    return (
      <section className="space-y-1.5" aria-label="Contradictions loading">
        <Skeleton className="h-14 w-full" />
      </section>
    );
  }

  const all = data?.contradictions ?? [];

  // WHY the header renders for error/empty too: the count badge ("0") IS the
  // named state's headline number — hiding the header on empty would make the
  // section disappear entirely, violating the no-blank-areas rule.
  const header = showHeader ? (
    <div className="mb-1.5 flex items-center gap-1.5">
      {/* Round-3 item 2: label-level accent bar (border-l-2 border-l-primary)
          — the Round-1 section-start marker applied uniformly across the
          Financials AND Intelligence tabs (DenseMetricsGrid is the reference). */}
      <p className="border-l-2 border-l-primary pl-1.5 text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
        Contradictions
      </p>
      {/* Count badge — total detected (not just the visible slice). Tinted
          negative when any exist: contradictions are a data-quality warning. */}
      <span
        data-testid="contradictions-count"
        className={cn(
          "rounded-[2px] px-1 font-mono text-[9px] tabular-nums",
          all.length > 0 ? "bg-negative/15 text-negative" : "bg-muted text-muted-foreground",
        )}
      >
        {all.length}
      </span>
    </div>
  ) : null;

  // ── Error state ──────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div>
        {header}
        <p className="text-[10px] text-muted-foreground italic">
          Contradictions unavailable.
        </p>
      </div>
    );
  }

  // ── Empty state (named: icon + headline — Round-1 requirement 4) ────────────
  // Round-3: copy resolves via the reserved registry key (identical strings).
  // The local component's "inline" variant is gone — the primitive owns a
  // single centred layout so this state renders pixel-identical to every
  // other empty state on the platform (the consolidation's whole point).
  if (all.length === 0) {
    return (
      <div>
        {header}
        <EmptyState
          condition="empty-no-data"
          copyKey="instrument.no-contradictions"
          icon={Scale}
        />
      </div>
    );
  }

  // ── Populated state ──────────────────────────────────────────────────────────
  // Collapsed → first `limit` cards; expanded → everything.
  const visible = expanded ? all : all.slice(0, limit);
  const hiddenCount = all.length - limit;

  return (
    <div>
      {header}
      <section className="space-y-1.5" aria-label="Contradictions">
        {visible.map((c) => (
          <ContradictionCard key={c.contradiction_id} contradiction={c} />
        ))}
        {/* Expand/collapse toggle — only when there is something to reveal.
            WHY a text button (not an accordion): one extra row at 9px mono
            keeps the rail dense; an accordion header would cost 24px. */}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            // Round-3 item 5: focus-visible ring for keyboard reachability.
            className="font-mono text-[9px] uppercase tracking-wider text-primary hover:underline rounded-[2px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {expanded ? "Show less" : `Show all (${all.length})`}
          </button>
        )}
      </section>
    </div>
  );
}
