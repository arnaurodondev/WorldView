/**
 * app/(app)/settings/data/page.tsx — Data & exports (placeholder).
 */

import { SettingsPlaceholder } from "../_components/placeholder";

export default function SettingsDataPage() {
  return (
    <SettingsPlaceholder
      title="Data & exports"
      description="Manage saved data and request exports"
      bullets={[
        "Bulk export of portfolios, watchlists, transactions",
        "Saved screener configurations",
        "Workspace layouts backup",
        "Account data deletion (GDPR right-to-be-forgotten)",
      ]}
    />
  );
}
