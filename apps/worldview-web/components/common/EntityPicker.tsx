/**
 * components/common/EntityPicker.tsx — shared debounced KG-entity autocomplete
 * (PLAN-0113 Wave 4, T-4-02).
 *
 * WHY THIS EXISTS / PROVENANCE:
 * This was originally an inline `EntityPicker` function inside
 * `components/intelligence/PathBetweenPanel.tsx`. PLAN-0113 needs the SAME picker
 * in the alert condition editors (news-volume, news-momentum, and the
 * KG-connection editor which mounts TWO of them). Rather than duplicate it, we
 * extract it here as the single shared primitive and re-point PathBetweenPanel to it.
 *
 * WHY `searchFundamentals` (not `searchInstruments`):
 * The reliable KG `entity_id` only comes from `searchFundamentals` — it runs an
 * S3 instrument search, then enriches each candidate via the company-overview
 * endpoint to attach the REAL `entity_id` from S7 (see lib/api/search.ts). The
 * alert backend keys news/momentum/connection rules on `entity_id`, so posting a
 * raw instrument_id would silently fail. `searchInstruments` returns
 * `entity_id = instrument_id` (a fallback) and is NOT safe for these rules.
 *
 * UX CONTRACT (unchanged from the original inline picker):
 *   - 300ms debounce; only searches at >= 2 chars AND when nothing is selected
 *   - Selected state renders a chip with a clear (×) button
 *   - Result rows show ticker (primary) + name (secondary)
 *
 * DESIGN: Midnight Pro dark palette, shadcn/ui (Input + Skeleton) only.
 */

"use client";
// WHY "use client": uses useState (picker + query state), the debounce hook, and
// TanStack Query — all browser-only.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { useDebounce } from "@/hooks/useDebounce";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { SearchResult } from "@/types/api";

/**
 * ChosenEntity — the minimal shape we keep once an entity is picked. We only
 * need the id (for the backend payload) + a display name (for the chip).
 */
export interface ChosenEntity {
  entityId: string;
  name: string;
}

export interface EntityPickerProps {
  /** Field label shown above the input / chip (e.g. "Source", "Entity"). */
  label: string;
  /** Currently-selected entity, or null when nothing is chosen yet. */
  value: ChosenEntity | null;
  /** Called with the chosen entity (carrying the REAL entity_id). */
  onSelect: (entity: ChosenEntity) => void;
  /** Called when the user clears the current selection. */
  onClear: () => void;
  /** Optional placeholder for the search input. */
  placeholder?: string;
}

/**
 * EntityPicker — debounced search box → results dropdown → onSelect, or a chip +
 * clear button once a value is chosen. Returns the REAL KG `entity_id`.
 */
export function EntityPicker({
  label,
  value,
  onSelect,
  onClear,
  placeholder = "Search entity…",
}: EntityPickerProps) {
  const gw = useApiClient();
  const [query, setQuery] = useState("");
  // Debounce so we only hit S9 when the user pauses typing (same 300ms as the
  // global search). Empty / very short queries never fire.
  const debounced = useDebounce(query, 300);

  // WHY the enabled gate (length>=2 AND value===null): don't search while a value
  // is already chosen (the input is hidden then) and skip 1-char noise.
  const { data, isFetching } = useQuery({
    queryKey: ["entity-picker-search", debounced],
    // searchFundamentals enriches each candidate with the REAL KG entity_id.
    queryFn: () => gw.searchFundamentals(debounced, 8),
    enabled: debounced.trim().length >= 2 && value === null,
    staleTime: 60_000,
  });

  // ── Selected state: chip + clear button ──────────────────────────────────
  if (value) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className="flex items-center gap-2 rounded-[2px] border border-primary/40 bg-primary/10 px-2 py-1">
          <span className="flex-1 truncate text-[11px] font-mono text-primary">
            {value.name}
          </span>
          <button
            type="button"
            onClick={() => {
              onClear();
              setQuery("");
            }}
            className="text-[12px] leading-none text-muted-foreground hover:text-foreground"
            aria-label={`Clear ${label}`}
          >
            ×
          </button>
        </div>
      </div>
    );
  }

  // ── Unselected state: search input + results dropdown ────────────────────
  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        className="h-7 text-[11px]"
        aria-label={`${label} entity search`}
      />

      {/* Results dropdown — only when the user has typed enough to search. */}
      {debounced.trim().length >= 2 && (
        <div className="absolute top-full z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-[2px] border border-border/60 bg-popover shadow-lg">
          {isFetching && (
            <div className="space-y-1 p-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-full" />
            </div>
          )}
          {!isFetching && (data?.results.length ?? 0) === 0 && (
            <p className="p-2 font-mono text-[10px] text-muted-foreground">
              No matching entities
            </p>
          )}
          {!isFetching &&
            (data?.results ?? []).map((r: SearchResult) => (
              <button
                key={r.entity_id}
                type="button"
                onClick={() => onSelect({ entityId: r.entity_id, name: r.name })}
                className="block w-full px-2 py-1 text-left text-[11px] font-mono text-foreground/90 hover:bg-muted/60"
              >
                <span className="text-primary">{r.ticker}</span>
                {"  "}
                <span className="text-foreground/70">{r.name}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
