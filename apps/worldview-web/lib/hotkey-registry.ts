/**
 * lib/hotkey-registry.ts — Central keyboard chord registry.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 closes the audit's most damaging Layout finding
 * (F-LAYOUT-001) — the StatusBar advertised six chord shortcuts (G+D, G+S,
 * G+W, G+P, G+A, ⌘K) with NO global keyboard listener wired. Promised-but-
 * broken hotkeys destroy trust within 90 seconds of demo. This registry is
 * the single source of truth that:
 *
 *   1. The chord listener (`hooks/useChordHotkeys`) consumes to dispatch chords.
 *   2. The StatusBar (`components/shell/StatusBar`) reads to render hints —
 *      so it cannot advertise a chord that is not actually wired (structurally
 *      impossible to lie).
 *   3. The cheat-sheet overlay (`?` → `HotkeyCheatSheet`) reads to render the
 *      help — the user always sees the truth.
 *
 * WHY DATA-DRIVEN (not a global keymap object): chords are registered at runtime
 * by the components that own the actions. The instrument page registers `D/F/N/I`
 * mnemonics when it mounts; on unmount they are unregistered. Modal dialogs push
 * a "modal" scope that suspends global chords. Without runtime registration the
 * registry would have to enumerate every page's chords statically and carry the
 * action callbacks across the import graph — unmaintainable.
 *
 * WHY SCOPE STACK: per the deep-dive layout report (§7.3), keyboard input must
 * be routed by precedence:
 *     modal  >  input  >  chart  >  table  >  page  >  global
 * Inner scopes win. When a `<Dialog>` opens it pushes "modal" so global G-chords
 * suspend until the dialog closes. When focus is in an `<input>` the chord
 * listener auto-suspends (handled by useChordHotkeys), preserving regular typing.
 *
 * REFERENCE: Linear command-palette + chord pattern. Linear keeps every key in
 * a single registry that the help overlay (`?`) and command palette (`⌘K`)
 * both read — keys can never drift from advertised. Raycast uses the same model.
 */

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * Hotkey scope precedence — outer-most ("global") is the lowest priority,
 * inner-most ("modal") is the highest. The scope stack maintained by
 * `HotkeyProvider` is consulted top-down on every keypress.
 *
 * WHY this exact ordering:
 *   - "modal":   blocking dialogs (AlertDialog, AddTransactionDialog) own all
 *                keys; global chords must NOT fire while a modal is open.
 *   - "input":   text inputs (textarea, contenteditable) — auto-detected by
 *                useChordHotkeys via document.activeElement (no manual push).
 *   - "chart":   chart-focused contexts (zoom/log toggle/markers/compare).
 *   - "table":   table-focused contexts (j/k row nav, Space select).
 *   - "page":    per-route mnemonics (e.g., D/F/N/I on /instruments/[id]).
 *   - "global":  app-wide chords (g d, ⌘K, ?, ⌘B). Always present.
 */
export type HotkeyScope = "global" | "page" | "table" | "chart" | "input" | "modal";

/**
 * Group taxonomy for cheat-sheet rendering. The `?` overlay groups bindings
 * by `group` so users can scan related chords together. Values are display
 * strings — the cheat sheet uses them verbatim as section headers.
 */
export type HotkeyGroup =
  | "Navigation"     // g d, g s, g w, g p, g a, g n, g c, g h, g ,
  | "Symbol"         // /, ⌘K, instrument-page mnemonics (D/F/N/I)
  | "Action"         // ⌘E export, ⌘R refresh, ⌘D add to watchlist
  | "View"           // ⌘B sidebar, ⌘. statusbar, ⌘\\ split
  | "Editing";       // ⌘Z, ⌘S, etc. (reserved for forms)

/**
 * One hotkey binding. The pair `(scope, chord)` is the unique key — two scopes
 * may register the same chord if the inner one wins by precedence.
 *
 * `chord` is canonical lowercase, space-separated for chord sequences:
 *   - Single key:        "?"
 *   - Modifier:          "mod+k"  (mod = ⌘ on macOS, Ctrl elsewhere — handled by listener)
 *   - Two-key chord:     "g d"
 *   - Modifier + chord:  "shift+mod+e" (advanced; reserved)
 *
 * `handler` is called when the chord matches. It receives the KeyboardEvent so
 * it may e.preventDefault() if needed (the listener already does this for matched
 * chords). Returning a Promise is allowed — the listener does not await it.
 */
