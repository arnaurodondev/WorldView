# QA Report: PLAN-0059-B — Workflow Grammar (Hotkeys, Cheat Sheet, Bloomberg Mnemonics)

**Date**: 2026-04-30 20:00 UTC
**Skill**: qa
**Scope**: plan-scoped — PLAN-0059-B (Workflow Grammar, Wave 1 Track A)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL — 2 BLOCKING test gaps + 1 CRITICAL security finding unresolved
**Report file**: docs/audits/2026-04-30-qa-plan-0059-b-report.md
**Compared against**: docs/audits/2026-04-30-deep-remediation-master-report.md (Bloomberg-grade goals)

---

## Executive Summary

PLAN-0059-B implemented the keyboard-driven workflow grammar layer for the institutional terminal: `lib/hotkey-registry.ts` (chord registry), `hooks/useChordHotkeys.ts` (global listener), `contexts/HotkeyContext.tsx` (scope stack), `components/shell/HotkeyCheatSheet.tsx` (auto-derived `?` overlay), `components/shell/StatusBar.tsx` (live registry reader), `components/shell/GlobalHotkeyBindings.tsx` (navigation chords), and Bloomberg mnemonics (D/F/N/I) on `/instruments/[id]`. The five specialist agents reviewed all deliverables against the master report goals.

**Architecture verdict**: CLEAN — all 8 PRD mandates satisfied. The core structural fix (StatusBar reads from registry, making it structurally impossible to advertise an unwired chord) is correctly implemented. The scope stack (modal > input > chart > table > page > global), 1.2s chord-reset, and Bloomberg instrument mnemonics all work correctly per architecture review.

**Test suite**: 934 tests pass, 0 failures, across 87 test files. TypeScript clean. ESLint clean (one deprecation warning only).

**Live platform**: 59 containers healthy. Key endpoints verified: `/v1/briefings/morning` (200, full data), `/v1/market/heatmap` (200), `/v1/market/top-movers` (200, 8 instruments), `/v1/portfolios` (200), `/v1/search/instruments` (200). Market-data price changes show 0.00% — expected for local dev seed data.

**Failure reason**: Two BLOCKING test gaps — the plan mandated specific integration tests for modal chord suppression and instrument mnemonic navigation, and these are absent. One CRITICAL security finding (keyboard injection via synthetic events) requires a test-infrastructure update before it can be landed.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 12 | 5 | 2 | 1 | 2 | 0 | 0 |
| Security | 8 | 5 | 1 | 1 | 1 | 2 | 0 |
| Data Platform / Product | 4 | 3 | 0 | 1 | 1 | 1 | 0 |
| Distributed Systems | 7 | 5 | 0 | 2 | 3 | 0 | 0 |
| Architecture | 12 | 0 | 0 | 0 | 0 | 1 | 0 |
| **Total** | — | **18** | **3** | **5** | **7** | **3** | **0** |

### Cross-Agent Signals (HIGH Confidence)
- **Security + DS**: `AlertStreamContext.tsx` JWT-in-URL WebSocket pattern is independently flagged as BLOCKING by Security (F-SEC-004) and as a reconnect storm risk by DS (F-DS-005) — both issues from the same file, highest confidence dual-signal.
- **QA + Architecture**: The F-LAYOUT-001 fix (registry-driven StatusBar) is confirmed implemented correctly by two independent agents — HIGH confidence PASS signal.

### Fixes Applied in This QA Pass
| Finding | Fix | Status |
|---------|-----|--------|
| F-SEC-001 | Attempted `!e.isTrusted` guard — reverted; breaks fireEvent-based tests | REVERTED — see F-SEC-001 for required test-infra change |

