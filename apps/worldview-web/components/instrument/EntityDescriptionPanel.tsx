/**
 * components/instrument/EntityDescriptionPanel.tsx
 *
 * WHY THIS EXISTS: Displays Worker 13J enrichment data (PRD-0073) for the entity
 * currently being viewed in the Instrument Detail page.  Shows:
 *   - Entity name + type badge
 *   - Description paragraph (from S3/EODHD/LLM cascade)
 *   - Data completeness score bar (0–100%)
 *   - Key metadata fields (sector, industry, country, exchange, ticker, ISIN)
 *
 * Renders a skeleton when description is null (enrichment pending or not started).
 *
 * DATA FLOW: fetches GET /v1/entities/{entityId} → S9 (PRD-0073 Wave D-1) → S7.
 * TanStack Query caches for 2 hours — descriptions are stable once written.
 *
 * WHO USES IT: IntelligenceTab (embedded above the graph section).
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import type { EntityMetadata } from "@/types/api";

interface EntityDescriptionPanelProps {
  entityId: string;
  className?: string;
}

// ── Metadata key-value pair ───────────────────────────────────────────────────
// WHY a small sub-component: keeps the metadata row rendering DRY and typed.
function MetaRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="shrink-0 w-[88px] text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
        {label}
      </span>
      <span className="font-mono text-[11px] text-foreground/80 truncate">{value}</span>
    </div>
  );
}

// ── Fields to render from EntityMetadata ─────────────────────────────────────
// WHY explicit list (not Object.entries): controls order and labels.
type MetaFieldKey = keyof EntityMetadata;
const META_FIELDS: Array<{ key: MetaFieldKey; label: string }> = [
  { key: "ticker", label: "Ticker" },
  { key: "isin", label: "ISIN" },
  { key: "exchange", label: "Exchange" },
  { key: "sector", label: "Sector" },
  { key: "industry", label: "Industry" },
  { key: "country", label: "Country" },
  { key: "headquarters_city", label: "HQ City" },
  { key: "currency_code", label: "Currency" },
  { key: "founded_year", label: "Founded" },
  { key: "employee_count", label: "Employees" },
];

// ── Component ─────────────────────────────────────────────────────────────────
export function EntityDescriptionPanel({ entityId, className }: EntityDescriptionPanelProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    queryKey: ["entity-detail", entityId],
    queryFn: () => createGateway(accessToken).getEntityDetail(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 2h staleTime: descriptions are stable once written by Worker 13J.
    // The overnight sweep updates enrichment_attempts/enriched_at, not description.
    staleTime: 2 * 60 * 60 * 1000,
    retry: 1,
  });

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <section className={cn("p-3 space-y-2", className)}>
        <div className="flex items-center gap-2 mb-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-16 rounded-[2px]" />
        </div>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </section>
    );
  }

  // ── Null state (entity not yet enriched or 404) ───────────────────────────
  // WHY show nothing rather than an error: enrichment runs overnight — a fresh
  // entity may simply not have been processed yet.  Showing an error would be
  // misleading.  The panel disappears entirely so the tab feels clean.
  if (!data || !data.description) {
    return null;
  }

  // ── Populated description ─────────────────────────────────────────────────
  const completeness = data.data_completeness ?? 0;
  const completePct = Math.round(completeness * 100);
  const populatedMeta = META_FIELDS.filter(
    ({ key }) => data.metadata[key] != null,
  );

  return (
    <section className={cn("p-3 border-b border-border/40", className)}>
      {/* Header: name + type badge */}
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-[12px] font-medium text-foreground leading-tight truncate">
          {data.canonical_name}
        </h3>
        <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {data.entity_type.replace(/_/g, " ")}
        </span>
      </div>

      {/* Description paragraph */}
      <p className="text-[11px] text-foreground/80 leading-relaxed mb-3">
        {data.description}
      </p>

      {/* Data completeness bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
            Data completeness
          </span>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {completePct}%
          </span>
        </div>
        {/* WHY bg-border/30 base + bg-primary fill: matches existing confidence bars in
            GraphDetailSidebar (consistent visual language across the Intelligence tab). */}
        <div className="h-1 w-full rounded-full bg-border/30 overflow-hidden">
          <div
            className="h-full rounded-full bg-primary/60 transition-all duration-300"
            style={{ width: `${completePct}%` }}
            role="progressbar"
            aria-valuenow={completePct}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      </div>

      {/* Metadata key-value grid */}
      {populatedMeta.length > 0 && (
        <div className="space-y-1">
          {populatedMeta.map(({ key, label }) => (
            <MetaRow key={key} label={label} value={String(data.metadata[key]!)} />
          ))}
        </div>
      )}
    </section>
  );
}
