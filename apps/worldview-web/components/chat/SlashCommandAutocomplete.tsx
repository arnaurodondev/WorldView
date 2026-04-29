/**
 * components/chat/SlashCommandAutocomplete.tsx — popover suggestion list
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-01):
 * Slash commands are powerful but discoverable only when the user knows the
 * verb. As soon as they type "/" we open a small popover showing the available
 * commands. Each click fills the input to the verb so the user can finish
 * typing the args (or hit Enter for arg-less commands).
 *
 * WHY KEYBOARD-FREE (clicks only): the chat input uses Enter-to-send. Wiring
 * up arrow-key navigation + Enter-to-pick would conflict with that. Click-to-
 * pick is sufficient for discovery; experienced users will type the full verb.
 *
 * WHY pure presentational (no fetching): just a list of commands filtered
 * by the typed prefix. The chat page owns the state and decides when to show
 * the popover (only when input starts with "/").
 */

"use client";
// WHY "use client": click handlers + relative absolute positioning rely on
// browser layout and event bindings.

import { filterCommands, type SlashCommand } from "@/lib/chat/slash-commands";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface SlashCommandAutocompleteProps {
  /** Current input text (may or may not start with "/"). */
  query: string;
  /**
   * Called when the user clicks a suggestion. The string passed back is the
   * exact verb (without leading slash) — the parent prepends "/" + a trailing
   * space when filling the input.
   */
  onPick: (cmd: SlashCommand) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SlashCommandAutocomplete — small panel above the textarea listing matching
 * commands. Renders nothing when the query doesn't start with "/" (the parent
 * component is also expected to gate visibility, this is belt-and-braces).
 */
export function SlashCommandAutocomplete({
  query,
  onPick,
}: SlashCommandAutocompleteProps) {
  // WHY trim then check prefix: a stray space after "/" still counts.
  const trimmed = query.trimStart();
  if (!trimmed.startsWith("/")) return null;

  // Use everything up to the first space as the prefix, so "/quo " still
  // matches "/quote" while "/quote AAPL" stops matching once the space is
  // typed (user has committed to the verb and is entering args — popover
  // can hide at that point if the parent chooses).
  const head = trimmed.split(/\s/)[0];
  const matches = filterCommands(head);

  // No matches — render nothing (parent might still show a "no commands"
  // placeholder, but we keep this component tight: hidden when irrelevant).
  if (matches.length === 0) return null;

  return (
    <div
      // WHY rounded-[2px]: design-system 2px radius rule.
      // WHY border-border + bg-card: the autocomplete sits over the chat log;
      // a solid bg + border is required for legibility.
      className={cn(
        "mb-2 rounded-[2px] border border-border bg-card shadow-none",
        "max-h-64 overflow-y-auto",
      )}
      role="listbox"
      aria-label="Slash command suggestions"
    >
      {matches.map((cmd) => (
        <button
          key={cmd.name}
          type="button"
          // WHY full-row button: Bloomberg-style menus use entire-row hits.
          className={cn(
            "flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left",
            "border-b border-border/40 last:border-b-0",
            "text-[12px] font-mono",
            "hover:bg-muted/50 focus:bg-muted/50 focus:outline-none",
          )}
          onClick={() => onPick(cmd)}
          role="option"
          aria-selected="false"
        >
          {/* Verb + arg spec — use primary colour for the slash so the
              command name pops visually. */}
          <span className="flex items-center gap-1.5">
            <span className="text-primary">/{cmd.name}</span>
            {cmd.argSpec && (
              <span className="text-[10px] text-muted-foreground">
                {cmd.argSpec}
              </span>
            )}
          </span>
          {/* Description on the right — terminal-style two-column layout */}
          <span className="text-[11px] text-muted-foreground">
            {cmd.description}
          </span>
        </button>
      ))}
      {/* PLAN-0053 T-F-6-04: usage-hint footer — shown ONLY when exactly one
          command matches (i.e. the user has narrowed to a single verb). At
          that point the inline reminder of how to invoke the command saves a
          trip to the docs and reduces friction for new users.
          WHY single-match (not multi-match): with multiple matches the row
          itself shows the argSpec; a single tip applies cleanly to one verb. */}
      {matches.length === 1 && (
        <div
          className={cn(
            "border-t border-border/40 bg-muted/30 px-3 py-1",
            "text-[10px] font-mono text-muted-foreground",
          )}
          aria-live="polite"
        >
          {/* WHY "Usage:": semantic prefix readable by both humans and screen
              readers. Mirrors man-page convention familiar to terminal users. */}
          <span className="text-foreground/70">Usage:</span>{" "}
          /{matches[0].name}
          {matches[0].argSpec ? ` ${matches[0].argSpec}` : ""}
        </div>
      )}
    </div>
  );
}