### Open Items
| Finding | Status | Owner |
|---------|--------|-------|
| F-QA-001 | Open BLOCKING — must fix before PASS | PLAN-0059-B |
| F-QA-002 | Open BLOCKING — must fix before PASS | PLAN-0059-B |
| F-SEC-001 | Open CRITICAL — fix requires test-infra update | PLAN-0059-B follow-up |
| F-SEC-004 | Open BLOCKING — JWT in WS URL (scoped to PLAN-0059-D) | PLAN-0059-D |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | — | — | 0 | — | PASS |
| Lint (ESLint) | worldview-web | — | — | 0 | — | PASS |
| Type Check (tsc) | worldview-web | — | — | 0 | — | PASS |
| Frontend Unit (Vitest) | worldview-web | 934 | 934 | 0 | 0 | PASS |
| Integration | all services | — | — | — | — | NOT_RUN (infra separate) |
| E2E (Playwright) | worldview-web | — | — | — | — | NOT_RUN |
| Python services (unit) | all services | — | — | — | — | OUT_OF_SCOPE |

**Note**: Python service tests not re-run — PLAN-0059-B is frontend-only; no Python files were modified.

### Live Platform Validation (59/59 containers healthy)

| Endpoint | Expected | Result | Status |
|----------|----------|--------|--------|
| `POST /v1/auth/dev-login` | 200 + token | 200 ✅ | PASS |
| `GET /v1/briefings/morning` | 200 + narrative | 200 ✅ | PASS |
| `GET /v1/market/heatmap` | 200 + sectors | 200 ✅ | PASS |
| `GET /v1/market/top-movers` | 200 + results | 200 ✅ | PASS |
| `GET /v1/portfolios` | 200 | 200 ✅ | PASS |
| `GET /v1/watchlists` | 200 | 200 ✅ | PASS |
| `GET /v1/search/instruments?q=AAPL` | 200 + results | 200 ✅ | PASS |
| `GET /v1/news/top` | 200 + items | 200, 0 items ⚠️ | WARN (data gap) |
| `GET /v1/quotes/stream` (WS) | WS upgrade | 400 (expected: no WS client) | PASS |
| Frontend `localhost:3001/` | HTML 200 | 200 ✅ | PASS |

**Market data note**: Top movers shows 8 instruments all at 0.00% change. This is expected behavior in local dev with seeded data (market prices are static). Not a PLAN-0059-B issue.

---

## Issues — Full Investigation

---

## Issue F-QA-001: Missing modal scope chord-suppression integration test (BLOCKING)

### Summary
PLAN-0059-B B-1 mandated `test_chord_suspended_when_modal_open` as a critical acceptance test. This test was listed in the plan's "Critical tests to ensure" section. It does not exist. The registry unit tests cover `lookup()` modal behavior, but no integration test verifies that the `useChordHotkeys` listener + `HotkeyContext` modal scope together actually suppress global G-chords.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA/Test

### Root Cause Analysis
- **What**: The `__tests__/use-chord-hotkeys.test.tsx` file covers happy-path chord matching, input suspension, and chord reset, but the test for pushing "modal" scope via `HotkeyProvider.initialScopes` and then firing a global chord is absent.
- **Why**: The modal short-circuit in `registry.lookup()` (line 329-338 of hotkey-registry.ts) is correct, but the integration path through `HotkeyContext.pushScope("modal")` → `useChordHotkeys` active-scopes ref → lookup is untested end-to-end.
- **When**: During demo, if a dialog opens and the user types a chord letter while the dialog is in focus, the chord must not fire navigation. Without this test, a regression here would not be caught.
- **Where**: `apps/worldview-web/__tests__/use-chord-hotkeys.test.tsx`

### Evidence
```
Grep "modal" in use-chord-hotkeys.test.tsx → 0 results
Grep "pushScope\|initialScopes.*modal\|modal.*scope" in __tests__/ → 0 results
```

### Impact
- **Immediate**: No regression protection for the modal chord-suppression behavior.
- **Blast radius**: If broken, pressing `g d` inside a dialog would navigate away, losing the dialog's state.
- **User impact**: Critical trust-destroying behavior in a demo.

### Solution Options

#### Option A: Add integration test to existing use-chord-hotkeys.test.tsx
**Changes required**:
- `apps/worldview-web/__tests__/use-chord-hotkeys.test.tsx` — add test:
```tsx
it("suspends global chords when modal scope is active", () => {
  const handler = vi.fn();
  const reg = new HotkeyRegistry();
  reg.register({ id: "nav.dashboard", chord: "g d", scope: "global",
    group: "Navigation", label: "Dashboard", handler });
  render(
    <HotkeyProvider registry={reg} initialScopes={new Set(["global", "modal"])}>
      <GlobalHotkeyBindings onToggleSidebar={vi.fn()} />
    </HotkeyProvider>
  );
  fireEvent.keyDown(document, { key: "g", bubbles: true });
  fireEvent.keyDown(document, { key: "d", bubbles: true });
  expect(handler).not.toHaveBeenCalled();
});
```
**Effort**: Low
**Risk**: Low

