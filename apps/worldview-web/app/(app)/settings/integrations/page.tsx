/**
 * app/(app)/settings/integrations/page.tsx — Integrations (placeholder).
 */

import { SettingsPlaceholder } from "../_components/placeholder";

export default function SettingsIntegrationsPage() {
  return (
    <SettingsPlaceholder
      title="Integrations"
      description="Connected accounts and external services"
      bullets={[
        "TastyTrade brokerage sync (already wired in /portfolio)",
        "SnapTrade brokerage connections (coming via PRD-0022)",
        "Slack alert delivery (planned)",
        "Webhook outbound for portfolio events (planned)",
      ]}
    />
  );
}
