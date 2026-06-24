# KG Filter Bug — Intelligence Tab (READ-ONLY investigation)

Date: 2026-06-23
Scope: `apps/worldview-web` Intelligence tab knowledge-graph filters.
Status: root-cause + fix recommendation. NO code changes made.

## Summary

The Intelligence tab has **two independent filter systems** stacked in the same
centre column, and they confuse each other:

1. **Entity-type filter** (`GraphToolbar` popover → `GraphColumn.typeFilters` →
   `filteredGraph` → `EntityGraph data=`). This one **works correctly** — it
   removes nodes (and their incident edges) from the data passed to the canvas.
   Verified empirically (see "Evidence").

2. **Relation-type filter pills** (`GraphControls` "all/executive/investor/
   supplier/customer/competitor" → `EntityGraph` internal `activeRelFilter` →
   `FilterController.edgeReducer`). This one **only hides EDGES** in sigma's
   reducer. It **never hides NODES.** When a relation pill is selected the
   non-matching nodes stay fully painted on the canvas as disconnected dots, so
   the analyst perceives "toggling a filter does not hide/show nodes."

The reported symptom ("toggling a filter does not hide/show the corresponding
nodes") is explained by system #2. System #1 is healthy.

## Root cause (file:line + evidence)

### Primary: relation-pill filter hides edges but leaves orphan nodes (hypothesis e + design gap)

`components/instrument/graph/SigmaInternalComponents.tsx` — `FilterController`:

- `edgeReducer` (lines 288-309) returns `{ ...data, hidden: true }` for edges
  that fail the strength threshold or the active relation filter
  (`matchesRelFilter`). This correctly hides EDGES.
- `nodeReducer` (lines 310-336) has **no relation-filter branch at all.** It only
  (a) highlights the selected node, and (b) dims search-miss nodes. There is no
  code that hides a node whose every edge has been filtered out.

Result: selecting "investor" hides every non-ownership edge but leaves all the
person/supplier/etc. nodes painted in place. The graph frame looks essentially
unchanged (same dots), which reads as "the filter does nothing to the nodes."

The "X of Y edges" badge added in PLAN-0099 W4 (`GraphControls.tsx` lines
146-153) was a partial mitigation: it tells the analyst edges WERE hidden, but
the nodes themselves never move, so the perceived bug remains.

### Why this is confusing: two filters, one column

`EntityGraph` (rendered by `GraphColumn` at `GraphColumn.tsx:320`) ALWAYS renders
its own `GraphControls` relation pills (`EntityGraph.tsx:195-210`) on top of the
already-type-filtered data. So the toolbar at the top of the column
(entity-TYPE, works) and the pills just below the toolbar (relation-TYPE,
edges-only) look like one filter bar to the analyst. Toggling the relation pills
— the more prominent, always-visible control — produces the "nodes don't change"
behaviour.

## Evidence

- Entity-type path is correct end-to-end. `GraphColumn.tsx:186-193` computes
  `filteredGraph` (drops non-whitelisted, non-centre nodes + their dangling
  edges); `GraphLoader` rebuilds the graphology graph on every `data` change
  (`SigmaInternalComponents.tsx:208` — `data` is in the effect deps). A focused
  reproduction (mocking `EntityGraph` to print the `data.nodes` it receives)
  confirmed that toggling "person" changes the passed node set from
  `ent-001,p1,o1` to `ent-001,p1` — i.e. the org node is correctly removed.
- Relation-pill path: `matchesRelFilter` (`graphFilterUtils.ts`) is correct and
  unit-tested (17 tests pass); the `edgeReducer` correctly hides edges. There is
  simply no corresponding node-hiding logic in `nodeReducer`.
- Existing tests do NOT cover the sigma render layer: `GraphColumn.test.tsx`
  stubs `EntityGraph` entirely; `GraphControls.test.tsx` only checks the
  presentational pills + the "X of Y edges" badge. Nothing asserts that nodes
  hide/show on filter change — which is why this shipped.

## Recommended fix (P0) — hand to /fix-bug

Make the relation-pill filter hide **orphaned nodes** (nodes left with zero
visible edges after the edge filter), and refit the camera so the change is
visible.

Target: `components/instrument/graph/SigmaInternalComponents.tsx`,
`FilterController` (the effect at lines 281-339).

1. Before building the reducers, compute the set of node ids that retain at least
   one VISIBLE edge under the current `activeRelFilter` + `minWeight`
   (reuse the exact predicate already in the visible-edge-count effect, lines
   263-279 — extract it to a shared helper so canvas + count can never diverge).
   The centre node (`centerEntityId`) and any `selectedNodeId` must always be
   kept visible regardless of edges.

2. In `nodeReducer` (line 310), add a branch BEFORE the search-dim branch:
   ```
   if (activeRelFilter !== "all" && !keptNodeIds.has(node) && node !== selectedNodeId)
     return { ...data, hidden: true };
   ```
   This hides nodes that have no surviving edge under the active relation filter.

3. Add `centerEntityId` to `FilterController`'s props (it currently does not
   receive it) so the centre node is never hidden.

4. Add `centerEntityId` and `keptNodeIds` to the reducer effect deps; keep the
   single-`setSettings` rule intact (do not add a second controller — the
   existing docstring at lines 281-286 explains why two `setSettings` callers
   clobber each other).

Note: sigma errors on edges with a hidden endpoint only if the EDGE is still
visible. Since step 1 only hides a node when ALL its edges are already hidden by
the edge filter, there are no dangling visible edges — this is safe.

### Secondary (UX clarity, optional)

Consider unifying the two filter bars. The entity-type popover lives in
`GraphToolbar` (top of `GraphColumn`) while the relation pills live inside
`EntityGraph` directly below it; they read as one control. Either move the
relation pills up into the toolbar or visually separate them with a label.

### Regression test to add

A test that mounts `EntityGraph` with a small graph and a non-`all`
`activeRelFilter`, then asserts (via a sigma-graph spy or the reducer output)
that nodes with no surviving edge get `hidden:true`. The current suite stubs the
canvas, so the render layer is unverified — that gap is why this shipped.

## Investigation artifact to delete

During investigation a temporary reproduction test was created at
`apps/worldview-web/components/instrument/intelligence/graph/__tests__/__kgfilter_repro.test.tsx`.
It is NOT part of any fix and should be deleted (the `rm` was blocked by the
sandbox during the read-only session).