### Recommended Option
**Option A** — 15-minute fix. Add the test.

### Verification Steps
- [ ] `pnpm test -- hotkey` passes with new test
- [ ] Test confirms handler is NOT called when modal scope is active

---

## Issue F-QA-002: Missing instrument mnemonic integration test (BLOCKING)

### Summary
PLAN-0059-B B-5 mandated `test_instrument_page_d_chord_jumps_to_overview_tab`. The instrument page correctly implements Bloomberg mnemonics (verified by Architecture agent) but no test exercises the end-to-end path: mount instrument page → register D/F/N/I bindings via HotkeyScope → fire keydown → verify tab switch.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA/Test

### Root Cause Analysis
- **What**: `apps/worldview-web/__tests__/instrument-detail.test.tsx` exists (23 tests) but contains zero hotkey/mnemonic tests.
- **Why**: Instrument page mnemonics were added via `<HotkeyScope>` but the test file was not extended with mnemonic coverage.

### Evidence
```
Grep "chord\|mnemonic\|HotkeyScope\|keyDown.*d\|key.*overview" in __tests__/instrument-detail.test.tsx → 0 results
```
The implementation at `app/(app)/instruments/[entityId]/page.tsx:277-324` is correct.

### Solution

Add to `apps/worldview-web/__tests__/instrument-detail.test.tsx`:
```tsx
it("D chord navigates to overview tab (Bloomberg DES mnemonic)", async () => {
  // mount InstrumentPageHotkeyBindings (extract from page.tsx or mount full page with mocks)
  const onTabChange = vi.fn();
  render(
    <HotkeyProvider registry={hotkeyRegistry}>
      <InstrumentPageHotkeyBindings activeTab="fundamentals" onTabChange={onTabChange} />
    </HotkeyProvider>
  );
  fireEvent.keyDown(document, { key: "d", bubbles: true });
  expect(onTabChange).toHaveBeenCalledWith("overview");
});
```

**Effort**: Low (30 min)
**Verification**: `pnpm test -- instrument-detail` passes.

---

## Issue F-QA-003: No tests for HotkeyContext push/pop ref-counting (CRITICAL)

### Summary
The `HotkeyContext.tsx` implements a ref-counted scope stack (e.g., push "modal" twice → needs two pops to leave modal scope). This logic is untested. A bug here would silently break chord routing for nested dialogs.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA/Test

### Evidence
```
No file: apps/worldview-web/__tests__/hotkey-context.test.tsx
```

### Solution
Create `apps/worldview-web/__tests__/hotkey-context.test.tsx` with 5 tests:
1. Pushing a scope twice increments refcount (scope stays after one pop)
2. Second pop removes scope from activeScopes
3. Pushing "global" is a no-op (always present)
4. `activeScopes` Set updates only when scope list changes
5. `useHotkeyBindings` returns stable empty array on server (SSR snapshot)

**Effort**: Medium (1-2 hours)

---

## Issue F-SEC-001: Keyboard injection via synthetic events (CRITICAL)

### Summary
`hooks/useChordHotkeys.ts` processes every `keydown` event without checking `e.isTrusted`. A malicious script can dispatch synthetic keyboard events to trigger hotkeys: `document.dispatchEvent(new KeyboardEvent('keydown', {key:'d', bubbles:true}))`.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Security

### Root Cause Analysis
- **What**: Line 186 of `useChordHotkeys.ts` begins processing without checking `e.isTrusted`.
- **Why**: The fix was attempted in this QA pass but reverted because `@testing-library/react`'s `fireEvent` creates untrusted events. Adding `if (!e.isTrusted) return;` broke all 10 chord-listener tests.
- **When**: Exploitable if XSS occurs anywhere in the app — a script can then silently fire navigation chords.

