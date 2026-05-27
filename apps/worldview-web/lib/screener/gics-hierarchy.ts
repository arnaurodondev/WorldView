/**
 * lib/screener/gics-hierarchy.ts — Static GICS sector → industry hierarchy
 * (PRD-0089 Wave I-A · Block B · T-IA-04)
 *
 * WHY THIS EXISTS:
 *   The screener filter popover (OQ-10) lets users narrow by sector AND by
 *   industry. The industry combobox must only show industries that belong
 *   to the currently-selected sector(s) — otherwise a user could pick e.g.
 *   "Banks" while sector=Energy and produce 0 results.
 *
 *   We resolve this client-side with a static GICS map. The Global Industry
 *   Classification Standard 4th-level taxonomy only revises every few years
 *   (last meaningful revision: 2018 — `Real Estate` split + Communication
 *   Services rename); shipping it as a static TypeScript module is cheaper
 *   than an extra S9 round-trip per popover open.
 *
 * SOURCE OF TRUTH:
 *   - GICS 2018 4th-level codes (post-Communication-Services renaming).
 *   - 11 sectors × ~6 industry groups per sector ≈ ~70 industry entries.
 *   - Captured verbatim from the public MSCI / S&P methodology document
 *     (https://www.msci.com/our-solutions/indexes/gics).
 *   - Sector names exactly match `features/screener/lib/filter-state.ts`
 *     `GICS_SECTORS`. Industry strings use the canonical capitalisation.
 *
 * ANNUAL AUDIT REMINDER:
 *   GICS reclassifications happen at most once per quarter. If MSCI/S&P
 *   announce a 2027+ revision, update this file and bump the date header.
 *   Mismatches surface as combobox "no matches" — a graceful empty state.
 *
 * WHO USES IT:
 *   - `components/screener/ScreenerFilterBar.tsx` (industry combobox cascade).
 *   - Future: any UI that needs to filter or label by GICS taxonomy.
 *
 * PLAN REF: docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-04
 * GICS DATA DATE: 2018-09 revision (verified 2026-05-26 against MSCI docs).
 */

// WHY: each tuple's first element matches `GICS_SECTORS` in
// `features/screener/lib/filter-state.ts` exactly. Drift here will
// silently break the cascade — a unit test pins this contract.
export type GICSSector =
  | "Energy"
  | "Materials"
  | "Industrials"
  | "Consumer Discretionary"
  | "Consumer Staples"
  | "Health Care"
  | "Financials"
  | "Information Technology"
  | "Communication Services"
  | "Utilities"
  | "Real Estate";

/**
 * GICS_HIERARCHY — sector → industries map.
 *
 * WHY a frozen plain object (not a Map): TypeScript discriminates string
 * literal keys natively. A Map adds runtime overhead with no type benefit.
 * Object.freeze prevents accidental mutation at runtime; the `as const`
 * gives the compiler the narrow tuple type for each value.
 */
