/**
 * components/workspace/NewFromTemplateDialog.tsx — Create a workspace from a template
 *
 * WHY THIS EXISTS: Bare workspaces start with two stub panels (chart + screener).
 * That's fine for ad-hoc tinkering, but new users facing the workspace tab strip
 * for the first time benefit from named, sensibly-laid-out starter configurations.
 * This dialog presents the 5 canonical templates (defined in lib/workspace-templates.ts)
 * as cards. One click instantiates the template as a brand-new workspace tab.
 *
 * WHY DIALOG (not a separate page or sidebar): templates are a one-shot
 * decision — pick one, get a workspace, close the dialog. Anything heavier
 * (a page) would imply ongoing template management; anything lighter (a
 * dropdown) wouldn't have room for the description text that helps users
 * choose between Day Trader and Swing Trader.
 *
 * WHY onCreate callback (not direct context mutation): WorkspaceContext.tsx
 * is owned by Part 1 of PLAN-0051 Wave C and may add an explicit
 * addWorkspaceFromConfig method later. By keeping the create-from-template
 * mutation in the parent (workspace/page.tsx) we don't have to touch the
 * context — the parent decides HOW to instantiate (e.g., write to localStorage
 * and reload, or call a future native context method).
 *
 * WHO USES IT: app/(app)/workspace/page.tsx (rendered alongside WorkspaceTabs)
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-06 (5 templates), DESIGN_SYSTEM.md
 */

"use client";
// WHY "use client": uses Radix Dialog (browser portal), useState (open state)

import { useState } from "react";
import {
  TrendingUp,
  Search,
  Activity,
  Newspaper,
  Briefcase,
  type LucideIcon,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  WORKSPACE_TEMPLATES,
  type WorkspaceTemplate,
} from "@/lib/workspace-templates";

// ── Per-template iconography ───────────────────────────────────────────────────

/**
 * TEMPLATE_ICONS — visual signifier for each template card.
 *
 * WHY map by template id (not embed icon in template definition): keeping the
 * icons here means lib/workspace-templates.ts stays JSX-free (it's a .ts file).
 * The icon-to-template mapping is presentational — it belongs in the component.
 *
 * WHY these specific icons:
 *   day-trader → TrendingUp (active price action)
 *   research → Search (deep dive)
 *   swing-trader → Activity (multi-day movement)
 *   news-junkie → Newspaper (news-driven)
 *   investor → Briefcase (long-term holdings)
 */
const TEMPLATE_ICONS: Record<string, LucideIcon> = {
  "day-trader": TrendingUp,
  "research": Search,
  "swing-trader": Activity,
  "news-junkie": Newspaper,
  "investor": Briefcase,
};

// ── Component props ────────────────────────────────────────────────────────────

interface NewFromTemplateDialogProps {
  /**
   * Called when the user picks a template. Receives the full template object
   * (id, name, description, config). The parent decides how to instantiate
   * it — typically by mutating localStorage and reloading, or by calling a
   * future context method like addWorkspaceFromConfig.
   */
  onCreate: (template: WorkspaceTemplate) => void;

  /**
   * Optional trigger override. When omitted, a default "+ New" button renders.
   * Lets callers (e.g., WorkspaceTabs) supply their own trigger that already
   * matches the surrounding tab strip styling.
   */
  trigger?: React.ReactNode;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function NewFromTemplateDialog({ onCreate, trigger }: NewFromTemplateDialogProps) {
  // WHY local open state (not uncontrolled Radix): we want to AUTO-CLOSE the
  // dialog after a user picks a template. Radix's uncontrolled mode keeps the
  // dialog open until the user clicks the X — which is wrong UX here (after
  // creating a workspace, there's nothing left to do in the dialog).
  const [open, setOpen] = useState(false);

  /**
   * handleSelect — fire onCreate then close the dialog.
   *
   * WHY synchronous flow: onCreate is expected to be synchronous (or fire-and-
   * forget). Awaiting it would risk a stuck-open dialog if the parent throws.
   * If a future onCreate becomes async (e.g., server template loading), this
   * function will need to be revisited with a loading state.
   */
  function handleSelect(template: WorkspaceTemplate) {
    onCreate(template);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          // WHY default trigger style: matches the existing "+ Add" button in
          // WorkspaceTabs visually (10px uppercase tracked, muted-foreground hover).
          <button
            className="ml-1 shrink-0 px-2 text-xs text-muted-foreground hover:text-foreground transition-colors duration-0"
            aria-label="New workspace from template"
          >
            + Template
          </button>
        )}
      </DialogTrigger>

      {/*
       * WHY max-w-md (not max-w-sm like Add Panel): template cards include
       * description text. md (28rem ≈ 448px) gives 2 cards side-by-side at the
       * 200px-each minimum width that fits "Day Trader" + 2-line description.
       */}
      <DialogContent
        className="max-w-md p-0 bg-card border border-border rounded-[2px] shadow-none"
      >
        <DialogHeader className="px-3 py-2 border-b border-border">
          {/* WHY font-mono: ADR-F-15 — dialog titles are section labels, use IBM Plex Mono */}
          <DialogTitle className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-mono font-normal">
            New Workspace from Template
          </DialogTitle>
          {/*
           * WHY DialogDescription required by Radix: omitting it triggers a
           * Radix accessibility warning (DialogDescription must be present for
           * screen readers, even if visually hidden). We keep ours visible —
           * traders benefit from the one-line context.
           */}
          <DialogDescription className="text-[10px] text-muted-foreground">
            Pick a starting layout. You can rename, resize, and rearrange after.
          </DialogDescription>
        </DialogHeader>

        {/* WHY grid-cols-2: 2 cards per row × 3 rows = 6 cells; we have 5
            templates, so the last cell is empty — visually balanced because
            the last row has 1 card centered. gap-px gives the 1px seam style. */}
        <div className="grid grid-cols-2 gap-px bg-border">
          {WORKSPACE_TEMPLATES.map((template) => {
            const Icon = TEMPLATE_ICONS[template.id];
            return (
              // WHY button (not div): templates are clickable; buttons get
              // free keyboard support (Enter/Space activates) and screen-reader
              // semantics. text-left because button defaults to text-center
              // which would misalign the multi-line description.
              <button
                key={template.id}
                onClick={() => handleSelect(template)}
                className="flex flex-col gap-1 bg-card p-3 text-left hover:bg-muted/40 focus:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                aria-label={`Use ${template.name} template`}
                data-testid={`template-card-${template.id}`}
              >
                <div className="flex items-center gap-1.5">
                  {Icon && (
                    <Icon
                      className="h-3.5 w-3.5 shrink-0 text-primary"
                      aria-hidden
                    />
                  )}
                  <span className="text-[11px] font-medium text-foreground">
                    {template.name}
                  </span>
                </div>
                {/* WHY clamp-3 (not no-clamp): a template's description should
                    fit in 3 lines max — anything longer probably belongs in a
                    docs page. line-clamp keeps card heights consistent across
                    the grid. */}
                <span className="text-[10px] text-muted-foreground line-clamp-3">
                  {template.description}
                </span>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
