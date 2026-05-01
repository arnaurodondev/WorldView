/**
 * components/docs/mdx/Steps.tsx — numbered tutorial steps (T-B-2-05)
 *
 * WHY THIS EXISTS: "How to set up X" pages benefit from explicit step
 * numbering with a connector line — visitors can scan their progress and
 * resume where they paused. Used like:
 *
 *   <Steps>
 *     <Step title="Install the CLI">…</Step>
 *     <Step title="Configure your token">…</Step>
 *   </Steps>
 *
 * WHY SERVER COMPONENT: pure render — the step number derives from child
 * index at render time; no client interactivity needed.
 */

import { Children, type ReactNode } from "react";

interface StepsProps {
  children: ReactNode;
}

export function Steps({ children }: StepsProps) {
  // Filter null/false children (common when MDX uses conditional snippets)
  // so step numbers stay sequential regardless of source spacing.
  const steps = Children.toArray(children).filter(Boolean);

  return (
    <ol className="my-5 space-y-4 border-l border-border/40 pl-6">
      {steps.map((step, i) => (
        <li
          key={i}
          // The marker counter is computed by Tailwind's `before:`
          // pseudo with the step index baked into a CSS variable.
          className="relative pl-2"
        >
          {/* Numbered badge that sits in the gutter */}
          <span
            aria-hidden="true"
            className="absolute -left-[33px] top-0 flex h-6 w-6 items-center justify-center rounded-full border border-border/60 bg-card font-mono text-[11px] font-semibold text-foreground"
          >
            {i + 1}
          </span>
          {step}
        </li>
      ))}
    </ol>
  );
}

interface StepProps {
  title?: string;
  children: ReactNode;
}

/**
 * Step — single tutorial step. Title is optional; when provided it
 * renders as an inline h4 above the body text.
 */
export function Step({ title, children }: StepProps) {
  return (
    <div>
      {title ? (
        <h4 className="mb-2 mt-0 text-sm font-semibold text-foreground">
          {title}
        </h4>
      ) : null}
      <div className="text-sm text-muted-foreground [&>p:last-child]:mb-0 [&>p]:mb-2 leading-relaxed">
        {children}
      </div>
    </div>
  );
}
