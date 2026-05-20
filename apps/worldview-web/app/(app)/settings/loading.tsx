/**
 * app/(app)/settings/loading.tsx — Settings page skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: /settings has a sidebar nav + content area layout.
 * The two-panel skeleton prevents blank flash while the layout.tsx shell
 * renders. Sidebar width (200px) matches the real SettingsSidebar width.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function SettingsLoading() {
  return (
    <div className="flex gap-0 h-full">
      {/* Left sidebar nav — mirrors SettingsSidebar width */}
      <div className="w-[200px] border-r border-border p-2 flex flex-col gap-1">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[28px] w-full rounded-[2px]" />
        ))}
      </div>
      {/* Main content panel */}
      <div className="flex-1 p-4 flex flex-col gap-3">
        {/* Section title */}
        <Skeleton className="h-[24px] w-[200px] rounded-[2px]" />
        {/* Content cards */}
        <Skeleton className="h-[120px] w-full rounded-[2px]" />
        <Skeleton className="h-[120px] w-full rounded-[2px]" />
      </div>
    </div>
  );
}
