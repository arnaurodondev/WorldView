/**
 * components/primitives/AiContentRail.tsx — 2px left rail on AI-generated text
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-DISCUSS-12 — every surface that
 * shows AI-generated narrative (brief, Ask AI panel, chat response) must
 * carry the same visual signal so analysts immediately know what's model-
 * generated and what's source data. The left rail uses --accent-ai
 * (violet, the universal industry color for AI).
 * WHO USES IT: Quote tab AI brief banner, Intelligence brief footer,
 *   AskAiPanel response, chat assistant bubbles.
 * DATA SOURCE: Pure presentational wrapper.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (AiContentRail row) + FU-DISCUSS-12.
 */

import type { ReactNode } from "react";

interface AiContentRailProps {
  readonly children: ReactNode;
}

export function AiContentRail({ children }: AiContentRailProps): ReactNode {
  return (
    <div
      data-ai-content="true"
      className="border-l-2 border-[hsl(var(--accent-ai))] pl-3"
    >
      {children}
    </div>
  );
}
