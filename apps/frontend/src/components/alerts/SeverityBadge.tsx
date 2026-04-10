import type { AlertSeverity } from "../../hooks/useAlertStream";

const SEVERITY_STYLE: Record<
  AlertSeverity,
  { bg: string; text: string; label: string }
> = {
  low: { bg: "bg-gray-100", text: "text-gray-600", label: "LOW" },
  medium: { bg: "bg-yellow-100", text: "text-yellow-700", label: "MED" },
  high: { bg: "bg-orange-100", text: "text-orange-700", label: "HIGH" },
  critical: { bg: "bg-red-100", text: "text-red-700", label: "CRITICAL" },
};

export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const { bg, text, label } =
    SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.low;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${bg} ${text}`}
    >
      {label}
    </span>
  );
}
