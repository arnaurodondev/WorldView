/**
 * types/alerts.ts — Alert type definitions shared between hooks and components
 *
 * WHY SEPARATE FILE: AlertStreamContext and FlashOverlay both need AlertPayload.
 * Defining in types/ avoids circular imports (context imports from types,
 * components import from types — not components importing from context or vice versa).
 *
 * DATA SOURCE: S10 WebSocket stream (PRD-0028 §6.6 Flow 5)
 */

/** Severity levels for alerts — mirrors AlertSeverity enum from PRD-0021 */
export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/**
 * AlertPayload — shape of a single alert from the S10 WebSocket stream
 *
 * WHY this shape: Mirrors the S10 WebSocket message format from PRD-0021.
 * CRITICAL alerts have separate display treatment (FlashOverlay vs notification badge).
 */
export interface AlertPayload {
  id: string;
  severity: AlertSeverity;
  alert_type: string;
  entity_id: string | null;
  message: string;
  created_at: string; // ISO 8601 UTC timestamp
}
