"use client";

/**
 * ToolTraceDrawer — debug-only right-docked panel ("Why this answer?").
 *
 * WHY this component exists (PRD-0089 K Block F / Q-8):
 * Wave K introduces a thesis-grade introspection surface that lets the
 * developer (and the thesis evaluator) see exactly which tools were
 * dispatched for an assistant turn, in what order, with which arguments,
 * which entities the retrieval resolved against, and which retrieval plan
 * the orchestrator chose. This is invaluable for:
 *   - debugging "why did S8 not call search_documents?" questions
 *   - validating fallback-chain behaviour (Q-9 `is_fallback` / `fallback_of`)
 *   - explaining the system in the thesis demo without opening DevTools
 *
 * WHY URL-gated (Q-8):
 * The drawer is hidden behind `?debug=1` (see `useDebugFlag`). Without
 * the query parameter, this component returns `null` UNCONDITIONALLY —
 * even if a caller mistakenly passes `open=true`. This is defense in
 * depth: a future bug that wires the drawer open in production never
 * leaks tool internals to end users.
 *
 * WHY a hand-rolled fixed-position aside (not shadcn `Sheet`):
 * `Sheet` is built on Radix Dialog — it grabs focus, traps it, and
 * blocks the underlying chat from receiving keyboard input. We want
 * the chat list to remain interactive while the drawer is open (the
 * dev should be able to click another turn to swap `turn` prop without
 * dismissing). A fixed-position aside achieves that with less code
 * and matches the design spec's "right-docked 320px panel" exactly.
 *
 * WHY console.debug (not analytics.track):
 * The spec forbids analytics on debug surfaces (Q-8 — no observability
 * of debug behaviour) so we stick to `console.debug` for any developer
 * breadcrumbs. In practice we emit none in T-19; the hook noted here is
 * for future debugging only.
 *
 * Props contract:
 *   open    — whether the parent wants the drawer visible
 *   onClose — invoked when the user presses Esc or the close button
 *   turn    — the selected assistant Message; null while no turn is
 *             focused (we render a placeholder).
 */

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useDebugFlag } from "@/features/chat/hooks/useDebugFlag";
import type { Message } from "@/types/api";

