/**
 * components/portfolio/ExportTransactionsButton.tsx — CSV export button for
 * the Transactions tab (PRD-0114 W5-T04).
 *
 * WHY THIS EXISTS: replaces the old client-side CSV generation in
 * TransactionsFilterBar (which only exported the currently-loaded page) with a
 * server-side streaming export that includes ALL filtered transactions regardless
 * of pagination state.
 *
 * HOW IT WORKS:
 *   1. User clicks "Export CSV"
 *   2. We fetch GET /v1/transactions/export?portfolio_id=...&from_date=...&...
 *      with the current filter params — the backend returns a streaming CSV
 *      with ALL matching rows (no pagination cap)
 *   3. We collect the response as a Blob and trigger a browser file download
 *      via URL.createObjectURL + programmatic <a> click
 *   4. On failure: show an error toast so the user knows the export didn't work
 *
 * WHY streaming download via Blob (not window.open or server redirect):
 *   - The S9 proxy requires the Authorization header — a bare window.open or
 *     <a href="..."> can't attach auth headers. Fetching with credentials and
 *     converting to a Blob is the standard pattern for auth-gated file downloads.
 *   - URL.createObjectURL + revokeObjectURL keeps the memory footprint bounded;
 *     the object URL is revoked after 100ms (enough for the browser to start
 *     the download) to avoid a permanent memory reference.
 *
 * WHY the "Export CSV" label stays fixed (no "Exporting..." label swap):
 *   The loading spinner next to the label communicates progress without forcing
 *   the button to resize, which would cause layout shift in the filter bar.
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 */

"use client";
// WHY "use client": uses fetch + Blob APIs (browser-only), onClick handler,
// and useState for the loading state.