export const GICS_HIERARCHY = Object.freeze({
  Energy: [
    "Oil & Gas Drilling",
    "Oil & Gas Equipment & Services",
    "Integrated Oil & Gas",
    "Oil & Gas Exploration & Production",
    "Oil & Gas Refining & Marketing",
    "Oil & Gas Storage & Transportation",
    "Coal & Consumable Fuels",
  ],
  Materials: [
    "Commodity Chemicals",
    "Diversified Chemicals",
    "Fertilizers & Agricultural Chemicals",
    "Industrial Gases",
    "Specialty Chemicals",
    "Construction Materials",
    "Metal & Glass Containers",
    "Paper Packaging",
    "Aluminum",
    "Diversified Metals & Mining",
    "Gold",
    "Steel",
    "Forest Products",
    "Paper Products",
  ],
  Industrials: [
    "Aerospace & Defense",
    "Building Products",
    "Construction & Engineering",
    "Electrical Components & Equipment",
    "Industrial Machinery",
    "Trading Companies & Distributors",
    "Commercial Printing",
    "Environmental & Facilities Services",
    "Office Services & Supplies",
    "Diversified Support Services",
    "Security & Alarm Services",
    "Human Resource & Employment Services",
    "Research & Consulting Services",
    "Air Freight & Logistics",
    "Airlines",
    "Marine",
    "Railroads",
    "Trucking",
  ],
  "Consumer Discretionary": [
    "Auto Parts & Equipment",
    "Automobile Manufacturers",
    "Motorcycle Manufacturers",
    "Consumer Electronics",
    "Home Furnishings",
    "Homebuilding",
    "Household Appliances",
    "Housewares & Specialties",
    "Leisure Products",
    "Apparel, Accessories & Luxury Goods",
    "Footwear",
    "Textiles",
    "Hotels, Resorts & Cruise Lines",
    "Restaurants",
    "Education Services",
    "Specialized Consumer Services",
    "Distributors",
    "Internet & Direct Marketing Retail",
    "Department Stores",
    "General Merchandise Stores",
    "Apparel Retail",
    "Computer & Electronics Retail",
    "Home Improvement Retail",
    "Specialty Stores",
    "Automotive Retail",
  ],
  "Consumer Staples": [
    "Drug Retail",
    "Food Distributors",
    "Food Retail",
    "Hypermarkets & Super Centers",
    "Brewers",
    "Distillers & Vintners",
    "Soft Drinks",
    "Agricultural Products",
    "Packaged Foods & Meats",
    "Tobacco",
    "Household Products",
    "Personal Products",
  ],
  "Health Care": [
    "Health Care Equipment",
    "Health Care Supplies",
    "Health Care Distributors",
    "Health Care Services",
    "Health Care Facilities",
    "Managed Health Care",
    "Health Care Technology",
    "Biotechnology",
    "Pharmaceuticals",
    "Life Sciences Tools & Services",
  ],
  Financials: [
    "Diversified Banks",
    "Regional Banks",
    "Thrifts & Mortgage Finance",
    "Consumer Finance",
    "Diversified Capital Markets",
    "Investment Banking & Brokerage",
    "Asset Management & Custody Banks",
    "Financial Exchanges & Data",
    "Mortgage REITs",
    "Insurance Brokers",
    "Life & Health Insurance",
    "Multi-line Insurance",
    "Property & Casualty Insurance",
    "Reinsurance",
  ],
  "Information Technology": [
    "Application Software",
    "Systems Software",
    "Internet Services & Infrastructure",
    "IT Consulting & Other Services",
    "Data Processing & Outsourced Services",
    "Communications Equipment",
    "Technology Hardware, Storage & Peripherals",
    "Electronic Equipment & Instruments",
    "Electronic Components",
    "Electronic Manufacturing Services",
    "Technology Distributors",
    "Semiconductor Equipment",
    "Semiconductors",
  ],
  "Communication Services": [
    "Alternative Carriers",
    "Integrated Telecommunication Services",
    "Wireless Telecommunication Services",
    "Advertising",
    "Broadcasting",
    "Cable & Satellite",
    "Publishing",
    "Movies & Entertainment",
    "Interactive Home Entertainment",
    "Interactive Media & Services",
  ],
  Utilities: [
    "Electric Utilities",
    "Gas Utilities",
    "Multi-Utilities",
    "Water Utilities",
    "Independent Power Producers & Energy Traders",
    "Renewable Electricity",
  ],
  "Real Estate": [
    "Diversified REITs",
    "Industrial REITs",
    "Hotel & Resort REITs",
    "Office REITs",
    "Health Care REITs",
    "Residential REITs",
    "Retail REITs",
    "Specialized REITs",
    "Diversified Real Estate Activities",
    "Real Estate Operating Companies",
    "Real Estate Development",
    "Real Estate Services",
  ],
} as const) satisfies Readonly<Record<GICSSector, readonly string[]>>;

/**
 * industriesForSectors — return the union of industries belonging to the
 * given sectors. Preserves order: sectors are walked in the array's order
 * and industries inside each sector keep their GICS-defined order. Unknown
 * sector names are silently skipped (graceful — see header note).
 *
 * @example
 *   industriesForSectors(["Information Technology"]).length // 13
 *   industriesForSectors([]) // [] (caller's choice to fall back to allowlist)
 */
export function industriesForSectors(sectors: readonly string[]): string[] {
  const result: string[] = [];
  for (const sector of sectors) {
    // WHY: cast to GICSSector at runtime — typing the input as a wider
    // `string[]` lets callers pass whatever the form state holds without
    // pre-narrowing. We just skip anything that isn't a known sector key.
    const industries = (GICS_HIERARCHY as Readonly<Record<string, readonly string[]>>)[sector];
    if (!industries) continue;
    for (const industry of industries) {
      if (!result.includes(industry)) result.push(industry);
    }
  }
  return result;
}