export interface HotkeyBinding {
  /** Stable identifier — used for deduplication and cheat-sheet keying. */
  readonly id: string;
  /** Canonical chord string (lowercase, space-separated). */
  readonly chord: string;
  /** Scope precedence — see HotkeyScope. */
  readonly scope: HotkeyScope;
  /** Display group for cheat-sheet sectioning. */
  readonly group: HotkeyGroup;
  /** Human-readable label shown in StatusBar + cheat sheet. */
  readonly label: string;
  /** Action invoked on chord match. */
  readonly handler: (e: KeyboardEvent) => void | Promise<void>;
  /**
   * Optional gating predicate — if provided and returns false, the chord is
   * treated as "not registered" for that keypress (allows higher scopes to
   * absorb the key). Used for context-sensitive bindings (e.g., a chart
   * pane's `c` compare-overlay key only when the chart is the focused panel).
   */
  readonly when?: () => boolean;
  /**
   * Optional pathname predicate — if provided, the binding only fires when
   * window.location.pathname matches. Used by `<HotkeyScope page="...">` to
   * scope per-route mnemonics. Accepts:
   *   - exact string ("/dashboard")
   *   - prefix string ending in "/" ("/instruments/" matches /instruments/AAPL)
   *   - RegExp
   */
  readonly page?: string | RegExp;
}

// ── Canonicalization ──────────────────────────────────────────────────────────

/**
 * canonicalChord — normalise a chord string for storage and matching.
 *
 * Rules:
 *   - lowercase
 *   - "cmd" or "meta" → "mod"  (canonical Apple/Windows-cross modifier)
 *   - "ctrl" → "mod"           (so mod+k matches both ⌘K on macOS and Ctrl+K elsewhere)
 *   - whitespace collapsed to single spaces
 *   - sequence chords stay space-separated ("g d")
 *
 * WHY lowercase: KeyboardEvent.key is "g" not "G" unless Shift is held. The
 * listener stores chord prefixes in lowercase to match.
 *
 * WHY mod alias: writing "cmd+k" on macOS but "ctrl+k" on Windows would fork
 * every binding — adopt one canonical form.
 */
export function canonicalChord(chord: string): string {
  return chord
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .split(" ")
    .map((part) =>
      part
        .split("+")
        .map((seg) => {
          if (seg === "cmd" || seg === "meta" || seg === "ctrl") return "mod";
          return seg;
        })
        .join("+"),
    )
    .join(" ");
}

/**
 * formatChordForDisplay — render a canonical chord as the platform-correct
 * display string for StatusBar + cheat sheet.
 *
 * Examples (macOS):
 *   "mod+k"  → "⌘K"
 *   "g d"    → "G D"
 *   "?"      → "?"
 *   "shift+mod+e" → "⇧⌘E"
 *
 * Non-macOS:
 *   "mod+k"  → "Ctrl+K"
 *
 * WHY platform-aware: macOS users expect ⌘ glyphs; Windows/Linux users expect
 * "Ctrl" text. Showing "⌘K" to a Linux user is confusing.
 *
 * WHY a function (not a per-binding `display` field): authors register chords
 * once in canonical form; the registry produces the right display string at
 * render time. Adding a new platform doesn't require auditing every binding.
 */
export function formatChordForDisplay(chord: string, isMac: boolean = detectMac()): string {
  return canonicalChord(chord)
    .split(" ")
    .map((part) =>
      part
        .split("+")
        .map((seg) => {
          if (seg === "mod") return isMac ? "⌘" : "Ctrl+";
          if (seg === "shift") return isMac ? "⇧" : "Shift+";
          if (seg === "alt" || seg === "option") return isMac ? "⌥" : "Alt+";
          if (seg === "enter" || seg === "return") return isMac ? "↵" : "Enter";
          if (seg === "escape" || seg === "esc") return "Esc";
          if (seg === "arrowup") return "↑";
          if (seg === "arrowdown") return "↓";
          if (seg === "arrowleft") return "←";
          if (seg === "arrowright") return "→";
          if (seg === "space") return "Space";
          // Single-letter or punctuation key — uppercase for display
          return seg.toUpperCase();
        })
        // On macOS the modifier glyphs concatenate without a separator (⇧⌘E),
        // matching Apple HIG. On other platforms we use "Ctrl+E" with the trailing "+".
        // The map above appends "+" to non-macOS modifiers; rejoining without a
        // separator collapses them correctly.
        .join(""),
    )
    .join(" ");
}