import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BackendTransactionParams } from "@/features/portfolio/hooks/useTransactionsFilterState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ExportTransactionsButtonProps {
  /** The portfolio whose transactions to export. */
  portfolioId: string;
  /**
   * Current active filter state derived from useTransactionsFilterState().
   * These are forwarded as query params to the backend export endpoint so the
   * exported CSV matches exactly what the user is viewing in the table.
   */
  filter: BackendTransactionParams;
  /**
   * Auth token for the S9 gateway. The export endpoint requires the same
   * Bearer token as every other S9 call — we can't use window.open because
   * it can't attach headers.
   */
  accessToken?: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ExportTransactionsButton({
  portfolioId,
  filter,
  accessToken,
}: ExportTransactionsButtonProps) {
  // WHY useState for loading (not a ref): we need React to re-render to show
  // the spinner and disable the button during the fetch. A ref mutation would
  // not trigger a re-render.
  const [isLoading, setIsLoading] = useState(false);

  async function handleExport() {
    if (isLoading) return; // Prevent double-clicks while a download is in flight.

    setIsLoading(true);

    try {
      // ── Build the export URL with filter params ───────────────────────────
      // WHY URLSearchParams: handles encoding automatically. Filter params
      // (dates, tickers, types) are forwarded as query params.
      // portfolio_id is embedded in the PATH (not a query param) to match the
      // existing S9 route: GET /v1/portfolios/{portfolio_id}/transactions/export
      // A flat /v1/transactions/export?portfolio_id=... route does NOT exist in
      // S9 — using the path-param form ensures correct portfolio ownership checks.
      const qs = new URLSearchParams();

      // Forward the active date-range filters if set.
      // The backend maps these to CAST(executed_at AS DATE) comparisons.
      if (filter.from_date) qs.set("from_date", filter.from_date);
      if (filter.to_date) qs.set("to_date", filter.to_date);

      // Forward the ticker filter if set.
      // The backend does a case-insensitive prefix match (ILIKE ticker || '%').
      if (filter.ticker) qs.set("ticker", filter.ticker);

      // Forward transaction type filters. The server accepts repeated params
      // (transaction_type=BUY&transaction_type=SELL) which URLSearchParams
      // handles via .append().
      if (filter.transaction_type && filter.transaction_type.length > 0) {
        for (const t of filter.transaction_type) {
          qs.append("transaction_type", t);
        }
      }

      // WHY /api/v1/portfolios/{id}/transactions/export:
      // - The /api prefix is required for the Next.js → S9 rewrite rule
      //   (source: "/api/:path*"). A bare /v1/... path has no matching rewrite
      //   and hits the Next.js 404 handler before reaching S9.
      // - portfolio_id is a PATH segment, not a query param. S9 route:
      //   GET /v1/portfolios/{portfolio_id}/transactions/export
      //   The path-param form invokes the correct S1 ownership check.
      const url = `/api/v1/portfolios/${portfolioId}/transactions/export${qs.toString() ? `?${qs.toString()}` : ""}`;

      // ── Fetch with auth ───────────────────────────────────────────────────
      // WHY fetch (not apiFetch): apiFetch returns parsed JSON. The export
      // endpoint returns text/csv — we need the raw Response to read it as
      // a Blob without JSON.parse() mangling the content.
      const response = await fetch(url, {
        method: "GET",
        headers: {
          // Forward the Bearer token so S9 middleware can authenticate the request.
          // Without this the request gets a 401 even though the user is logged in.
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          // Tell the server we expect CSV — guards against accidental JSON fallback.
          Accept: "text/csv",
        },
      });

      if (!response.ok) {
        // Parse the error body if possible to give a useful toast message.
        let errorDetail = `HTTP ${response.status}`;
        try {
          const errJson = (await response.json()) as { detail?: string };
          if (errJson.detail) errorDetail = errJson.detail;
        } catch {
          // Ignore parse failures — the status code message is sufficient.
        }
        throw new Error(errorDetail);
      }

      // ── Convert streaming response to a downloadable Blob ─────────────────
      // WHY Blob (not text()): response.text() buffers the entire response in
      // memory as a JS string. For large exports (thousands of rows) this is
      // fine — we use Blob for consistency and to get the correct MIME type
      // for the browser download dialog.
      const blob = await response.blob();

      // ── FE-006: guard against empty-export (0 data rows) ──────────────────
      // WHY: a 200 response with only the CSV header row is a valid HTTP
      // success (response.ok=true) but produces a useless download. The
      // backend always emits the header line (~100 bytes) even for empty
      // result sets. We check blob.size against a generous threshold (512 bytes
      // = header + a handful of padding) to detect the header-only case without
      // being brittle to minor header wording changes.
      // WHY 512 bytes: the CSV header is ~90 chars; any real data row is at
      // least 30 chars. 512 gives a comfortable margin while still being well
      // below a single-row export (~200 bytes total).
      // WHY toast.info (not toast.warning): this is an expected outcome when
      // the user's filters are too narrow — it is informational, not an error.
      const HEADER_ONLY_THRESHOLD_BYTES = 512;
      if (blob.size <= HEADER_ONLY_THRESHOLD_BYTES) {
        toast.info("No transactions", {
          description: "No transactions match the current filters. Try broadening your date range or removing filters.",
        });
        return; // skip the download — setIsLoading(false) runs in finally
      }

      // ── Trigger browser download ───────────────────────────────────────────
      // WHY createObjectURL + programmatic click: the canonical approach for
      // downloading a file from a fetch response. The <a> gets a temporary
      // object URL pointing to the Blob in memory; clicking it triggers the
      // browser's native "Save As" dialog with the specified filename.
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;

      // Build a descriptive filename that includes the portfolio and date range
      // so exports from different time windows don't overwrite each other in
      // the Downloads folder.
      const today = new Date().toISOString().slice(0, 10);
      const fromPart = filter.from_date ? `_from-${filter.from_date}` : "";
      const toPart = filter.to_date ? `_to-${filter.to_date}` : "";
      anchor.download = `transactions_${portfolioId.slice(0, 8)}${fromPart}${toPart}_${today}.csv`;

      // The anchor must be in the DOM for Firefox to trigger the download.
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);

      // Revoke the object URL after a short delay — the browser needs the URL
      // to remain valid for the download to start (immediate revoke cancels it).
      // 100ms is enough for the browser's download machinery to begin.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 100);

    } catch (error) {
      // Show a user-facing error toast with the failure reason.
      // WHY not re-throw: the user doesn't need to see a crash page for a
      // failed CSV export — a toast explaining the problem is sufficient and
      // lets them retry without navigating away.
      const message =
        error instanceof Error ? error.message : "Export failed. Please try again.";
      toast.error("CSV export failed", {
        // WHY no duration override: centralized Toaster in app/providers.tsx
        // sets duration=4000 for all toasts (DESIGN_SYSTEM.md §6.16 + toast-config.test.ts).
        description: message,
      });
    } finally {
      // Always clear the loading state so the button is re-enabled even if
      // the download failed — the user should be able to retry.
      setIsLoading(false);
    }
  }

  return (
    // WHY variant="outline": matches the Bloomberg terminal's secondary action
    // style — a subtle border keeps the export button from visually competing
    // with the primary "Add Position" CTA.
    <Button
      variant="outline"
      size="sm"
      // WHY h-6: 24px height matches the filter bar's control height (type pills,
      // date inputs, Reset button) so the export button integrates without
      // introducing a height mismatch that would force the row taller.
      className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] rounded-[2px]"
      onClick={() => void handleExport()}
      // WHY disabled during loading: prevents a second concurrent export request.
      // The spinner already communicates "in progress" visually; the disabled
      // state prevents keyboard/screenreader activation of the same action twice.
      disabled={isLoading}
      aria-label="Export filtered transactions as CSV"
    >
      {isLoading && (
        // Spinner replaces the leading icon slot while the download is in progress.
        // WHY animate-spin on Loader2: standard Next.js / shadcn loading pattern —
        // h-3 w-3 keeps it the same size as the button text so the layout doesn't shift.
        <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden="true" />
      )}
      Export CSV
    </Button>
  );
}
