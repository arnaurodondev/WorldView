/**
 * components/feedback/NPSPromptHost.tsx — global NPSPrompt mount point.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-08):
 * Trigger sites (post-portfolio-sync, post-first-alert) want a 1-line
 * call to fire the NPS prompt without each one mounting its own Dialog.
 * The host listens for a `worldview:request-nps` CustomEvent and pops
 * the prompt IF eligibility allows. Trigger code looks like:
 *
 *   window.dispatchEvent(
 *     new CustomEvent("worldview:request-nps", { detail: { surface: "post_sync" }})
 *   );
 *
 * Mounted once in (app)/layout.tsx so every authenticated page has it.
 */

"use client";

import { useEffect, useState } from "react";
import { useNPSEligibility } from "@/hooks/useNPSEligibility";
import { NPSPrompt } from "./NPSPrompt";

export interface NPSRequestEventDetail {
  surface: string;
}

export function NPSPromptHost() {
  const { eligible } = useNPSEligibility();
  const [open, setOpen] = useState(false);
  const [surface, setSurface] = useState("default");

  useEffect(() => {
    function onRequest(e: Event) {
      // WHY narrow inside listener: CustomEvent<T> isn't preserved by
      // window.addEventListener's broad signature in TS. We runtime-check
      // the detail shape and fall back to "default" surface.
      const detail = (e as CustomEvent<NPSRequestEventDetail>).detail;
      const reqSurface =
        detail && typeof detail.surface === "string" ? detail.surface : "default";
      // Only open if the eligibility hook says so. The trigger doesn't
      // need to know about cooldown / quarter rules — they're centralised
      // in useNPSEligibility.
      if (!eligible) return;
      setSurface(reqSurface);
      setOpen(true);
    }
    window.addEventListener("worldview:request-nps", onRequest);
    return () => window.removeEventListener("worldview:request-nps", onRequest);
  }, [eligible]);

  // WHY render only when open: NPSPrompt's Dialog auto-mounts/unmounts
  // animations even when closed. Skipping the render keeps the tree
  // lighter on every page.
  if (!open) return null;
  return <NPSPrompt open={open} onOpenChange={setOpen} surface={surface} />;
}

/**
 * requestNPS — convenience helper for trigger sites. Single import surface
 * so callers don't sprinkle dispatchEvent strings throughout the app.
 */
export function requestNPS(surface: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<NPSRequestEventDetail>("worldview:request-nps", {
      detail: { surface },
    }),
  );
}
