/**
 * components/screener/NLScreenerInput.tsx — Natural-language screener bar
 *
 * WHY THIS EXISTS: Power users can describe screens in plain English
 * ("profitable tech stocks, P/E below 20") rather than manually configuring
 * ~16 filter controls. The LLM translates the query to structured FilterState
 * and shows a 1-sentence explanation so the user can confirm the interpretation
 * before applying.
 *
 * WHY ADDITIVE (not replace): existing filters in FilterChipStrip survive
 * when NL filters are applied — NL patches on top of the current state. This
 * lets analysts layer an NL quick-filter over a preset without losing context.
 *
 * WHY allowlist guard: the backend already validates field names against S3's
 * /screen/fields allowlist. The frontend strips unknown keys as a defence-in-depth
 * measure so malformed LLM responses cannot inject arbitrary filter keys into state.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (toggled by the "/" hotkey)
 * DATA SOURCE: POST /v1/screener/nl-translate via gateway
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Loader2, X } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { FilterState } from "@/features/screener/lib/filter-state";

// ── Filter conversion ─────────────────────────────────────────────────────────

/** Supported backend field → FilterState key mapping. */
const FIELD_LABELS: Record<string, string> = {
  pe_ratio: "P/E",
  pb_ratio: "P/B",
  price_sales_ttm: "P/S",
  dividend_yield: "Div Yield",
  roe_ttm: "ROE",
  profit_margin: "Net Margin",
  operating_margin_ttm: "Op Margin",
  quarterly_revenue_growth_yoy: "Rev Growth",
  quarterly_earnings_growth_yoy: "EPS Growth",
  market_capitalization: "Mkt Cap",
};

/** The set of backend field names we can convert to FilterState. */
const KNOWN_FIELDS = new Set(Object.keys(FIELD_LABELS).concat(["sector"]));

/** Extract numeric min/max from a condition object (LLM uses gte/lte/gt/lt). */
function getRange(v: unknown): { min?: number; max?: number } {
  if (typeof v === "number") return { min: v };
  if (typeof v === "object" && v !== null) {
    const obj = v as Record<string, unknown>;
    return {
      min:
        typeof obj.gte === "number"
          ? obj.gte
          : typeof obj.gt === "number"
            ? obj.gt
            : undefined,
      max:
        typeof obj.lte === "number"
          ? obj.lte
          : typeof obj.lt === "number"
            ? obj.lt
            : undefined,
    };
  }
  return {};
}

/** Convert backend filter dict to a FilterState patch. Unknown fields are skipped. */
function parseNLFilters(filters: Record<string, unknown>): Partial<FilterState> {
  const patch: Partial<FilterState> = {};
  for (const [field, value] of Object.entries(filters)) {
    if (!KNOWN_FIELDS.has(field)) continue;
    if (field === "sector" && typeof value === "string") {
      patch.sector = value;
      continue;
    }
    const { min, max } = getRange(value);
    switch (field) {
      case "pe_ratio":
        patch.peMin = min;
        patch.peMax = max;
        break;
      case "pb_ratio":
        patch.pbMin = min;
        patch.pbMax = max;
        break;
      case "price_sales_ttm":
        patch.psMin = min;
        patch.psMax = max;
        break;
      case "dividend_yield":
        patch.divYieldMin = min;
        patch.divYieldMax = max;
        break;
      case "roe_ttm":
        patch.roeMin = min;
        patch.roeMax = max;
        break;
      case "profit_margin":
        patch.netMarginMin = min;
        patch.netMarginMax = max;
        break;
      case "operating_margin_ttm":
        patch.opMarginMin = min;
        patch.opMarginMax = max;
        break;
      case "quarterly_revenue_growth_yoy":
        patch.revGrowthMin = min;
        patch.revGrowthMax = max;
        break;
      case "quarterly_earnings_growth_yoy":
        patch.earningsGrowthMin = min;
        patch.earningsGrowthMax = max;
        break;
    }
  }
  return patch;
}

