/**
 * components/charts/index.ts — barrel export for Wave G chart primitives.
 *
 * WHY barrel: consumers (AnalyticsPerformanceChart, AnalyticsDrawdownChart,
 * upcoming SA-B/C/D wiring) import these often. A single import path
 * (`@/components/charts`) reduces import churn when we add more primitives.
 */
export { TerminalLineChart } from "./TerminalLineChart";
export { TerminalAreaChart } from "./TerminalAreaChart";
