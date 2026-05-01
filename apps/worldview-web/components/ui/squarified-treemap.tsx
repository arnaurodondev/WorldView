/**
 * components/ui/squarified-treemap.tsx — React component over lib/treemap.ts
 *
 * WHY THIS EXISTS: PLAN-0059 H-3 — migrate MarketHeatmap and SectorHeatmapWidget
 * off ad-hoc grid/flex-wrap layouts onto a true Bruls/Huijsen/van Wijk
 * squarified layout. The algorithm (lib/treemap.ts) is pure; this component
 * adds:
 *   - ResizeObserver to measure the container at runtime (squarify needs a
 *     pixel rect, not a CSS size).
 *   - Skeleton state during the first measurement frame.
 *   - Render-prop-style `renderTile` so consumers control cell content.
 *
 * USAGE:
 *   <SquarifiedTreemap
 *     items={sectors.map(s => ({ id: s.name, weight: s.market_cap, payload: s }))}
 *     renderTile={(cell) => <SectorTile sector={cell.item.payload} />}
 *     gap={2}
 *     minWidth={32}
 *     minHeight={22}
 *   />
 */

"use client";

import * as React from "react";
import { squarify, type TreemapCell } from "@/lib/treemap";
import { cn } from "@/lib/utils";

export interface SquarifiedTreemapItem<T> {
  id: string;
  /** Layout weight (e.g. market cap). Must be ≥ 0. */
  weight: number;
  payload: T;
}

export interface SquarifiedTreemapProps<T> {
  items: SquarifiedTreemapItem<T>[];
  renderTile: (
    cell: TreemapCell<SquarifiedTreemapItem<T>>,
    index: number,
  ) => React.ReactNode;
  /** Gap (px) between cells. Subtracted from cell w/h. Default 2. */
  gap?: number;
  /** Minimum cell width — below this the tile is hidden. Default 0 (show all). */
  minWidth?: number;
  /** Minimum cell height. Default 0. */
  minHeight?: number;
  className?: string;
  /** ARIA label for the layout region. */
  ariaLabel?: string;
  /**
   * Optional click handler. When provided, each tile becomes keyboard-reachable
   * (tabIndex=0, role=button, Enter/Space activation) and a focus ring renders.
   * Without this, tiles are static visual blocks (presentation role).
   */
  onTileClick?: (item: SquarifiedTreemapItem<T>, index: number) => void;
  /**
   * Per-tile aria-label resolver. Used together with `onTileClick` so each
   * focusable tile announces meaningful content to screen readers. The
   * absolute-positioned wrapper carries the label so SR users hear it on
   * focus, not via inner-tile traversal.
   */
  getTileAriaLabel?: (item: SquarifiedTreemapItem<T>) => string;
}

/**
 * SquarifiedTreemap — measures its container, runs the squarify algorithm,
 * and renders absolute-positioned tiles.
 *
 * WHY ResizeObserver (not window resize): the layout responds to PARENT size,
 * not viewport. Workspace panels can resize without a window event.
 *
 * WHY first-paint skeleton: until ResizeObserver fires we have no rect, so
 * tiles can't be positioned. Returning null would cause layout jump; a
 * skeleton-grey panel keeps the slot stable.
 */
export function SquarifiedTreemap<T>({
  items,
  renderTile,
  gap = 2,
  minWidth = 0,
  minHeight = 0,
  className,
  ariaLabel,
  onTileClick,
  getTileAriaLabel,
}: SquarifiedTreemapProps<T>) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState<{ w: number; h: number } | null>(null);

  // useLayoutEffect measures synchronously after the DOM commits but BEFORE
  // paint. This lets first-paint show real cells, not a skeleton flash.
  // jsdom returns 0×0 for getBoundingClientRect; we fall back to a sensible
  // default so the component still renders content in tests / SSR snapshots.
  // Real browsers will overwrite via ResizeObserver on the next frame anyway.
  React.useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const w = rect.width > 0 ? rect.width : el.clientWidth || 600;
    const h = rect.height > 0 ? rect.height : el.clientHeight || 400;
    setSize({ w, h });
  }, []);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (typeof ResizeObserver === "undefined") return; // jsdom may not provide it
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((prev) => {
        if (prev && Math.abs(prev.w - width) < 0.5 && Math.abs(prev.h - height) < 0.5) {
          return prev;
        }
        return { w: width, h: height };
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const cells = React.useMemo(() => {
    if (!size || size.w === 0 || size.h === 0) return [];
    return squarify(
      items.map((it) => ({ item: it, weight: it.weight })),
      { x: 0, y: 0, width: size.w, height: size.h },
    );
  }, [items, size]);

  return (
    <div
      ref={containerRef}
      role="group"
      aria-label={ariaLabel}
      className={cn("relative h-full w-full", className)}
    >
      {!size && (
        // First-paint skeleton — single grey block at full size.
        <div className="absolute inset-0 animate-pulse bg-muted/30 rounded-[2px]" />
      )}
      {cells.map((cell, i) => {
        const w = Math.max(0, cell.width - gap);
        const h = Math.max(0, cell.height - gap);
        if (w < minWidth || h < minHeight) return null;
        const isInteractive = !!onTileClick;
        return (
          <div
            key={cell.item.id}
            style={{
              position: "absolute",
              left: cell.x,
              top: cell.y,
              width: w,
              height: h,
            }}
            // PLAN-0059 H-QA-iter1: keyboard-reachability fix. Without
            // tabIndex/role the tile is a dead visual block — old grid layout
            // had focusable cells, treemap regression must be closed. We only
            // make it focusable when an onTileClick is provided (otherwise
            // there's no action to fire).
            tabIndex={isInteractive ? 0 : undefined}
            role={isInteractive ? "button" : undefined}
            aria-label={getTileAriaLabel?.(cell.item)}
            onClick={isInteractive ? () => onTileClick?.(cell.item, i) : undefined}
            onKeyDown={
              isInteractive
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onTileClick?.(cell.item, i);
                    }
                  }
                : undefined
            }
            className={isInteractive ? "focus:outline-none focus-visible:ring-1 focus-visible:ring-primary cursor-pointer" : undefined}
          >
            {renderTile(cell, i)}
          </div>
        );
      })}
    </div>
  );
}