### Evidence
```ts
// hooks/useChordHotkeys.ts:186 — no isTrusted guard
function onKeyDown(e: KeyboardEvent): void {
  // Always honour Escape: ...
  if (e.key === "Escape") {
    clearBuffer();
  }
  // ... processes all events
```

### Solution Options

#### Option A: Update tests to use trusted-event dispatch
Replace `fireEvent.keyDown(document, ...)` in use-chord-hotkeys tests with:
```ts
function fireTrustedKey(key: string, options: KeyboardEventInit = {}): void {
  const evt = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...options });
  Object.defineProperty(evt, "isTrusted", { value: true });
  document.dispatchEvent(evt);
}
```
Then add the guard:
```ts
if (!e.isTrusted) return;
```
**Effort**: Medium (2-3 hours — update ~15 fireEvent calls)
**Risk**: Low

#### Option B: VITEST environment flag
Check `process.env.NODE_ENV === 'test'` to skip the guard in tests.
**Risk**: High — weakens security in test parity. Rejected.

### Recommended Option
**Option A** — Update test helpers + add the guard. This is the correct institutional approach.

---

## Issue F-SEC-004: JWT token in WebSocket URL query string (BLOCKING — PLAN-0059-D scope)

### Summary
`AlertStreamContext.tsx:162` embeds the ws-token in the WebSocket URL. Tokens in URLs appear in server logs, browser history, and CDN access logs.

### Severity / Confidence
**Severity**: BLOCKING (for production deploy; acceptable for local dev)
**Confidence**: HIGH
**Flagged by**: Security

### Evidence
```ts
// contexts/AlertStreamContext.tsx:162
`${wsBase}/v1/alerts/stream?token=${encodeURIComponent(tokenData.token)}`
```

The comment acknowledges "30s TTL limits exposure window" — this is insufficient; replay within 30s is a valid attack window.

### Solution
Implement WebSocket sub-protocol authentication (RFC 6455 `Sec-WebSocket-Protocol` header). This is already planned in PLAN-0059-D (D-3). No action needed in PLAN-0059-B, but flagged here for tracking.

**Scope**: PLAN-0059-D D-3

---

## Issue F-DS-001: Timer cleanup on fast route navigation (MAJOR)

### Summary
When a user navigates away from `/instruments/AAPL` while a 1.2s chord-reset timer is pending, the cleanup in `useChordHotkeys` calls `clearBuffer()` which calls `clearTimeout()`. This IS implemented correctly — the cleanup at line 276 is safe.

**Verdict**: FALSE POSITIVE from DS agent. The cleanup correctly clears the timer. No action needed.

---

## Issue F-DS-002: Snapshot cache race in HotkeyContext (MAJOR)

### Summary
`useHotkeyBindings()` uses a per-registry WeakMap cache with `ensureSubscribed()` to track subscriptions. The DS agent flagged a theoretical race where concurrent renders may call `ensureSubscribed()` twice with the same registry. The architecture agent confirmed the WeakMap-based fix (epoch tracking) was implemented correctly in the PLAN-0059 session. This is a LOW confidence risk under normal usage patterns.

**Verdict**: LOW confidence risk. No immediate action required. Add a `hasSubscribed` guard per registry instance if the pattern proves problematic under React 18 concurrent stress tests.

---

## Issue F-DS-004: Scope push/pop race in React 18 concurrent mode (MAJOR)

### Summary
`HotkeyContext.pushScope/popScope` reads and modifies `scopeCountsRef.current` without atomic guarantees. Two concurrent renders calling `pushScope("modal")` simultaneously could corrupt the count.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: MEDIUM

### Evidence
```ts
// HotkeyContext.tsx:110-117
const pushScope = useCallback((scope: HotkeyScope) => {
  const prev = scopeCountsRef.current.get(scope) ?? 0;
  scopeCountsRef.current.set(scope, prev + 1);
  if (prev === 0) setActiveScopes(/* ... */);
}, []);
```

In React 18 concurrent mode, if two effects fire simultaneously, `scopeCountsRef.current.get(scope)` may return `0` for both, causing a double `setActiveScopes` call with `prev === 0` condition true for both.

