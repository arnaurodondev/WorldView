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

// ── Real-backend shape normalisation (UI roadmap 2026-06-19 item #4) ──────────
//
// WHY THIS EXISTS: the S7 contradiction-detection job (claim_repository
// .fetch_contradictions_for_entity, recently fixed so recent_contradiction_count
// now populates) returns a DETAIL shape that the api-gateway PASSES THROUGH
// verbatim (intelligence.py is a pass-through proxy). That live shape is NOT the
// flat `claim_a/claim_b/source_a/source_b/severity` the frontend `Contradiction`
// type historically modelled — it is:
//
//   { claim_type, strength, detected_at,
//     sides: [{ polarity, confidence, doc_id, claim_text, evidence_date }, …] }
//
// (see services/knowledge-graph .../api/schemas: ContradictionDetailResponse +
// ContradictionSideResponse). Rendering the old flat fields against the new
// payload would print blank claims. We normalise BOTH shapes here, at the
// rendering boundary, so:
//   • the now-flowing detail data renders claim-vs-counterclaim WITH per-side
//     confidence + recency (the item #4 differentiator), and
//   • the legacy flat shape (and the existing unit tests / 404→null contract)
//     keep working unchanged.
// The frontend `Contradiction` type lives in types/api.ts (out of this change's
// scope); normalising defensively here is the minimal, forward-compatible fix.

/** One side of a contradiction in the live S7 detail shape. */
interface ContradictionSide {
  polarity?: string | null;
  confidence?: number | null;
  doc_id?: string | null;
  claim_text?: string | null;
  evidence_date?: string | null;
}

/** The flat display model the card actually renders from. */
interface DisplayContradiction {
  key: string;
  claimType: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  detectedAt: string | null | undefined;
  claimA: string;
  claimB: string;
  sourceA: string;
  sourceB: string;
  confidenceA: number | null;
  confidenceB: number | null;
}

/**
 * strengthToSeverity — the detail shape carries a numeric `strength` [0,1]
 * instead of a HIGH/MEDIUM/LOW band. Map it so the severity badge keeps
 * working. Thresholds mirror the platform's confidence banding (>=0.66 high,
 * >=0.33 medium). Used only when no explicit `severity` string is present.
 */
function strengthToSeverity(strength: number | null | undefined): "HIGH" | "MEDIUM" | "LOW" {
  if (strength == null) return "LOW";
  if (strength >= 0.66) return "HIGH";
  if (strength >= 0.33) return "MEDIUM";
  return "LOW";
}

/** A polarity string (e.g. "POSITIVE"/"NEGATIVE") makes a readable source label. */
function sideSource(side: ContradictionSide | undefined, fallback: string): string {
  const polarity = side?.polarity?.trim();
  if (polarity) return polarity.toUpperCase();
  // doc_id is a UUID — too noisy as a label; only use polarity, else fallback.
  return fallback;
}

/**
 * normalizeContradiction — accept either the live detail shape OR the legacy
 * flat shape and produce a single DisplayContradiction.
 *
 * WHY a permissive cast: the typed `Contradiction` models the legacy flat shape
 * only; the live payload arrives untyped through the pass-through proxy. We read
 * both field sets off a loose record and prefer whichever is present.
 */
