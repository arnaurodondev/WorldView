# Screenshot capture guide — EMNLP demo appendix composite

UI is live at **http://localhost:3001** (your `next dev`). Log in with the **Dev Login** button
(no credentials needed). Capture at a consistent width (~1280px, light OR dark — pick one and keep
it) and crop tightly to the relevant panel. Save PNGs into `docs/emnlp-2026-demo/figs/` with the
exact filenames below; I'll compose + place them in the appendix (and one in the body).

The reviewer asked for a compact 3-crop composite. Capture these three (a 4th prediction shot is
optional but on-message given the prediction integration):

## 1. `figs/shot-enrichment.png` — incoming document + enrichment
An entity's news/intelligence feed showing a recent document with its enrichment status
(entities/relations extracted). Good source: an entity page for **TSMC** or **NVIDIA** → the
news/recent-coverage panel. Shows text → structured enrichment.

## 2. `figs/shot-graph-evidence.png` — graph edge with its evidence passage
Open the **knowledge-graph / entity graph** for **NVIDIA** or **TSMC**, click an edge (e.g. a
supplier/supply-chain relation), and capture the panel that shows the edge **plus the exact
supporting source passage** (the provenance back-link). This is the paper's core "graph edge →
source passage" claim, made visual.

## 3. `figs/shot-chat-trace.png` — answer with tool trace + mixed evidence  *(most important)*
Open **chat** and ask the exact question from the real trace in §3:

> Trace how recent TSMC news could ripple through the supply chain to affect Apple and NVIDIA.

Capture the answer **with the inspectable tool-trace / evidence panel expanded** — showing the
tool calls (`get_entity_news`, `traverse_graph`) and the numbered `[1][2]` citations. This ties the
screenshot directly to the verified PASS@97 trace we cite.

## 4. (optional) `figs/shot-prediction.png` — prediction market
A prediction-market view: a market's proposition + probability history, ideally showing the linked
entities / `PREDICTION` event. Reinforces that prediction markets are a first-class modality. Use a
market you know is populated (politics/crypto — e.g. a Trump 2028 or Bitcoin market).

---
When done, tell me the files are in `figs/` and I'll build the composite figure and reference it
from the body (§3 or §2.5) + appendix.