// ─────────────────────────────────────────────────────────────────────────
// Public chord helper — registers ⌘D / Ctrl+D to toggle the drawer.
//
// WHY exported separately (not embedded in ToolTraceDrawer):
// Block G's T-20 wires the drawer at the page level (chat/page.tsx) where
// the selected turn lives. A standalone hook keeps the chord registration
// near the same state that drives `open` (the page's `useState`).
// We expose it from T-19 so T-20 only has to import + call it.
//
// WHY gated on `useDebugFlag()` here too:
// Defense in depth. If a caller forgets to gate registration, the hook
// still no-ops when the URL flag is absent — never steal ⌘D from browser
// "bookmark" when debug=0.
// ─────────────────────────────────────────────────────────────────────────
export function useToolTraceChord(
  enabled: boolean,
  setOpen: (next: boolean | ((prev: boolean) => boolean)) => void,
): void {
  // WHY read flag inside the hook (not as an arg): the chord should ONLY
  // be wired when debug=1 is present, regardless of what the consumer
  // passes for `enabled`. The `enabled` arg lets the page also gate on
  // "is there a focused assistant turn?" — both conditions must hold.
  const isDebug = useDebugFlag();
  useEffect(() => {
    if (!isDebug || !enabled) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      // WHY both Cmd (mac) and Ctrl (win/linux): unified chord across OSes
      // mirrors the convention used by ChatLayout.tsx for other ⌘-prefixed
      // shortcuts. We do NOT match plain "d" — that would clash with typing.
      const isModifier = event.metaKey || event.ctrlKey;
      if (isModifier && event.key.toLowerCase() === "d") {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isDebug, enabled, setOpen]);
}

// ─────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────

/**
 * ToolTraceRow — one row per tool_call/tool_result for the selected turn.
 *
 * WHY the `unknown` cast on `turn`: the canonical `Message` interface
 * doesn't carry a `tool_calls[]` field (yet — backend Q-11 follow-up).
 * For now we read it defensively from any extra property the orchestrator
 * may attach; if absent we degrade to an empty list. This matches Q-9's
 * "ship behind null-safe defaults" rule (see plan §RP-RP).
 */
type ToolRow = {
  name: string;
  status?: string;
  duration_ms?: number;
  args?: Record<string, unknown>;
  result_count?: number;
  is_fallback?: boolean;
  fallback_of?: string;
};

function readToolRows(turn: Message | null): ToolRow[] {
  if (!turn) return [];
  // Defensive read: the canonical Message type doesn't expose tool_calls
  // today, but the wire envelope may attach them under a side-channel
  // key. Cast to a record-of-unknown and check before trusting.
  const extra = turn as unknown as { tool_calls?: unknown };
  if (!Array.isArray(extra.tool_calls)) return [];
  return extra.tool_calls.filter((tc): tc is ToolRow => typeof tc === "object" && tc !== null);
}

function readTokenCount(turn: Message | null, key: "token_count_in" | "token_count_out"): number | null {
  if (!turn) return null;
  // Same defensive read pattern — token counts aren't on the canonical
  // Message type yet, but may arrive on the metadata SSE event later.
  const extra = turn as unknown as Record<string, unknown>;
  const value = extra[key];
  return typeof value === "number" ? value : null;
}

// ─────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────

interface ToolTraceDrawerProps {
  open: boolean;
  onClose: () => void;
  turn: Message | null;
}

export function ToolTraceDrawer({ open, onClose, turn }: ToolTraceDrawerProps): React.ReactElement | null {
  const isDebug = useDebugFlag();

  // Esc closes — registered only when the drawer is actually visible to
  // avoid intercepting Esc when the chat composer needs it (e.g. to clear
  // an autocomplete popover). Also gated on debug=1 as a safety net.
  useEffect(() => {
    if (!isDebug || !open) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isDebug, open, onClose]);

  // Defense in depth — return null even if `open=true` should the URL flag
  // be missing. The two gates are independent: callers should also gate
  // the toggle wiring, but we must not trust callers.
  if (!isDebug) return null;
  if (!open) return null;

  const toolRows = readToolRows(turn);
  const tokensIn = readTokenCount(turn, "token_count_in");
  const tokensOut = readTokenCount(turn, "token_count_out");
  const resolvedEntities = turn?.resolved_entities ?? [];
  const retrievalPlan = turn?.retrieval_plan ?? null;

  return (
    <aside
      // WHY data-testid: Block I (T-22/T-23) Playwright opens this drawer
      // and asserts on its contents. Stable test hook lives here.
      data-testid="tool-trace-drawer"
      // WHY fixed inset-y-0 right-0: right-docked panel that overlays the
      // chat without pushing layout. Width 320px == 20rem matches spec.
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-80 flex-col",
        "border-l border-border bg-card text-foreground",
        "shadow-xl",
      )}
      role="complementary"
      aria-label="Tool trace debug drawer"
    >
      {/* Header — sticky, identifies the turn and reminds Esc closes. */}
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="text-xs font-medium">
          <span className="text-warning">[DEBUG]</span> Tool trace
          {turn?.message_id ? (
            <>
              {" "}
              — turn <span className="tabular-nums">{turn.message_id.slice(0, 8)}</span>
            </>
          ) : null}
          <span className="ml-2 text-muted-foreground">· ESC closes</span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onClose}
          // WHY h-6 px-2 text-xs: align with the dense terminal style of
          // the chat header bar. shadcn `sm` default is too tall.
          className="h-6 px-2 text-xs"
        >
          Close
        </Button>
      </header>

      {/* Body — scrolls independently of the chat. */}
      <div className="flex-1 overflow-y-auto px-3 py-3 text-xs">
        {turn == null ? (
          <p className="text-muted-foreground">Select an assistant turn</p>
        ) : (
          <>
            {/* Section: retrieval plan ----------------------------------- */}
            <section className="mb-4">
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Retrieval plan
              </h3>
              {retrievalPlan && Object.keys(retrievalPlan).length > 0 ? (
                <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded border border-border bg-background p-2 text-[11px] leading-relaxed">
                  {JSON.stringify(retrievalPlan, null, 2)}
                </pre>
              ) : (
                <p className="text-muted-foreground">—</p>
              )}
            </section>

            {/* Section: resolved entities -------------------------------- */}
            <section className="mb-4">
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Resolved entities ({resolvedEntities.length})
              </h3>
              {resolvedEntities.length === 0 ? (
                <p className="text-muted-foreground">—</p>
              ) : (
                <ul className="flex flex-wrap gap-1">
                  {resolvedEntities.map((eid) => (
                    <li
                      key={eid}
                      className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] tabular-nums"
                      title={eid}
                    >
                      {eid.slice(0, 8)}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Section: tool trace --------------------------------------- */}
            <section className="mb-4">
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Tool trace ({toolRows.length})
              </h3>
              {toolRows.length === 0 ? (
                <p className="text-muted-foreground">—</p>
              ) : (
                <ul className="space-y-1">
                  {toolRows.map((row, idx) => (
                    <li
                      key={`${row.name}-${idx}`}
                      className={cn(
                        "rounded border border-border bg-background p-1.5",
                        // WHY warning tint for fallbacks: matches MessageMetaStrip's
                        // existing convention for is_fallback rows so the user
                        // recognises the visual immediately.
                        row.is_fallback && "text-warning",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-[11px]">{row.name}</span>
                        <span className="tabular-nums text-[10px] text-muted-foreground">
                          {row.status ?? "—"}
                          {typeof row.duration_ms === "number" ? ` · ${row.duration_ms}ms` : ""}
                          {typeof row.result_count === "number" ? ` · ${row.result_count} items` : ""}
                        </span>
                      </div>
                      {row.is_fallback && row.fallback_of ? (
                        <div className="mt-0.5 text-[10px] text-warning">
                          fallback of <span className="font-mono">{row.fallback_of}</span>
                        </div>
                      ) : null}
                      {row.args && Object.keys(row.args).length > 0 ? (
                        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-1 text-[10px]">
                          {JSON.stringify(row.args, null, 2)}
                        </pre>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Section: token counts ------------------------------------- */}
            <section className="mb-4">
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Tokens
              </h3>
              <dl className="grid grid-cols-2 gap-1 text-[11px]">
                <dt className="text-muted-foreground">in</dt>
                <dd className="tabular-nums">{tokensIn ?? "—"}</dd>
                <dt className="text-muted-foreground">out</dt>
                <dd className="tabular-nums">{tokensOut ?? "—"}</dd>
              </dl>
            </section>

            {/* Section: provider / model / latency ----------------------- */}
            <section>
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Serving
              </h3>
              <dl className="grid grid-cols-2 gap-1 text-[11px]">
                <dt className="text-muted-foreground">provider</dt>
                <dd className="font-mono">{turn.provider ?? "—"}</dd>
                <dt className="text-muted-foreground">model</dt>
                <dd className="font-mono break-all">{turn.model ?? "—"}</dd>
                <dt className="text-muted-foreground">latency</dt>
                <dd className="tabular-nums">
                  {typeof turn.latency_ms === "number" ? `${turn.latency_ms}ms` : "—"}
                </dd>
              </dl>
            </section>
          </>
        )}
      </div>
    </aside>
  );
}