/**
 * detectMac — runtime platform detection. Tries navigator.platform first
 * (deprecated but still populated), falls back to userAgent. SSR-safe — returns
 * false when navigator is unavailable so server-rendered StatusBar shows
 * non-macOS strings, then the client takes over after hydration.
 */
function detectMac(): boolean {
  if (typeof navigator === "undefined") return false;
  // navigator.platform is deprecated; userAgentData is preferred but not on Safari.
  // For our use case (display-only) the legacy field is reliable enough.
  const platform = navigator.platform || (navigator.userAgent || "");
  return /Mac|iPhone|iPad|iPod/i.test(platform);
}

// ── Registry implementation ───────────────────────────────────────────────────

/**
 * HotkeyRegistry — process-singleton storage for active bindings.
 *
 * WHY a class (not a top-level Map): we want a single instance shared across
 * the app, but importing a mutable Map directly creates testing pain (the Map
 * is shared across test runs and pollutes between cases). A class lets us
 * instantiate a fresh registry per test via `new HotkeyRegistry()` while
 * exposing a default singleton (`hotkeyRegistry`) for production use.
 *
 * Bindings are keyed by `id` (must be unique per binding) plus an internal
 * (scope, chord) index for fast lookup during keypress dispatch.
 */
export class HotkeyRegistry {
  /** All bindings, keyed by stable id. Preserves registration order for stable cheat-sheet sort. */
  private readonly byId = new Map<string, HotkeyBinding>();

  /**
   * Bindings indexed by canonical chord string. Each chord may have multiple
   * bindings (one per scope) — the listener picks the inner-most active scope.
   * Order within the array reflects registration order.
   */
  private readonly byChord = new Map<string, HotkeyBinding[]>();

  /**
   * Set of all chord prefixes (e.g., "g " for the "g" prefix of "g d").
   * Used by the listener to know whether to keep the chord buffer alive
   * after a partial match — "g" alone is not a binding but is a prefix
   * of several, so we wait for the next key.
   */
  private prefixSet = new Set<string>();

  /**
   * Subscribers notified on every change (register/unregister). The cheat sheet
   * subscribes so the `?` overlay updates if a route mounts new mnemonics
   * while it's open. Provider exposes this via `subscribe`.
   */
  private readonly listeners = new Set<() => void>();

  /**
   * register — add a binding. If `id` already exists the existing binding is
   * replaced (last-wins) — useful for a re-rendering component re-registering
   * the same handler.
   *
   * Returns an unregister function for use in useEffect cleanup:
   *   useEffect(() => hotkeyRegistry.register(binding), [...]);
   */
  register(binding: HotkeyBinding): () => void {
    const canonical = canonicalChord(binding.chord);
    const normalised: HotkeyBinding = { ...binding, chord: canonical };

    // If this id was previously registered, remove the old entry from byChord
    // so we do not accumulate duplicates.
    const previous = this.byId.get(binding.id);
    if (previous) {
      const arr = this.byChord.get(previous.chord);
      if (arr) {
        const filtered = arr.filter((b) => b.id !== binding.id);
        if (filtered.length === 0) this.byChord.delete(previous.chord);
        else this.byChord.set(previous.chord, filtered);
      }
    }

    this.byId.set(binding.id, normalised);
    const arr = this.byChord.get(canonical) ?? [];
    arr.push(normalised);
    this.byChord.set(canonical, arr);

    this.rebuildPrefixSet();
    this.notify();

    return () => this.unregister(binding.id);
  }

  /**
   * unregister — remove a binding by id. Idempotent (safe to call multiple times).
   */
  unregister(id: string): void {
    const existing = this.byId.get(id);
    if (!existing) return;
    this.byId.delete(id);
    const arr = this.byChord.get(existing.chord);
    if (arr) {
      const filtered = arr.filter((b) => b.id !== id);
      if (filtered.length === 0) this.byChord.delete(existing.chord);
      else this.byChord.set(existing.chord, filtered);
    }
    this.rebuildPrefixSet();
    this.notify();
  }

