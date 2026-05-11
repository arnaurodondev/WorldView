/**
 * components/shell/HotkeyScope.tsx — Declarative scope + bindings registration.
 *
 * WHY THIS EXISTS: Pages that need their own chord bindings (e.g. the instrument
 * page wants D/F/N/I tab mnemonics; a Dialog wants to push "modal" scope) get
 * a single React component to drop in instead of writing useEffect plumbing.
 *
 *   <HotkeyScope
 *     scope="page"
 *     page="/instruments/"
 *     bindings={[
 *       { id: "ins.tab.overview", chord: "d", group: "Symbol", label: "DES — Overview", handler: () => setActiveTab("overview") },
 *       ...
 *     ]}
 *   />
 *
 * On mount: pushes the scope, registers each binding. On unmount: unregisters
 * all bindings, pops the scope. Re-running with new bindings (e.g., handlers
 * captured fresh closures) automatically replaces the prior set.
 *
 * WHY a component (not a hook): components compose well in JSX trees and make
 * the scope-push lifecycle visually obvious (`<HotkeyScope>` next to the
 * Dialog it modifies). A hook works too — both are exported.
 */

"use client";
// WHY "use client": uses useEffect to manage registration lifecycle.

import { useEffect, type ReactElement } from "react";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import type { HotkeyBinding, HotkeyScope as HotkeyScopeKind } from "@/lib/hotkey-registry";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * Bindings passed to <HotkeyScope> can omit `scope` and `page` — the scope
 * comes from the parent component's prop, and `page` from the optional `page`
 * prop. Authors thus declare only the chord-specific fields per binding.
 */
type ScopedBindingInput = Omit<HotkeyBinding, "scope" | "page"> & {
  /** Optional per-binding `when` predicate; rare but allowed. */
  when?: HotkeyBinding["when"];
};

interface HotkeyScopeProps {
  /**
   * Scope to push while this component is mounted. Bindings registered through
   * `bindings` are stamped with this scope automatically.
   *
   * - "modal":  push for blocking dialogs.
   * - "page":   per-route mnemonics (most common — instrument tabs, screener filters).
   * - "table" / "chart":  context-focused.
   * - "global": rarely passed directly; usually the framework's GlobalHotkeyBindings owns this.
   */
  readonly scope: HotkeyScopeKind;
  /**
   * Optional per-binding pathname predicate. Forwarded into each registered
   * binding so the registry only fires when window.location.pathname matches.
   */
  readonly page?: string | RegExp;
  /**
   * Bindings to register while mounted. Re-registers when the array reference
   * changes — pass a stable reference (useMemo) if you need to avoid churn.
   */
  readonly bindings: readonly ScopedBindingInput[];
}

export function HotkeyScope({ scope, page, bindings }: HotkeyScopeProps): ReactElement | null {
  const { pushScope, popScope, registry } = useHotkeyScope();

  // Push/pop the scope on mount/unmount (ref-counted in HotkeyContext).
  useEffect(() => {
    pushScope(scope);
    return () => popScope(scope);
  }, [scope, pushScope, popScope]);

  // Register the bindings. We re-run when bindings reference changes — the
  // caller controls churn via memoisation. Each register() returns an
  // unregister fn which we call on cleanup.
  useEffect(() => {
    const unsubs = bindings.map((b) =>
      registry.register({
        id: b.id,
        chord: b.chord,
        scope,
        group: b.group,
        label: b.label,
        handler: b.handler,
        when: b.when,
        page,
      }),
    );
    return () => {
      for (const u of unsubs) u();
    };
  }, [bindings, scope, page, registry]);

  // <HotkeyScope> is invisible — it only manages registration side-effects.
  return null;
}