function normalizeContradiction(raw: Contradiction, index: number): DisplayContradiction {
  const r = raw as unknown as Record<string, unknown>;
  const sides = Array.isArray(r.sides) ? (r.sides as ContradictionSide[]) : null;

  // claim_type pill: explicit on the detail shape; "CLAIM" otherwise (Δ16).
  const claimType = typeof r.claim_type === "string" && r.claim_type.trim()
    ? r.claim_type.toUpperCase()
    : "CLAIM";

  // Severity: explicit band wins; else derive from numeric `strength`.
  const severity = r.severity != null
    ? normalizeSeverity(r.severity as string)
    : strengthToSeverity(typeof r.strength === "number" ? r.strength : null);

  // detected_at is present on both shapes.
  const detectedAt = (r.detected_at as string | null | undefined) ?? null;

  if (sides && sides.length >= 2) {
    // ── Live detail shape: two opposing sides. ──
    const a = sides[0];
    const b = sides[1];
    return {
      key: (r.contradiction_id as string) ?? `con-${index}`,
      claimType,
      severity,
      detectedAt: detectedAt ?? a?.evidence_date ?? b?.evidence_date ?? null,
      claimA: a?.claim_text?.trim() || "—",
      claimB: b?.claim_text?.trim() || "—",
      sourceA: sideSource(a, "Side A"),
      sourceB: sideSource(b, "Side B"),
      confidenceA: typeof a?.confidence === "number" ? a.confidence : null,
      confidenceB: typeof b?.confidence === "number" ? b.confidence : null,
    };
  }

  // ── Legacy flat shape (and the unit-test fixtures). ──
  return {
    key: raw.contradiction_id ?? `con-${index}`,
    claimType,
    severity,
    detectedAt,
    claimA: raw.claim_a ?? "—",
    claimB: raw.claim_b ?? "—",
    sourceA: raw.source_a || "Source A",
    sourceB: raw.source_b || "Source B",
    confidenceA: null,
    confidenceB: null,
  };
}

/** Render a [0,1] confidence as a compact "· 80%" suffix; null → nothing. */
function ConfidenceTag({ value }: { value: number | null }) {
  if (value == null) return null;
  // tabular-nums so the suffix doesn't jitter the source prefix width.
  return (
    <span className="font-mono text-[9px] tabular-nums text-muted-foreground/70">
      {" · "}
      {Math.round(value * 100)}%
    </span>
  );
}

// ── Sub-component: individual contradiction card ──────────────────────────────

interface ContradictionCardProps {
  contradiction: DisplayContradiction;
}

function ContradictionCard({ contradiction }: ContradictionCardProps) {
  return (
    // WHY border-border/40: consistent with other right-rail cards (RelationsList rows).
    <div className="border border-border/40 p-2 space-y-1">
      {/* ── Header: claim_type pill + severity badge ────────────────────────── */}
      <div className="flex items-center gap-1.5">
        {/* claim_type pill — uppercase, 9px mono (Δ16) */}
        <span className="text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {contradiction.claimType}
        </span>
        {/* severity badge (Δ8: always uppercase, fallback LOW) */}
        <span
          className={cn(
            "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px]",
            severityClass(contradiction.severity),
          )}
        >
          {contradiction.severity}
        </span>
        {/* Detected date — right-aligned in the header row (Round-1 req 4).
            WHY ml-auto: keeps the pills left-clustered and the date scannable
            at the row's end, matching the platform's "timestamps trail" rule. */}
        <span className="ml-auto text-[9px] font-mono tabular-nums text-muted-foreground/70">
          {formatDate(contradiction.detectedAt)}
        </span>
      </div>

      {/* ── Claims: source A's claim vs source B's claim ─────────────────────
          Round-1 requirement 4: each side is attributed to its SOURCE so the
          analyst can judge credibility without opening the underlying articles.
          Item #4: when the live detail shape supplies a per-side CONFIDENCE we
          render it next to the source — the analyst sees not just "these two
          conflict" but "how sure the pipeline is of each side". */}
      <p className="text-[10px] text-foreground/90 leading-snug">
        <span className="font-mono text-[9px] text-muted-foreground">{contradiction.sourceA}</span>
        <ConfidenceTag value={contradiction.confidenceA} />
        <span className="font-mono text-[9px] text-muted-foreground">: </span>
        {contradiction.claimA}
      </p>
      <p className="text-[9px] text-muted-foreground font-mono uppercase">vs</p>
      <p className="text-[10px] text-foreground/90 leading-snug">
        <span className="font-mono text-[9px] text-muted-foreground">{contradiction.sourceB}</span>
        <ConfidenceTag value={contradiction.confidenceB} />
        <span className="font-mono text-[9px] text-muted-foreground">: </span>
        {contradiction.claimB}
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
        {visible.map((c, i) => {
          // Normalise each raw row (live detail OR legacy flat shape) into the
          // single display model the card renders from (item #4).
          const display = normalizeContradiction(c, i);
          return <ContradictionCard key={display.key} contradiction={display} />;
        })}
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
