/**
 * hooks/useNlScreenerTranslate.ts — natural-language → screener filters mutation.
 *
 * WHY A HOOK (not an inline useMutation in the page): keeps the page focused on
 * orchestration, and lets the NL search box own its own loading/error state.
 *
 * WHY useMutation (not useQuery): translating a query is an explicit user ACTION
 * (submit), not a declarative read that should auto-fetch on mount. TanStack's
 * mutation model gives us mutate()/isPending/error/data out of the box and never
 * fires until the user submits.
 *
 * DATA FLOW:
 *   user types prompt → mutate(prompt) → POST /v1/screener/nl-translate
 *   → backend returns ScreenerFilter[] → page maps them back into a FilterState
 *   (nlFiltersToFilterState) and applies them through the normal pipeline.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { ScreenerFilter } from "@/types/api";

export interface NlTranslateResult {
  filters: ScreenerFilter[];
  explanation?: string;
}

/**
 * useNlScreenerTranslate — returns a TanStack mutation that translates a
 * plain-English screen prompt into structured ScreenerFilter[].
 *
 * The caller invokes `mutate(query)` / `mutateAsync(query)` and reads
 * `isPending` / `error` / `data` to drive the NL search box UI.
 */
export function useNlScreenerTranslate() {
  const { accessToken } = useAuth();

  return useMutation<NlTranslateResult, Error, string>({
    mutationFn: async (query: string) => {
      // WHY trim + guard: an empty/whitespace prompt should never hit the
      // backend (a wasted LLM call). The component also guards, but defending
      // here keeps the hook safe regardless of caller.
      const trimmed = query.trim();
      if (!trimmed) return { filters: [] };
      return createGateway(accessToken).nlTranslate(trimmed);
    },
  });
}