### Solution
Wrap the count modification in a `queueMicrotask` or use a state reducer that operates atomically:
```ts
const pushScope = useCallback((scope: HotkeyScope) => {
  setScopeCounts(prev => {
    const count = prev.get(scope) ?? 0;
    return new Map(prev).set(scope, count + 1);
  });
}, []);
```
And derive `activeScopes` from `scopeCounts` state via a `useMemo`.

**Effort**: Medium (2-3 hours refactor)

---

## Issue F-PROD-001: Missing chord wires — `g h`, `mod+k` cheat-sheet listing (CRITICAL)

### Summary
The plan (B-1, §7.3 of master report) listed `g h` (History/cheat sheet alias) and `mod+k` (command palette) as navigation grammar elements. `g h` is noted in the GlobalHotkeyBindings comment as "alias for `?`" but is NOT registered as a chord. `mod+k` is noted as "existing GlobalSearch handles it" and is NOT in the hotkey registry — meaning it won't appear in the cheat sheet when a user presses `?`.

### Severity / Confidence
**Severity**: CRITICAL (for demo credibility — cheat sheet shows incomplete list)
**Confidence**: HIGH
**Flagged by**: Product Completeness

### Evidence
```ts
// GlobalHotkeyBindings.tsx:17
// g h  →  cheat-sheet (alias for `?`)
```
But searching the bindings list (lines 95-116) — `g h` is NOT registered.

Similarly, no entry for `mod+k` in the binding list.

