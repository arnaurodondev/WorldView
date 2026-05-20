/**
 * app/(app)/news/loading.tsx — News feed skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: /news fetches from S6 NLP pipeline which can take 200-800ms.
 * Article row skeletons fill the full height so there's no layout shift on
 * hydration — each skeleton row matches the 28px CompactArticleRow height.
 *
 * WHY 8 rows: matches the default `pageSize` for the initial news fetch.
 * Fewer skeleton rows would leave blank whitespace below the fold.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function NewsLoading() {
  return (
    <div className="flex flex-col gap-0 divide-y divide-border">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-1.5">
          {/* Timestamp placeholder */}
          <Skeleton className="h-[10px] w-[60px] rounded-[2px]" />
          {/* Article title placeholder — flex-1 fills remaining width */}
          <Skeleton className="h-[10px] flex-1 rounded-[2px]" />
          {/* Source/score badge placeholder */}
          <Skeleton className="h-[10px] w-[40px] rounded-[2px]" />
        </div>
      ))}
    </div>
  );
}
