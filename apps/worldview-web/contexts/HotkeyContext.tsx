/**
 * contexts/HotkeyContext.tsx — Scope-stack provider for the hotkey registry.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 hotkey infrastructure (deep-dive layout §7.2).
 * The registry (`lib/hotkey-registry`) holds bindings; this context tracks which
 * scopes are currently active. When a `<Dialog>` opens it pushes "modal", which
 * suspends global G-chords until the dialog closes. When a chart pane gains
 * focus it pushes "chart", enabling the chart's mnemonics (l, c, m, +/-).
 *
 * WHY a context (not a singleton on the registry): scope state belongs to the
 * React tree — when a component unmounts we want its scope to pop automatically
 * via useEffect cleanup. Storing scopes on the registry would require manual
 * push/pop without React's lifecycle guarantees.
 *
 * WHY useSyncExternalStore for the registry version: the cheat sheet + StatusBar
 * read from the registry but the registry is a non-React class. Without
 * useSyncExternalStore React 19's concurrent rendering can show stale chords.
 * The store-snapshot pattern is the standard React-19-blessed escape hatch.
 *
 * USAGE:
 *   <HotkeyProvider>
 *     <App />  {/* useChordHotkeys is mounted inside via GlobalHotkeyBindings *\/}
 *   </HotkeyProvider>
 *
 *   const { pushScope, popScope } = useHotkeyScope();
 *   useEffect(() => { pushScope("modal"); return () => popScope("modal"); }, []);
 */

"use client";
// WHY "use client": uses React state, effects, and DOM event listeners — all
// browser-only.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  hotkeyRegistry as defaultRegistry,
  type HotkeyBinding,
  type HotkeyRegistry,
  type HotkeyScope,
} from "@/lib/hotkey-registry";

// ── Context shape ─────────────────────────────────────────────────────────────

/**
 * The public API exposed via useHotkeyScope().
 *
 * `activeScopes` is a ReadonlySet — the set of scopes currently on the stack
 * plus "global" (which is always on). Consumers rarely need this directly;
 * the chord listener uses it via the provider's internal state.
 *
 * `pushScope` / `popScope` are reference-counted: pushing the same scope twice
 * requires two pops to remove. This handles nested dialogs correctly (two
 * modals → still in "modal" scope until both close).
 */
export interface HotkeyScopeContextValue {
  readonly activeScopes: ReadonlySet<HotkeyScope>;
  readonly pushScope: (scope: HotkeyScope) => void;
  readonly popScope: (scope: HotkeyScope) => void;
  /**
   * resetScopes — collapse every active scope back to the singleton ["global"]
   * baseline. Required by the logout flow per PRD-0089 W1 plan C-28: when the
   * user signs out, any modal/drawer/popover that pushed a scope should be
   * cleared synchronously so the next user (or the same user on re-login) does
   * not inherit a poisoned scope stack. Ref-counted internals are cleared in
   * one operation — no need to walk the count map.
   */
  readonly resetScopes: () => void;
  /** The registry instance bound to this provider — exposed for tests + advanced use. */
  readonly registry: HotkeyRegistry;
}

const HotkeyScopeContext = createContext<HotkeyScopeContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

interface HotkeyProviderProps {
  children: ReactNode;
  /**
   * Optional registry override — defaults to the process singleton. Tests pass
   * a fresh `new HotkeyRegistry()` to isolate from other test runs.
   */
  registry?: HotkeyRegistry;
  /**
   * Optional initial scope set — defaults to ["global"]. Useful in tests that
   * want to simulate "modal is already open" without firing a push.
   */
  initialScopes?: readonly HotkeyScope[];
}

