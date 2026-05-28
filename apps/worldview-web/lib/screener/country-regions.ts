/**
 * lib/screener/country-regions.ts — Regional ISO3 country-code presets
 *
 * WHY THIS EXISTS: PRD-0089 Wave I-B Block IB-L1 (OQ-9) asks for four
 * regional preset chips above the multi-select Country combobox so analysts
 * can apply "North America" or "EM" with one click rather than tapping
 * three or fifteen individual ISO codes. The Wave L-1 backend stores the
 * country on `instruments.country` as an ISO 3-letter code, so the chip
 * just expands to a `string[]` we feed into FilterState.countries.
 *
 * WHY a static list (not fetched from S9): the `screen_field_metadata`
 * seed (services/market-data/src/market_data/app.py L168) declares
 * `field_type="text"` for `country` — it does NOT enumerate the allowed
 * values. The plan explicitly allows a "static ISO3 list of ~50 common
 * codes" fallback when the allowlist hook is unavailable. This list
 * matches what the EODHD universe carries today.
 *
 * GROUPING CONVENTIONS:
 *   NA   — USA / Canada / Mexico (NAFTA / USMCA).
 *   EU   — Western + Northern + Mediterranean Europe (developed-market
 *          MSCI Europe constituents).
 *   APAC — Developed APAC (JPN/AUS/NZL/SGP/HKG/KOR/TWN) + China cohort.
 *   EM   — MSCI Emerging Markets index (~24 countries, abridged to the
 *          ones with at least one EODHD-supported exchange).
 *   India and China appear in both APAC and EM intentionally — that
 *   mirrors how index providers double-classify them and what an analyst
 *   running "EM screen including BRIC" would expect.
 */

export interface CountryRegion {
  /** Stable ID — used as React key + active-chip lookup. */
  id: "NA" | "EU" | "APAC" | "EM";
  /** Display label (short — chip is 22px tall). */
  label: string;
  /** ISO 3-letter country codes the chip expands into. */
  iso3: readonly string[];
}

export const COUNTRY_REGIONS: readonly CountryRegion[] = Object.freeze([
  {
    id: "NA",
    label: "NA",
    iso3: ["USA", "CAN", "MEX"],
  },
  {
    id: "EU",
    label: "EU",
    iso3: [
      "DEU",
      "FRA",
      "GBR",
      "ITA",
      "ESP",
      "NLD",
      "CHE",
      "SWE",
      "NOR",
      "DNK",
      "FIN",
      "BEL",
      "AUT",
      "POL",
      "IRL",
      "PRT",
      "GRC",
    ],
  },
  {
    id: "APAC",
    label: "APAC",
    iso3: [
      "JPN",
      "CHN",
      "HKG",
      "TWN",
      "KOR",
      "SGP",
      "AUS",
      "NZL",
      "IND",
      "THA",
      "MYS",
      "IDN",
      "PHL",
      "VNM",
    ],
  },
  {
    id: "EM",
    label: "EM",
    iso3: [
      "BRA",
      "MEX",
      "ARG",
      "COL",
      "CHL",
      "PER",
      "RUS",
      "TUR",
      "ZAF",
      "EGY",
      "NGA",
      "SAU",
      "ARE",
      "ISR",
      "IND",
      "CHN",
      "IDN",
      "PHL",
      "THA",
      "MYS",
      "VNM",
    ],
  },
]);

/**
 * COMMON_COUNTRY_ISO3 — Flat de-duplicated union of every preset's
 * country list — used as the default option list for the multi-select
 * combobox when the `screen_field_metadata` allowlist hook is not wired.
 *
 * WHY a frozen union (not a separate ~250-entry ISO3 master list): the
 * combobox is for portfolio screening, not a country picker. Showing the
 * 50-odd countries that actually have tradeable equities on the platform
 * is more useful than scrolling past Antarctica. Future Wave L-x flip
 * lands a hook against the live `screen_field_metadata` rows and this
 * fallback becomes dead code (lint will flag it for removal).
 */
export const COMMON_COUNTRY_ISO3: readonly string[] = Object.freeze(
  Array.from(new Set(COUNTRY_REGIONS.flatMap((r) => r.iso3))).sort(),
);
