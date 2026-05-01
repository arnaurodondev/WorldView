/**
 * app/(app)/settings/security/page.tsx — Security settings (placeholder).
 *
 * PLAN-0059 I-3: route exists so the sidebar nav lands somewhere; full
 * content ships in I-4 (user-prefs incl. session management).
 */

import { SettingsPlaceholder } from "../_components/placeholder";

export default function SettingsSecurityPage() {
  return (
    <SettingsPlaceholder
      title="Security"
      description="Account, session, and key management"
      bullets={[
        "Active sessions list with revoke",
        "Two-factor enrolment (TOTP / WebAuthn)",
        "Password change (proxied to identity provider)",
        "Audit log of recent sign-ins",
      ]}
    />
  );
}
