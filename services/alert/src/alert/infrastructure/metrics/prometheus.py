"""Prometheus metrics for the Alert service (S10).

All metric names use the ``s10_`` prefix per service naming convention.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

# ── Counters ──────────────────────────────────────────────────────────────────

s10_alerts_fanned_out_total = Counter(
    "s10_alerts_fanned_out_total",
    "Total alerts fanned out to users, labelled by alert type",
    ["type"],
)

s10_alerts_deduplicated_total = Counter(
    "s10_alerts_deduplicated_total",
    "Total alerts suppressed by the deduplication window",
)

s10_websocket_pushes_total = Counter(
    "s10_websocket_pushes_total",
    "Total WebSocket push attempts (includes failed sends)",
)

s10_alerts_by_severity_total = Counter(
    "s10_alerts_by_severity_total",
    "Total alerts fanned out, labelled by severity tier and alert type (PRD-0021)",
    ["severity", "alert_type"],
)

s10_flash_overlays_triggered_total = Counter(
    "s10_flash_overlays_triggered_total",
    "Total CRITICAL-severity alerts that triggered a flash overlay (PRD-0021)",
)

# ── Gauges ────────────────────────────────────────────────────────────────────

s10_alerts_pending_total = Gauge(
    "s10_alerts_pending_total",
    "Current number of unacknowledged pending_alerts rows",
)

s10_s1_lookup_failed_total = Counter(
    "s10_s1_lookup_failed_total",
    "Total S1 watchlist lookup failures (network/HTTP error).",
)

# ── Alert rule poller (PLAN-0113, BP-705) ──────────────────────────────────────
# Liveness gauge: unix seconds of the last successful poller cycle. A staleness
# alert (now - gauge > 2x cadence) detects a silent stall. Survives nothing on
# its own, but the poller re-emits every cycle so an alert fires when the loop
# wedges.
s10_rule_poller_last_success_timestamp = Gauge(
    "s10_rule_poller_last_success_timestamp_seconds",
    "Unix timestamp (UTC seconds) of the last successful alert-rule poller cycle.",
)

# Runs counter labelled by outcome so a flat "ran but always errored" stall is
# distinguishable from "not running at all".
s10_rule_poller_runs_total = Counter(
    "s10_rule_poller_runs_total",
    "Total alert-rule poller cycles, labelled by outcome (success|error|timeout).",
    ["outcome"],
)

# Per-cycle count of rules found due (cardinality-safe — no per-rule labels).
s10_rule_poller_due_rules = Gauge(
    "s10_rule_poller_due_rules",
    "Number of enabled poll rules found due in the most recent poller cycle.",
)
