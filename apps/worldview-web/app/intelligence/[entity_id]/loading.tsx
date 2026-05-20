/**
 * app/intelligence/[entity_id]/loading.tsx — Streaming loading UI for the
 * entity intelligence page.
 *
 * WHY THIS EXISTS: Next.js App Router shows this file's export while the
 * page.tsx Server Component is fetching (or suspended). Without it, the
 * shell renders a blank white screen during navigation — jarring in a
 * dark-themed terminal UI.
 *
 * WHY A SPINNER (not a skeleton): the intelligence page layout varies
 * significantly by entity type (instrument vs. company vs. macro event).
 * A skeleton with fixed-height placeholders would mis-match the real layout
 * more than 50% of the time. A centered spinner is the correct pattern
 * when the layout is unknown at load time.
 *
 * WHO USES IT: app/intelligence/[entity_id]/ route (nested under app router
 * root, NOT inside app/(app)/ — the intelligence page has its own layout).
 */

import { Loader2 } from "lucide-react"

export default function IntelligenceLoading() {
  return (
    // WHY h-full: the parent shell sets a fixed viewport height; h-full fills
    // it so the spinner centres in the visible area, not just the content box.
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-4 animate-spin text-muted-foreground" />
      <span className="sr-only">Loading entity...</span>
    </div>
  )
}
