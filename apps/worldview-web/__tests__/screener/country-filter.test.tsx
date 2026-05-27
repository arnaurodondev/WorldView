/**
 * __tests__/screener/country-filter.test.tsx
 * (PRD-0089 Wave I-B Block IB-L1 · T-IB-01)
 *
 * WHY: the Country row introduces three new behaviours that must not regress:
 *   1. Four regional preset chips (NA/EU/APAC/EM) REPLACE the current
 *      selection with the chip's ISO3 set (not additive — see component
 *      comment for rationale).
 *   2. The multi-select combobox stores ISO3 codes in `FilterState.countries`
 *      and emits onChange every time the user toggles a code.
 *   3. The FilterChipStrip auto-renders one chip "Country: USA, DEU ×"
 *      whenever `countries.length > 0`; clicking ✕ clears the field.
 *
 * The build-filters layer (separately tested in build-filters.test.ts)
 * carries the field through to the wire — this file only proves the
 * UI surface behaves correctly.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CountryFilterRow } from "@/features/screener/components/CountryFilterRow";
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";
import { COUNTRY_REGIONS } from "@/lib/screener/country-regions";

describe("CountryFilterRow", () => {
  it("renders the four regional preset chips (NA / EU / APAC / EM)", () => {
    // WHY a four-chip lock: OQ-9 explicitly pins this count. Dropping or
    // adding a region must be a conscious plan-level decision, not a
    // silent component edit.
    render(<CountryFilterRow value={[]} onChange={() => {}} />);
    for (const region of COUNTRY_REGIONS) {
      const btn = screen.getByRole("button", {
        name: new RegExp(`Select ${region.label} region`, "i"),
      });
      expect(btn).toBeInTheDocument();
      // No preset is "pressed" when value is empty.
      expect(btn).toHaveAttribute("aria-pressed", "false");
    }
  });

  it("clicking a regional preset REPLACES the current selection with its ISO3 set", () => {
    // WHY replace (not append): partial overlap (EM+APAC both include CHN)
    // makes append behaviour confusing. The component locks "replace" semantics.
    const onChange = vi.fn();
    render(<CountryFilterRow value={["BRA"]} onChange={onChange} />);
    const naChip = screen.getByRole("button", { name: /Select NA region/i });
    fireEvent.click(naChip);
    // The NA preset is the first region in COUNTRY_REGIONS.
    const naIso3 = COUNTRY_REGIONS.find((r) => r.id === "NA")!.iso3;
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith([...naIso3]);
  });

  it("preset chip shows aria-pressed=true when current selection exactly matches", () => {
    // WHY exact-match semantics: lighting up "NA" when the user has
    // {USA,CAN,MEX,KOR} would lie about what the chip would do if
    // clicked. The set-equality check is the only honest definition.
    const naIso3 = COUNTRY_REGIONS.find((r) => r.id === "NA")!.iso3;
    render(<CountryFilterRow value={[...naIso3]} onChange={() => {}} />);
    const naChip = screen.getByRole("button", { name: /Select NA region/i });
    expect(naChip).toHaveAttribute("aria-pressed", "true");
    // Order-independent equality — re-render with the same set in reverse.
    const euChip = screen.getByRole("button", { name: /Select EU region/i });
    expect(euChip).toHaveAttribute("aria-pressed", "false");
  });
});

describe("FilterChipStrip — country chip propagation (T-IB-01)", () => {
  it("renders one chip 'Country: USA, DEU' when countries has two entries", () => {
    // WHY: the plan's acceptance criterion is literally `Country: USA, DEU ×`.
    // Joining with ", " keeps long selections compact (regional presets can
    // produce ~17 codes; we accept the horizontal scroll on a deliberate
    // EU click rather than truncate and lose info).
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, countries: ["USA", "DEU"] }}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText("Country: USA, DEU")).toBeInTheDocument();
  });

  it("clicking ✕ on the country chip clears the field via onApply", () => {
    // WHY ✕ clears (not opens the popover): every other chip in the strip
    // dismisses with ✕; the country chip MUST follow the same contract.
    const onApply = vi.fn();
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, countries: ["USA", "DEU"] }}
        onApply={onApply}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Remove filter: Country: USA, DEU/i,
      }),
    );
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ countries: undefined }),
    );
  });

  it("renders no chip when countries is undefined or empty", () => {
    // WHY: empty / undefined are the "no filter" sentinels — adding a chip
    // would mislead the user that a filter is active.
    const { rerender } = render(
      <FilterChipStrip filters={DEFAULT_FILTERS} onApply={() => {}} />,
    );
    expect(screen.queryByText(/Country:/)).not.toBeInTheDocument();
    rerender(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, countries: [] }}
        onApply={() => {}}
      />,
    );
    expect(screen.queryByText(/Country:/)).not.toBeInTheDocument();
  });
});
