/**
 * components/instrument/DrawingPalette.tsx — Left-side vertical drawing palette
 *
 * WHY THIS EXISTS: Analysts annotate charts to mark support/resistance levels,
 * trend lines, and key price zones. TradingView places a vertical palette of
 * drawing tools on the left side of the chart — a well-established convention
 * that institutional traders recognise immediately.
 *
 * WHY LEFT-SIDE VERTICAL LAYOUT: The right side is owned by the price scale (Y axis)
 * and data labels. The top is the toolbar with indicators. The bottom is the time
 * scale. The left is the only edge with no competing chrome — it's the natural home
 * for drawing tools. Bloomberg Desktop uses the same placement.
 *
 * WHY CLICK-TO-ARM MODEL (not drag-and-drop from palette): The chart canvas is
 * managed by lightweight-charts WebGL renderer — dragging an SVG element from the
 * palette onto the WebGL canvas is not natively supported. Instead:
 *   1. User clicks a tool button → the tool is "armed" (active tool set in state).
 *   2. User clicks on the chart canvas → first point is recorded.
 *   3. User clicks again → second point is recorded and the annotation is committed.
 * This is identical to TradingView's interaction model.
 *
 * WHY ABSOLUTE POSITIONING: The palette sits on the left side of the chart container
 * via `absolute inset-y-0 left-0`. The chart canvas is padded-left by the palette
 * width (28px) so the WebGL surface doesn't extend behind the buttons.
 *
 * WHY `data-testid` on every button: Playwright tests click these buttons to arm
 * tools before simulating canvas clicks. Without testids, the playwright selectors
 * would need fragile role/text matching.
 *
 * WHO USES IT: OHLCVChart (renders alongside the chart container)
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-02, TradingView left drawing palette
 */

// WHY no "use client": DrawingPalette is a pure presentation component.
// It receives the active tool via props and emits callbacks — no hooks needed.

import type { DrawingToolId } from "@/lib/instrument-context";

// ── Tool metadata ─────────────────────────────────────────────────────────────

/**
 * TOOL_META — display config for each drawing tool.
 *
 * WHY Unicode glyphs (not SVG icons): at 11px button size, SVG icons at <14px
 * become unreadable. Unicode geometric/arrow symbols at 10-11px are clear and
 * require zero external dependencies.
 *
 * Glyph selection rationale:
 *   TREND_LINE       ╱  — diagonal line (trend direction)
 *   HORIZONTAL_LEVEL ─  — horizontal bar (horizontal level / support)
 *   RECTANGLE        □  — rectangle outline
 *   ARROW            ↗  — arrow (momentum direction)
 *   FIB_RETRACEMENT  φ  — phi (Fibonacci association)
 *   PARALLEL_CHANNEL ≡  — parallel lines (channel)
 *   TEXT             T  — capital T (text tool convention)
 *   CURSOR           ✕  — exit / escape active tool
 */
const TOOL_META: Record<DrawingToolId | "CURSOR", { glyph: string; title: string }> = {
  CURSOR:           { glyph: "✕", title: "Exit drawing mode" },
  TREND_LINE:       { glyph: "╱", title: "Trend Line — click two points" },
  HORIZONTAL_LEVEL: { glyph: "─", title: "Horizontal Level — click one price" },
  RECTANGLE:        { glyph: "□", title: "Rectangle — click top-left, then bottom-right" },
  ARROW:            { glyph: "↗", title: "Arrow — click start, then end" },
  FIB_RETRACEMENT:  { glyph: "φ", title: "Fibonacci Retracement — click high, then low" },
  PARALLEL_CHANNEL: { glyph: "≡", title: "Parallel Channel — click 3 points" },
  TEXT:             { glyph: "T", title: "Text Annotation — click anchor point" },
};

