/**
 * components/alerts/alert-row-content.ts — pure helpers that turn a single
 * `Alert` payload into the distinct, scannable columns the Alerts list renders.
 *
 * WHY THIS EXISTS (roadmap item #2 / DESIGN-QA A-1 / FUNCTIONAL B2):
 * The Alerts page used to render ~30 visually identical rows
 *   `TICKER · GRAPH_CHANGE · MEDIUM signal · …large dead gap… · 5m · [ACK ▾]`
 * with no "what changed" body and a big empty horizontal band. The audit's fix
 * is: surface the one-line "what changed" summary (the content the sidebar
 * ALARMS panel already shows) into that dead space, plus a humanised type chip,
 * so each row is differentiated and scannable.
 *
 * These functions are intentionally **pure** (no React, no hooks, no DOM) so
 * they are trivially unit-testable and can never silently diverge from the
 * sidebar's `formatAlertTitle` — we reuse it directly as the summary source.
 *
 * DATA REALITY (see types/api.ts `Alert`): the only reliably-populated,
 * differentiating fields are `severity`, `alert_type`, `ticker` / `entity_name`,
 * `created_at`, and the composed `title` / `signal_label`. `body` is frequently
 * empty on post-PLAN-0048 alerts, and there is NO typed threshold/value/
 * condition field on the Alert payload (those live only on AlertRule, the rule
 * *definition*). So we compose the summary from whatever IS present and only
 * opportunistically read free-form `payload` keys — never inventing data. Any
 * structured "value vs threshold" rendering is a backend follow-up (noted in
 * the implementation report), not faked here.
 */

import { formatAlertTitle } from "@/lib/alerts/format";
import type { Alert } from "@/types/api";

// ── Type label ────────────────────────────────────────────────────────────────

/**
 * humaniseAlertType — turn a raw `alert_type` token into a compact, scannable
 * label for the TYPE column.
 *
 * WHY: the old row printed the raw token (`GRAPH_CHANGE`, `PRICE_MOVE`) verbatim
 * — screaming-snake-case is hard to scan and looks like a debug string. We
 * upper-case + space it into a terminal-style tag ("GRAPH CHANGE", "PRICE MOVE")
 * so the TYPE column reads as a deliberate, denser classifier rather than a leak
 * of the backend enum.
 *
 * WHY keep it UPPERCASE (not Title Case): the row's TYPE column is a chrome-style
 * classifier tag (like a Bloomberg field code), so all-caps + letter-spacing in
 * the component reads as a label, not prose. The summary column carries the
 * human-readable prose instead.
 */
export function humaniseAlertType(alertType: string | null | undefined): string {
  if (!alertType) return "";
  return alertType.replace(/_/g, " ").trim().toUpperCase();
}

// ── Row subject (ticker / entity) ──────────────────────────────────────────────

/**
 * alertSubject — the entity the alert is *about*, for the dedicated subject
 * column. Prefers the ticker (traders scan by ticker), falling back to the
 * entity name, then any ticker/entity embedded in the free-form payload (legacy
 * alerts persisted enrichment there before the top-level columns existed).
 *
 * Returns `null` when no subject is known so the caller can render the `—` null
 * sentinel instead of an empty cell (DESIGN_SYSTEM null-handling rule).
 */
export function alertSubject(alert: Alert): string | null {
  if (alert.ticker) return alert.ticker;
  if (alert.entity_name) return alert.entity_name;
  const payload = (alert.payload ?? {}) as Record<string, unknown>;
  if (typeof payload.ticker === "string" && payload.ticker) return payload.ticker;
  if (typeof payload.entity_name === "string" && payload.entity_name) return payload.entity_name;
  return null;
}

// ── "What changed" summary ──────────────────────────────────────────────────────

/**
 * alertSummary — the one-line "what changed" string that fills the previously
 * dead horizontal band, making each row differentiated and scannable.
 *
 * Priority (first non-empty wins):
 *   1. `alert.body`        — the richest "what changed" prose when populated
 *                            (e.g. "Tesla critical news signal detected — …").
 *   2. `formatAlertTitle`  — the SAME composer the sidebar ALARMS panel + the
 *                            dashboard RecentAlerts use, so the three surfaces
 *                            never drift. It walks title → signal_label → subject
 *                            → payload.message → humanised type, and is
 *                            *guaranteed* never to return a bare "<SEV> signal"
 *                            string (regression F-D-006).
 *
 * WHY strip a leading "SUBJECT:" prefix from the formatAlertTitle result when we
 * already render the subject in its own column: `formatAlertTitle` returns
 * "AAPL: Bullish guidance" so the sidebar (which has no subject column) stays
 * self-describing. In the list the ticker lives in its own column, so repeating
 * it in the summary is redundant — we trim the "<subject>: " prefix to keep the
 * summary column tight. We only strip when the prefix exactly matches the
 * subject we're already showing, so unrelated colons in prose are preserved.
 */
export function alertSummary(alert: Alert): string {
  // 1. Prefer an explicit body when the backend populated one.
  if (typeof alert.body === "string" && alert.body.trim()) {
    return alert.body.trim();
  }

  // 2. Fall back to the shared sidebar/dashboard composer.
  const composed = formatAlertTitle(alert);
  const subject = alertSubject(alert);

  // De-duplicate the subject when it's already shown in the subject column.
  if (subject) {
    const prefix = `${subject}: `;
    if (composed.startsWith(prefix)) {
      return composed.slice(prefix.length);
    }
  }
  return composed;
}