### Impact
When a BlackRock evaluator presses `?` to see the cheat sheet, they will not see:
- `mod+k` listed (they may press it and find the GlobalSearch cmdk modal works, but it's invisible from the cheat sheet)
- `g h` not listed or wired

### Solution
Add to `GlobalHotkeyBindings.tsx` bindings list:
```ts
// g h → open cheat sheet (Bloomberg alias; ? is the canonical binding)
{
  id: "shell.help.cheatsheet.alt",
  chord: "g h",
  scope: "global",
  group: "Navigation",
  label: "Open keyboard help",
  handler: () => { /* fire ? binding or open cheat sheet directly */ },
},
// mod+k → open command palette
{
  id: "shell.palette.open",
  chord: "mod+k",
  scope: "global",
  group: "Symbol",
  label: "Open command palette (⌘K)",
  handler: () => onFocusSearch?.(),  // existing handler
},
```

**Effort**: Low (30 minutes)

---

## Issue F-PROD-002: `/` search chord conditional — PRIORITY_IDS silent miss (MAJOR)

### Summary
The `shell.search.focus` binding is only registered when `onFocusSearch` prop is provided. However, `StatusBar.tsx:62` includes `"shell.search.focus"` in `PRIORITY_IDS` — if the binding is not registered, the StatusBar silently skips it (correct behavior), but the slot is wasted instead of filling with the next chord.

**Severity**: MAJOR
**File**: `components/shell/StatusBar.tsx:62`
**Confidence**: HIGH

**Solution**: Move `shell.search.focus` to the end of `PRIORITY_IDS` so the 6 navigation chords always fill first, and search focus is shown only if registered.

**Auto-fixable**: YES — 1 line reorder.

---

## Issue F-QA-004: GlobalHotkeyBindings has no test file (MAJOR)

### Summary
`components/shell/GlobalHotkeyBindings.tsx` registers all G-navigation chords and the sidebar toggle. It has NO corresponding test file. The chord infrastructure is tested (hotkey-registry.test.ts + use-chord-hotkeys.test.tsx) but the critical binding declarations themselves (router.push paths) are untested.

**Severity**: MAJOR
**Confidence**: HIGH

**Solution**: Create `__tests__/global-hotkey-bindings.test.tsx`:
- Mock `useRouter`, render `GlobalHotkeyBindings`, fire each G-chord, verify `router.push(path)` called with correct destination.
- ~9 tests for the 9 navigation chords + 1 for sidebar toggle.

**Effort**: Medium (1-2 hours)

---

## Implementation Status vs. Bloomberg Goals

| Feature | Plan Goal | Implemented | Evidence |
|---------|-----------|-------------|----------|
| `g d/p/s/w/a/n/c/,` | Navigation chords | ✅ DONE | GlobalHotkeyBindings.tsx:97-105 |
| `g h` | Cheat sheet alias | ❌ MISSING | Comment-only, not registered |
| `mod+b` | Sidebar toggle | ✅ DONE | GlobalHotkeyBindings.tsx:108-115 |
| `mod+k` | Command palette | ⚠️ PARTIAL | cmdk handles it natively but not in registry/cheatsheet |
| `/` | Focus search | ⚠️ CONDITIONAL | Only registered if `onFocusSearch` prop provided |
| `?` | Cheat sheet | ✅ DONE | HotkeyCheatSheet.tsx:62-68 |
| D/F/N/I mnemonics | Bloomberg instrument page | ✅ DONE | instruments/[entityId]/page.tsx:277-324 |
| StatusBar reads registry | No lying | ✅ DONE | StatusBar.tsx:68-92 |
| 1.2s chord reset | Spec | ✅ DONE | useChordHotkeys.ts:44 |
| Modal scope suppression | Scope stack | ✅ DONE | hotkey-registry.ts:329-338 |
| Input suspension | Scope stack | ✅ DONE | useChordHotkeys.ts:69-85 |
| Architecture clean | 8/8 mandates | ✅ DONE | Architecture agent: all pass |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| TypeScript typecheck | PASS | `tsc --noEmit` exits 0 |
| ESLint | PASS | 0 errors; 1 `next lint` deprecation warning |
| Dead deps | PASS | Wave A-2 removed react-grid-layout, react-resizable, @radix-ui/react-toast |
| Brand assets | PASS | `public/manifest.webmanifest` present; icons wired |
| Color tokens | PASS | `--positive: 150 100% 41%`, `--negative: 350 100% 62%`, `.dark --muted-foreground: 55%` all correct |
| isTrusted guard | FAIL | Not implemented — requires test infrastructure update first |
| JWT in WS URL | WARN | Known issue; 30s TTL; fix in PLAN-0059-D |

---

## Recommendations (Priority Order)

1. **[30 min] Add `test_chord_suspended_when_modal_open`** (F-QA-001) — critical to verify modal safety before demo.
2. **[30 min] Add `test_instrument_page_d_chord_jumps_to_overview_tab`** (F-QA-002) — validates most-visible Bloomberg feature.
3. **[30 min] Wire `g h` and `mod+k` into registry** (F-PROD-001) — cheat sheet must be complete for demo.
4. **[2 hrs] Create `__tests__/hotkey-context.test.tsx`** (F-QA-003) — ref-counting untested is a regression risk.
5. **[1 hr] Create `__tests__/global-hotkey-bindings.test.tsx`** (F-QA-004) — router.push destinations have no regression protection.
6. **[2 hrs] Add `e.isTrusted` guard with trusted-event test helpers** (F-SEC-001) — institutional-grade security hardening.
7. **[30 min] Reorder StatusBar `PRIORITY_IDS`** (F-PROD-002) — minor but trivially fixable.
8. **[3 hrs] Scope push/pop refactor to state-based atomic mutation** (F-DS-004) — React 18 concurrent mode safety.

**After items 1-3**: Verdict becomes PASS_WITH_WARNINGS.
**After all 8**: Verdict becomes PASS.

---

## New Bug Patterns Identified

**BP-260** — `e.isTrusted` guard blocks test `fireEvent` events: Adding `if (!e.isTrusted) return` to document-level keyboard listeners breaks all tests using `@testing-library/react`'s `fireEvent`, which creates synthetic events with `isTrusted: false`. Fix pattern: create a `fireTrustedKey(key, options)` helper that uses `Object.defineProperty(evt, 'isTrusted', {value: true})` before dispatching.

**BP-261** — HotkeyContext scope push/pop concurrent mode race: In React 18 concurrent mode, `useRef` mutable operations in `useCallback`s are not atomic. Scope counting that reads then writes `scopeCountsRef.current` can corrupt count if two effects schedule simultaneously. Pattern: use `useState + functional updater` for any ref-based counter that must be consistent.
