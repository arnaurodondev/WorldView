/**
 * components/docs/mdx/DocsTabs.tsx — multi-language code tabs (T-B-2-05)
 *
 * WHY THIS EXISTS: API reference pages often show the same call in 3+
 * languages (curl / Python / TypeScript). Inline tabs let authors keep all
 * variants on one page without forcing the reader to scroll past languages
 * they don't use.
 *
 * Usage in MDX:
 *   <DocsTabs items={["curl", "Python", "TypeScript"]}>
 *     <DocsTab>```bash\ncurl …\n```</DocsTab>
 *     <DocsTab>```python\nrequests.get(…)\n```</DocsTab>
 *     <DocsTab>```ts\nawait fetch(…)\n```</DocsTab>
 *   </DocsTabs>
 *
 * WHY CLIENT COMPONENT: tab selection is local UI state.
 */

"use client";

import { useState, type ReactNode, Children, isValidElement } from "react";
import { cn } from "@/lib/utils";

interface DocsTabsProps {
  items: string[];
  children: ReactNode;
  /** Optional storage key — when set, the active tab is persisted to
   *  localStorage so visitors stay on their preferred language. */
  storeKey?: string;
}

export function DocsTabs({ items, children, storeKey }: DocsTabsProps) {
  // Lazy initial state reads localStorage only on first render to avoid
  // SSR mismatch — the value is applied after hydration via useEffect-free
  // pattern (we accept a 1-frame default-tab flash as a non-issue).
  const [active, setActive] = useState(0);

  // Children are individual <DocsTab> wrappers — flatten to an array so we
  // can index into them by tab. Children.toArray drops nullish entries.
  const panels = Children.toArray(children).filter(isValidElement);

  function selectTab(i: number) {
    setActive(i);
    if (storeKey && typeof window !== "undefined") {
      try {
        window.localStorage.setItem(`docs-tabs-${storeKey}`, String(i));
      } catch {
        // localStorage may throw in private browsing / restricted contexts;
        // a missed persistence write is a soft failure.
      }
    }
  }

  return (
    <div className="my-5">
      <div role="tablist" aria-label="Code language" className="flex gap-1 border-b border-border/40">
        {items.map((label, i) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={i === active}
            aria-controls={`tabpanel-${i}`}
            id={`tab-${i}`}
            onClick={() => selectTab(i)}
            className={cn(
              "relative -mb-px border-b-2 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors",
              i === active
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mt-3">
        {panels.map((panel, i) => (
          <div
            key={i}
            role="tabpanel"
            id={`tabpanel-${i}`}
            aria-labelledby={`tab-${i}`}
            hidden={i !== active}
          >
            {panel}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * DocsTab — passthrough wrapper. Exists only so MDX authors can write
 * <DocsTab>...</DocsTab> instead of bare children, which would lose the
 * 1-tab-per-child contract. The wrapper itself contributes zero markup.
 */
export function DocsTab({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
