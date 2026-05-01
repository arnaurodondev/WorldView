/**
 * app/(app)/settings/appearance/page.tsx — Appearance settings (extracted
 * from legacy /settings tabset, PLAN-0059 I-3).
 */

"use client";

import { AppearanceTab } from "../_components/tabs";

export default function SettingsAppearancePage() {
  return <AppearanceTab />;
}