  /**
   * lookup — find the best binding for a chord under the given active-scopes
   * set. Returns the inner-most-scope match where `when()` (if present) and
   * `page` (if present) both pass.
   *
   * WHY pass active scopes (not store them on the registry): scopes are owned
   * by HotkeyContext (the provider). The registry is scope-agnostic — it just
   * holds bindings. This lets the same registry serve different scope stacks
   * in tests (e.g., simulate a modal-open state without touching context).
   *
   * MODAL SHORT-CIRCUIT: when "modal" is on the active set, the lookup ONLY
   * considers modal-scoped bindings. No fall-through to global/page/etc. This
   * implements the design rule "blocking dialogs own all keys" — global G-chords
   * must NOT fire while an AlertDialog/AddTransactionDialog is open. Without
   * the short-circuit, a user pressing `g d` inside a modal would silently
   * navigate away, losing the modal's pending state.
   */
  lookup(
    chord: string,
    activeScopes: ReadonlySet<HotkeyScope>,
    pathname: string = "",
  ): HotkeyBinding | null {
    const canonical = canonicalChord(chord);
    const candidates = this.byChord.get(canonical);
    if (!candidates || candidates.length === 0) return null;

    // Modal short-circuit: if a modal is open, ONLY modal-scoped bindings fire.
    if (activeScopes.has("modal")) {
      for (const candidate of candidates) {
        if (candidate.scope !== "modal") continue;
        if (!matchesPage(candidate.page, pathname)) continue;
        if (candidate.when && !candidate.when()) continue;
        return candidate;
      }
      return null;
    }

    // Otherwise iterate scope precedence inner → outer.
    const order: HotkeyScope[] = ["input", "chart", "table", "page", "global"];
    for (const scope of order) {
      if (!activeScopes.has(scope)) continue;
      for (const candidate of candidates) {
        if (candidate.scope !== scope) continue;
        if (!matchesPage(candidate.page, pathname)) continue;
        if (candidate.when && !candidate.when()) continue;
        return candidate;
      }
    }
    return null;
  }

  /**
   * isPrefix — true if the given chord-buffer is a prefix of any registered
   * chord (e.g., "g" is a prefix of "g d", "g s", etc.). Used by the listener
   * to decide whether to hold the buffer for the next key or reset.
   */
  isPrefix(buffer: string): boolean {
    if (buffer === "") return false;
    return this.prefixSet.has(buffer + " ");
  }

  /** all — snapshot of every registered binding (for cheat sheet rendering). */
  all(): HotkeyBinding[] {
    return Array.from(this.byId.values());
  }

  /**
   * subscribe — observe registry changes. Returns an unsubscribe function.
   * Cheat sheet uses this so re-render reflects new mnemonics from a route mount.
   */
  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /**
   * clear — wipe all bindings. ONLY for tests. Production code never clears
   * the registry; it relies on per-binding unregister via cleanup callbacks.
   */
  clear(): void {
    this.byId.clear();
    this.byChord.clear();
    this.prefixSet.clear();
    this.notify();
  }

  // ── Internals ────────────────────────────────────────────────────────────────

  private rebuildPrefixSet(): void {
    this.prefixSet.clear();
    for (const chord of this.byChord.keys()) {
      // For "g d" build prefix "g " (note trailing space).
      const parts = chord.split(" ");
      for (let i = 1; i < parts.length; i++) {
        this.prefixSet.add(parts.slice(0, i).join(" ") + " ");
      }
    }
  }

  private notify(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch (err) {
        // A subscriber throwing must not corrupt the registry's notify loop.
        // We surface to the console so tests fail loudly without breaking the chain.
        // eslint-disable-next-line no-console
        console.error("[hotkey-registry] subscriber threw:", err);
      }
    }
  }
}

/**
 * matchesPage — predicate helper. A binding's optional `page` field can be:
 *   - undefined: matches any pathname (global default)
 *   - exact string ending in non-"/"  → equality match
 *   - prefix string ending in "/"     → startsWith match (e.g., "/instruments/")
 *   - RegExp                          → regex.test(pathname)
 */
function matchesPage(page: string | RegExp | undefined, pathname: string): boolean {
  if (page === undefined) return true;
  if (page instanceof RegExp) return page.test(pathname);
  if (page.endsWith("/")) return pathname.startsWith(page);
  return pathname === page;
}

// ── Default singleton ─────────────────────────────────────────────────────────

/**
 * hotkeyRegistry — the process-wide default registry used by useChordHotkeys
 * + StatusBar + HotkeyCheatSheet. Tests should construct fresh instances via
 * `new HotkeyRegistry()` to avoid cross-test pollution.
 */
export const hotkeyRegistry = new HotkeyRegistry();
