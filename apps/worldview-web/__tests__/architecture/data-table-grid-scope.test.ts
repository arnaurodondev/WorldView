/**
 * Architecture test — PRD-0089 F1 `data-table-grid` opt-in scope
 *
 * WHY THIS EXISTS: F1 §16.3 limits the `data-table-grid` opt-in wrapper to
 * seven approved v1 surfaces (Screener results, Holdings table, Transactions
 * ledger, Financials FlatMetricsGrid, Watchlist, Workspace data panels, Peer
 * Comparison).  The wrapper drives 20px row + 6px cell-padding contract
 * globally — applying it to a non-tabular surface (a CTA card, a brief
 * panel) collapses spacing in surprising ways.
 *
 * This test walks the .tsx tree and asserts every `data-table-grid` usage
 * sits inside one of the 7 whitelisted surface files (or their descendants).
 * New surfaces require a deliberate amendment to this allowlist.
 *
 * SCOPE: matches `data-table-grid` attribute literals only (not the CSS
 * selector form, which lives in `app/globals.css`).
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SCAN_ROOTS = ["app", "components", "lib", "hooks", "features", "contexts"];

// Whitelisted v1 surfaces — relative-path substrings.  Matching is by
// substring rather than equality because each surface owns multiple files
// (header, body, footer) and they all legitimately wear the wrapper.
//
// HOW TO EXTEND: add a new substring here only when the Design System §16.3
// table grows.  Each entry must correspond to a tabular surface where the
// 20px row contract is desirable.
const ALLOWED_SURFACES: readonly string[] = [
  // 1. Screener results table
  "components/screener/",
  "features/screener/",
  "app/(app)/screener/",
  // 2. Holdings table + 3. Transactions ledger (both live under portfolio/)
  "components/portfolio/",
  "features/portfolio/",
  "app/(app)/portfolio/",
  // 4. Financials tab surfaces: DenseMetricsGrid, IncomeStatementTable,
  //    EarningsBarChart, PeerComparisonTable, InsiderTransactionsTable,
  //    InstitutionalHoldersTable, FundHoldersTable (all data-table-grid opt-in).
  "components/instrument/financials/",
  // 4b. W5 Quote-tab density surfaces (PRD-0089 W5, §1.6):
  //   MultiPeriodReturnsStrip, IntradayStatsBand, MetricGrid4Col, CompanyAboutCard,
  //   InsiderActivityList, EarningsMiniList, RelatedHeadlinesList,
  //   PeersStrip, PriceLevelsStrip, WhatsMovingStrip (all data-table-grid opt-in).
  "components/instrument/quote/",
  // 5. Watchlist — both the future /watchlists page surface AND the global
  // shell sidebar panel. PRD-0089 W1 §4.5 adopts data-table-grid on the
  // sidebar so its rows inherit the 20px row height token (FU-5.5 explicitly
  // lists "Watchlist" among the 7 v1 surfaces).
  "components/watchlists/",
  "app/(app)/watchlists/",
  "components/shell/WatchlistPanel.tsx",
  // 6. Workspace data panels
  "components/workspace/",
  "app/(app)/workspace/",
  // 7. Peer Comparison (lives under instrument/intelligence per current layout)
  "components/instrument/intelligence/",
  // Test fixtures legitimately need the attribute to verify behaviour.
  "__tests__/",
  // The arch test file itself contains the attribute as a regex literal.
  "__tests__/architecture/data-table-grid-scope.test.ts",
];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
      out.push(path);
    }
  }
  return out;
}

// Strip comments before scanning so explanatory references in `// the
// data-table-grid wrapper drives row height …` style WHY blocks don't
// produce false positives.  Newlines preserved to keep line numbers stable.
function stripComments(content: string): string {
  let s = content;
  s = s.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
  return s;
}

// Match `data-table-grid` as an HTML/JSX attribute name (boundaries on both
// sides to avoid e.g. `data-table-grid-row` false-positives).
const ATTR_RE = /\bdata-table-grid(?:=|\b)/;

function findOutOfScopeUsages(): { file: string; line: number; text: string }[] {
  const offences: { file: string; line: number; text: string }[] = [];
  for (const root of SCAN_ROOTS) {
    let files: string[];
    try {
      files = walk(root);
    } catch {
      continue;
    }
    for (const file of files) {
      // Whitelist match: any allowed substring → skip.
      if (ALLOWED_SURFACES.some((s) => file.includes(s))) continue;
      const raw = readFileSync(file, "utf-8");
      const stripped = stripComments(raw);
      const rawLines = raw.split("\n");
      const strippedLines = stripped.split("\n");
      for (let i = 0; i < strippedLines.length; i++) {
        const codeLine = strippedLines[i] ?? "";
        if (codeLine.trim().length === 0) continue;
        if (ATTR_RE.test(codeLine)) {
          offences.push({ file, line: i + 1, text: (rawLines[i] ?? "").trim() });
        }
      }
    }
  }
  return offences;
}

describe("architecture: PRD-0089 F1 data-table-grid scope", () => {
  it("data-table-grid only appears in the 7 whitelisted v1 surfaces", () => {
    const offences = findOutOfScopeUsages();
    if (offences.length > 0) {
      const detail = offences
        .map((o) => `${o.file}:${o.line}  ${o.text}`)
        .join("\n");
      throw new Error(
        `Found ${offences.length} out-of-scope data-table-grid usages:\n${detail}\n\n` +
          `Either move the surface under one of the 7 whitelisted paths, or extend ` +
          `ALLOWED_SURFACES in this test file with a written justification.`,
      );
    }
    expect(offences).toEqual([]);
  });
});
