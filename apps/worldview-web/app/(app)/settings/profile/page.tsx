/**
 * app/(app)/settings/profile/page.tsx — Profile settings (extracted from
 * legacy /settings tabset, PLAN-0059 I-3).
 */

"use client";

import { useAuth } from "@/hooks/useAuth";
import { ProfileTab } from "../_components/tabs";

export default function SettingsProfilePage() {
  const { user } = useAuth();
  return <ProfileTab user={user} />;
}