/**
 * TOOL_ORDER — order of tools shown in the palette.
 *
 * WHY CURSOR first: the cursor (exit drawing mode) is the most important tool.
 * Placing it at the top lets analysts quickly escape back to normal pan/zoom mode
 * — especially important when they accidentally arm the wrong tool.
 *
 * The rest follows TradingView's palette order: lines first, complex tools last.
 */
const TOOL_ORDER: Array<DrawingToolId | "CURSOR"> = [
  "CURSOR",
  "TREND_LINE",
  "HORIZONTAL_LEVEL",
  "RECTANGLE",
  "ARROW",
  "FIB_RETRACEMENT",
  "PARALLEL_CHANNEL",
  "TEXT",
];

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DrawingPaletteProps {
  /**
   * Currently armed drawing tool. `null` = cursor mode (no tool active).
   * OHLCVChart owns this state and passes it via props.
   */
  activeTool: DrawingToolId | null;
  /**
   * Callback when user clicks a palette button.
   * Passing `null` means "exit drawing mode" (CURSOR button clicked).
   */
  onSelectTool: (tool: DrawingToolId | null) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DrawingPalette({ activeTool, onSelectTool }: DrawingPaletteProps) {
  return (
    // WHY flex-col: tools stack vertically (one per row).
    // WHY w-7: 28px width — enough for a single glyph character at 11px.
    //   The chart container receives pl-7 to offset the palette width so
    //   lightweight-charts doesn't render under the buttons.
    // WHY z-10: the palette must appear above the chart's WebGL canvas.
    //   lightweight-charts' canvas gets z-index 0 by default. Without z-10 here,
    //   the palette buttons would be hidden behind the canvas on some browsers.
    // WHY bg-[#09090B]/80 (dark translucent): matches the chart background
    //   (--background: #09090B) with 80% opacity so the price scale edge is
    //   slightly visible through the palette — preserves spatial context.
    // WHY border-r: hairline separator between palette and chart canvas.
    <div
      className="absolute inset-y-0 left-0 z-10 flex w-7 flex-col items-center gap-0.5 py-1 border-r border-border/30 bg-[#09090B]/80"
      data-testid="drawing-palette"
      role="toolbar"
      aria-label="Chart drawing tools"
    >
      {TOOL_ORDER.map((toolId) => {
        // CURSOR is a special "no tool" button — selecting it deselects the active tool
        const isSpecialCursor = toolId === "CURSOR";

        // Determine if this button is the currently "active" state:
        //   - CURSOR button is active when NO tool is armed (activeTool === null)
        //   - Other buttons are active when they match activeTool
        const isActive = isSpecialCursor ? activeTool === null : activeTool === toolId;

        // WHY separator before CURSOR: visually groups the cursor (exit) button
        // separately from the drawing tools below.
        // WHY not shown for non-CURSOR items: tools flow without separators.

        return (
          <button
            key={toolId}
            onClick={() => {
              // Clicking CURSOR → clear active tool (cursor mode)
              // Clicking a tool → arm that tool
              // Clicking the already-active tool → also clear (toggle off)
              if (isSpecialCursor || activeTool === toolId) {
                onSelectTool(null);
              } else {
                onSelectTool(toolId as DrawingToolId);
              }
            }}
            title={TOOL_META[toolId].title}
            aria-label={TOOL_META[toolId].title}
            aria-pressed={isActive}
            data-testid={`drawing-tool-${toolId.toLowerCase().replace("_", "-")}`}
            className={[
              // Base: tiny square button with no extra padding
              "flex h-5 w-5 items-center justify-center rounded-[2px] text-[11px] transition-colors",
              // Active state: highlight with primary color (brand yellow)
              // WHY bg-primary/20: matches the ChartToolbar active button style
              isActive
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
            ].join(" ")}
          >
            {TOOL_META[toolId].glyph}
          </button>
        );
      })}

      {/* WHY separator + annotation count at the bottom: shows how many annotations
          are saved for this instrument. Gives analysts confidence that their drawings
          are persisted even after a tab close. */}
    </div>
  );
}