/** Build human-readable chip labels from the backend filter dict. */
function buildChipLabels(filters: Record<string, unknown>): string[] {
  const chips: string[] = [];
  for (const [field, value] of Object.entries(filters)) {
    if (!KNOWN_FIELDS.has(field)) continue;
    if (field === "sector" && typeof value === "string") {
      chips.push(`Sector: ${value}`);
      continue;
    }
    const label = FIELD_LABELS[field] ?? field;
    const { min, max } = getRange(value);
    if (min != null && max != null) chips.push(`${label} ${min}–${max}`);
    else if (min != null) chips.push(`${label} ≥ ${min}`);
    else if (max != null) chips.push(`${label} ≤ ${max}`);
  }
  return chips;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface NLScreenerInputProps {
  /** Whether the bar is visible (controlled by parent "/" hotkey state). */
  visible: boolean;
  /** Called when the user confirms the NL-derived filters — merges into current state. */
  onApply: (patch: Partial<FilterState>) => void;
  /** Called when the user presses Escape or clicks the × button. */
  onDismiss: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NLScreenerInput({ visible, onApply, onDismiss }: NLScreenerInputProps) {
  const { accessToken } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [explanation, setExplanation] = useState("");
  const [chips, setChips] = useState<string[]>([]);
  const [pendingPatch, setPendingPatch] = useState<Partial<FilterState> | null>(null);

  // Focus the input whenever the bar becomes visible.
  useEffect(() => {
    if (visible) {
      inputRef.current?.focus();
    } else {
      // Clear state when hidden so reopening is a fresh experience.
      setQuery("");
      setExplanation("");
      setChips([]);
      setPendingPatch(null);
    }
  }, [visible]);

  const mutation = useMutation({
    mutationFn: (q: string) => createGateway(accessToken).translateNLScreenerQuery(q),
    onSuccess: (data) => {
      setExplanation(data.explanation ?? "");
      const patch = parseNLFilters(data.filters);
      setPendingPatch(patch);
      setChips(buildChipLabels(data.filters));
    },
  });

  const handleSubmit = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed) return;
    mutation.mutate(trimmed);
  }, [query, mutation]);

  const handleApply = useCallback(() => {
    if (!pendingPatch) return;
    onApply(pendingPatch);
    onDismiss();
  }, [pendingPatch, onApply, onDismiss]);

  if (!visible) return null;

  return (
    <div
      aria-label="Natural language screener"
      className="shrink-0 border-b border-border px-3 py-1.5 bg-background flex flex-col gap-1.5"
    >
      {/* ── Input row ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit();
            if (e.key === "Escape") onDismiss();
          }}
          placeholder="Describe what you're looking for, e.g. &quot;profitable tech stocks, P/E below 20&quot;"
          aria-label="Natural language screener query"
          className="flex-1 h-7 bg-input border border-border/40 rounded-[2px] px-2 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={mutation.isPending || !query.trim()}
          aria-label="Submit natural language query"
          className="h-7 w-7 flex items-center justify-center bg-primary/10 hover:bg-primary/20 text-primary rounded-[2px] border border-primary/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          ) : (
            <ArrowRight className="h-3 w-3" aria-hidden />
          )}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close natural language input"
          className="h-7 w-7 flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      </div>

      {/* ── Explanation line ────────────────────────────────────────────── */}
      {explanation && (
        <div className="flex items-start gap-1.5">
          <span className="text-[10px] font-mono text-muted-foreground shrink-0">
            Interpreted as:
          </span>
          <span className="text-[10px] font-mono text-foreground">{explanation}</span>
        </div>
      )}

      {/* ── Filter chip previews + Apply ─────────────────────────────── */}
      {chips.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          {chips.map((chip) => (
            <span
              key={chip}
              className="inline-flex items-center rounded-[2px] border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[10px] font-mono text-foreground whitespace-nowrap"
            >
              {chip}
            </span>
          ))}
          <button
            type="button"
            onClick={handleApply}
            aria-label="Apply NL-derived filters"
            className="ml-auto h-5 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/40 text-primary rounded-[2px] hover:bg-primary/20 transition-colors"
          >
            Apply
          </button>
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {mutation.isError && (
        <span
          role="alert"
          className="text-[10px] font-mono text-destructive"
        >
          Could not translate — try being more specific
        </span>
      )}
    </div>
  );
}