export function HotkeyProvider({
  children,
  registry = defaultRegistry,
  initialScopes,
}: HotkeyProviderProps) {
  // WHY ref-counted scope counts (not a stack): two nested dialogs both push
  // "modal"; popping one shouldn't deactivate the scope until both close.
  // Using a count map guarantees correctness independent of push/pop interleaving.
  const scopeCountsRef = useRef<Map<HotkeyScope, number>>(
    new Map((initialScopes ?? ["global"]).map((s) => [s, 1])),
  );

  // The set surface re-renders consumers on change. We derive it from the
  // ref-counted map and only flip the state when the active set actually changes
  // (a count going from 1→2 doesn't change which scopes are active).
  const [activeScopes, setActiveScopes] = useState<ReadonlySet<HotkeyScope>>(() =>
    new Set(scopeCountsRef.current.keys()),
  );

  const pushScope = useCallback((scope: HotkeyScope) => {
    const counts = scopeCountsRef.current;
    const prev = counts.get(scope) ?? 0;
    counts.set(scope, prev + 1);
    if (prev === 0) {
      // Scope was inactive → flip the public set.
      setActiveScopes(new Set(counts.keys()));
    }
  }, []);

  const popScope = useCallback((scope: HotkeyScope) => {
    const counts = scopeCountsRef.current;
    const prev = counts.get(scope) ?? 0;
    if (prev <= 1) {
      counts.delete(scope);
      setActiveScopes(new Set(counts.keys()));
    } else {
      counts.set(scope, prev - 1);
    }
  }, []);

  const resetScopes = useCallback(() => {
    // PRD-0089 W1 C-28: collapse the entire ref-counted stack and re-seed with
    // only "global". The safety-net useEffect below re-pushes "global" if it
    // happens to be missing, but we set it explicitly here so the next render
    // already reflects the cleared state.
    const counts = scopeCountsRef.current;
    counts.clear();
    counts.set("global", 1);
    setActiveScopes(new Set(["global"]));
  }, []);

  // The "global" scope is always on. If the consumer accidentally pops it, we
  // re-add it on the next render. This is a safety net — the API doesn't
  // expose a way to deliberately lose "global".
  useEffect(() => {
    if (!activeScopes.has("global")) {
      pushScope("global");
    }
  }, [activeScopes, pushScope]);

  const value = useMemo<HotkeyScopeContextValue>(
    () => ({ activeScopes, pushScope, popScope, resetScopes, registry }),
    [activeScopes, pushScope, popScope, resetScopes, registry],
  );

  return (
    <HotkeyScopeContext.Provider value={value}>{children}</HotkeyScopeContext.Provider>
  );
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * useHotkeyScope — read scope state and dispatch push/pop.
 *
 * Throws if called outside a `<HotkeyProvider>` so missing-provider mistakes
 * surface as loud test failures, not silently broken chords.
 */
export function useHotkeyScope(): HotkeyScopeContextValue {
  const ctx = useContext(HotkeyScopeContext);
  if (!ctx) {
    throw new Error(
      "useHotkeyScope() must be used inside a <HotkeyProvider>. " +
        "Mount HotkeyProvider near the top of the app tree.",
    );
  }
  return ctx;
}

/**
 * useHotkeyBindings — subscribe to the registry and re-render on changes.
 *
 * Returns a snapshot of all currently registered bindings. The cheat-sheet
 * overlay and StatusBar use this so when a route mount registers new mnemonics
 * the UI immediately reflects them (no manual refresh).
 *
 * Uses useSyncExternalStore (React 18+) to safely bridge our class-based
 * registry into React's render system. Without it, concurrent rendering may
 * show stale binding lists.
 *
 * If `registry` is omitted, the hook reads from HotkeyProvider's contextual
 * registry. This means tests that pass a custom registry to <HotkeyProvider>
 * work end-to-end without manual plumbing through every consumer.
 */
export function useHotkeyBindings(registry?: HotkeyRegistry): readonly HotkeyBinding[] {
  // PLAN-0059 W0 fix F-007 (verbatimModuleSyntax + readonly hygiene):
  // EMPTY_BINDINGS is `readonly HotkeyBinding[]` (Object.freeze([])); the
  // hook now returns the readonly type to honour the SSR-snapshot guarantee
  // and avoid TS4104. Consumers should not mutate the returned list anyway.
  // PLAN-0059 W1 fix (2026-04-30): default to the contextual registry (via
  // useHotkeyScope) instead of defaultRegistry. This way <HotkeyCheatSheet>
  // and <StatusBar> automatically read from whichever registry the surrounding
  // <HotkeyProvider> was given — including custom test registries.
  const ctx = useContext(HotkeyScopeContext);
  const reg = registry ?? ctx?.registry ?? defaultRegistry;
  return useSyncExternalStore(
    // subscribe — registry calls fn() on every register/unregister.
    useCallback((onChange: () => void) => reg.subscribe(onChange), [reg]),
    // getSnapshot — must return a stable reference until the underlying data changes.
    // We cache the last snapshot and only rebuild when notify fires.
    useCallback(() => snapshotBindings(reg), [reg]),
    // server snapshot — empty list during SSR (no bindings registered server-side).
    () => EMPTY_BINDINGS,
  );
}

const EMPTY_BINDINGS: readonly HotkeyBinding[] = Object.freeze([]);

/**
 * Per-registry snapshot cache — useSyncExternalStore demands a stable reference
 * across calls when the underlying data hasn't changed; otherwise React 18 will
 * loop infinitely. The cache holds (epoch, arr) per registry, where the epoch
 * is incremented each time THAT registry notifies. Listeners are lazily
 * attached the first time a registry is observed.
 *
 * PLAN-0059 W1 fix (2026-04-30): the previous version used a single global
 * epoch attached only to the default registry. Tests passing a fresh
 * `new HotkeyRegistry()` to <HotkeyProvider> never bumped the global epoch,
 * so the cached snapshot was treated as fresh and the cheat sheet showed
 * stale (empty) bindings. The per-registry epoch closes that hole.
 */
const snapshotCache = new WeakMap<
  HotkeyRegistry,
  { epoch: number; arr: readonly HotkeyBinding[] }
>();
const registryEpochs = new WeakMap<HotkeyRegistry, number>();
const registryListenersAttached = new WeakSet<HotkeyRegistry>();

function ensureSubscribed(reg: HotkeyRegistry): void {
  if (registryListenersAttached.has(reg)) return;
  registryListenersAttached.add(reg);
  registryEpochs.set(reg, 0);
  reg.subscribe(() => {
    registryEpochs.set(reg, (registryEpochs.get(reg) ?? 0) + 1);
  });
}

function snapshotBindings(reg: HotkeyRegistry): readonly HotkeyBinding[] {
  ensureSubscribed(reg);
  const epoch = registryEpochs.get(reg) ?? 0;
  const cached = snapshotCache.get(reg);
  if (cached && cached.epoch === epoch) return cached.arr;
  const arr: readonly HotkeyBinding[] = reg.all();
  snapshotCache.set(reg, { epoch, arr });
  return arr;
}

// Eagerly subscribe to the default registry so the very first useHotkeyBindings
// call doesn't miss a notify that fired between module load and React mount.
ensureSubscribed(defaultRegistry);
