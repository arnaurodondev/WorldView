/**
 * context/ContradictionsBlock.tsx — KG-detected contradictory claims (W7 T-12)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — the KG pipeline runs a contradiction detector
 * that flags claim pairs with conflicting signals (e.g., two sources disagree on
 * a company's revenue). Surfacing these in the Intelligence right rail allows
 * analysts to instantly spot data integrity issues before acting on them.
 *
 * WHO USES IT: ContextPanel (entity-overview mode, below PathInsightsBlock).
 * DATA SOURCE: GET /v1/entities/{id}/contradictions via S9 gateway.
 * DESIGN REFERENCE: W7 design doc §5.4 (ContradictionsBlock, 60px cards).
 *
 * WHY SEVERITY NORMALIZATION (Δ8):
 * The backend returns severity as a string but the historical data has mixed
 * casing from schema evolution ("HIGH" vs "high"). Always calling .toUpperCase()
 * before the conditional branch makes the UI immune to future casing changes.
 * Unknown values (undefined, null, "UNKNOWN") fall back to "LOW" so we never
 * show a blank severity badge.
 */

"use client";
// WHY "use client": useQuery + onClick require browser context.

import { useQuery } from "@tanstack/react-query";
import { useAccessToken } from "@/lib/api-client";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

export interface ContradictionsBlockProps {
  readonly entityId: string;
  readonly limit?: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Normalize severity to uppercase; unknown/falsy → "LOW". (Δ8) */
function normalizeSeverity(raw: string | null | undefined): "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" {
  const up = (raw ?? "LOW").toUpperCase() as "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  return ["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(up)
    ? up
    : "LOW";
}

/** Severity → color class. */
function severityClass(severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"): string {
  if (severity === "LOW") return "text-positive bg-positive/10";
  if (severity === "MEDIUM") return "text-warning bg-warning/10";
  // HIGH and CRITICAL both get error styling — critical is just the most severe variant.
  return "text-negative bg-negative/10";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ContradictionsBlock({ entityId, limit = 5 }: ContradictionsBlockProps) {
  // WHY useAccessToken (not useAuth): matches the token source used by all other
  // intelligence hooks (useEntityPaths, EntityOverviewBlock) so enabled guard fires
  // consistently. useAuth().accessToken can lag behind on hydration causing suppressed queries.
  const accessToken = useAccessToken();

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.kg.contradictions(entityId),
    queryFn: () => createGateway(accessToken).getContradictions(entityId),
    staleTime: 2 * 60 * 1000, // WHY 2 min: contradictions update with every pipeline run (~2 min cadence)
    enabled: !!accessToken && !!entityId,
  });

  const sectionLabel = (
    <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground px-3 py-1 block">
      CONTRADICTIONS
    </span>
  );

  if (isLoading) {
    return (
      <div>
        {sectionLabel}
        <div className="px-3 py-1">
          <Skeleton className="h-[60px] w-full" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">Contradiction data unavailable.</p>
      </div>
    );
  }

  const contradictions = (data?.contradictions ?? []).slice(0, limit);

  if (contradictions.length === 0) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">No contradictions detected.</p>
      </div>
    );
  }

  return (
    <div>
      {sectionLabel}
      <div className="space-y-1 px-3">
        {contradictions.map((c: Contradiction) => {
          const severity = normalizeSeverity(c.severity);
          // WHY source_a as URL: the existing ContradictionsResponse type uses
          // source_a/source_b as string URLs (not {url, label} objects). We open
          // source_a in a new tab so analysts can read the originating claim.
          // WHY protocol guard: reject javascript:/data: URLs from API to prevent injection.
          const handleClick = () => {
            if (!c.source_a) return;
            try {
              const parsed = new URL(c.source_a);
              if (!["http:", "https:"].includes(parsed.protocol)) return;
            } catch {
              return;
            }
            window.open(c.source_a, "_blank", "noopener,noreferrer");
          };

          return (
            <button
              key={c.contradiction_id}
              type="button"
              onClick={handleClick}
              className={cn(
                "w-full min-h-[60px] py-2 px-2 flex flex-col gap-0.5 text-left",
                "border border-border-subtle hover:bg-muted/20 transition-color-only duration-100",
              )}
            >
              {/* ── Row 1: severity badge + detected_at ───────────────────── */}
              <div className="flex items-center justify-between">
                <span
                  className={cn(
                    "text-[9px] font-mono uppercase tracking-wider px-1 py-0.5 rounded-[2px]",
                    severityClass(severity),
                  )}
                >
                  {severity}
                </span>
                <span className="text-[9px] font-mono text-muted-foreground tabular-nums">
                  {formatDate(c.detected_at)}
                </span>
              </div>

              {/* ── Row 2: claim A (positive assertion) ───────────────────── */}
              <span className="text-[10px] text-foreground/90 truncate w-full">{c.claim_a}</span>

              {/* ── Row 3: claim B (conflicting assertion) ────────────────── */}
              <span className="text-[10px] text-muted-foreground truncate w-full">
                vs. {c.claim_b}
              </span>

              {/* ── Row 4: source URLs ────────────────────────────────────── */}
              {(c.source_a || c.source_b) && (
                <span className="text-[9px] text-muted-foreground/70 truncate w-full">
                  {[c.source_a, c.source_b]
                    .filter(Boolean)
                    .map((url) => {
                      try {
                        return new URL(url!).hostname;
                      } catch {
                        return url;
                      }
                    })
                    .join(" · ")}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
