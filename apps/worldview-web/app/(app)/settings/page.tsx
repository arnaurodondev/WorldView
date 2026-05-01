/**
 * app/(app)/settings/page.tsx — index redirect
 *
 * PLAN-0059 I-3: settings was a 593-LOC tabbed page; now split into nested
 * routes. The bare /settings URL redirects to the canonical first-section
 * (/settings/profile) so existing bookmarks land somewhere sensible.
 */

import { redirect } from "next/navigation";

export default function SettingsIndex() {
  redirect("/settings/profile");
}
