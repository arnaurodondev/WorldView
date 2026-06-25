# GLiNER CPU Bottleneck Investigation

**Date:** 2026-06-21
**Mode:** READ-ONLY diagnostics (no code edits, no restarts, no DB/container mutation)
**Container:** `worldview-gliner-server-1`
**Host:** macOS / Apple Silicon (`arm64`), Docker Desktop VM = 14 CPU / ~50 GB
**Symptom:** A single realistic ~600-word article × 11 entity classes never completes NER
(>300 s, timed out). Container had OOM-died (exit 137) for ~38 h. Tiny inputs return in
~0.2–3 s when healthy, but real articles hit the consumer's 240 s `/ner/batch` timeout,
so **every article fails at NER before reaching extraction**.

---

## TL;DR — Ranked Root Causes

| # | Root cause | Verdict | Evidence |
|---|-----------|---------|----------|
| **1** | **CPU quota too low (4 cores) + PyTorch thread OVERSUBSCRIPTION (14 OMP threads on a 4-core cgroup quota)** | **DEFINITELY THE CAUSE** | cgroup `cpu.max = 400000 100000` (=4.0 CPU) but `nproc`/`os.cpu_count()`=14 and `torch.get_num_threads()`=**14**. During active inference the container draws only **~12% CPU** (≈1.7 of 14 host cores) — classic OMP thread-thrashing / CFS-throttle stall, not real compute. |
| **2** | **4 GB memory cap is fully consumed by the model at idle → any batch OOM-kills (exit 137)** | **DEFINITELY THE CAUSE of the OOM deaths** | `docker stats` at near-idle: **3.992 GiB / 4 GiB = 99.79 %**. `gliner_large-v2.1` (DeBERTa-v3-large) RSS alone fills the cap; in-flight forward-pass tensors push it over. |
| **3** | Full large model (`urchade/gliner_large-v2.1`, DeBERTa-v3-large) on CPU | **CONTRIBUTING FACTOR** | Confirmed in compose, Dockerfile, server env. Large model is intrinsically the slowest GLiNER variant on CPU; combined with #1/#2 it has no headroom. |
| **4** | Inference cost scales with (text_len × num_labels) — pipeline sends all **11** labels per call | **CONTRIBUTING FACTOR (secondary)** | GLiNER prepends every label to every text; 11 labels inflates sequence length & compute. But NOT the primary driver — even a **1-label short text** is glacial right now, which only #1/#2 explain. |
| — | x86 image emulated under Rosetta/QEMU ("Unknown CPU vendor" warning) | **RULED OUT (NOT the cause)** | Container `uname -m`=**aarch64**, host=**arm64**, image arch=linux/arm64. Native. The `onnxruntime cpuid_info: Unknown CPU vendor` line is a benign onnxruntime arm64 cpuinfo quirk — **and onnxruntime is not even on the inference path** (see below). Red herring. |

### Key correction to prior assumptions
- The problem brief said `NanoCpus=0` (unlimited). **It is not** — `deploy.resources.limits.cpus: "4.0"`
  is set in `infra/compose/docker-compose.yml` (line ~1398) and inspect confirms
  `NanoCpus=4000000000`, `Memory=4294967296` (4 GB). Caps were applied by PLAN-0113 W1.
- The "Unknown CPU vendor" warning implicates **onnxruntime**, but GLiNER here runs on
  **PyTorch** (`torch==2.3.1`). `grep -rl onnxruntime` over the installed `gliner` package
  returned nothing — ort is only a transitive `transformers` dependency and never executes.
  So that warning is unrelated to the slow inference.

---

## Evidence Detail

### 1. Architecture — NOT emulated (suspect #1 eliminated)
```
host    uname -m         : arm64
container uname -m       : aarch64
docker inspect .Platform : linux            (image arch linux/arm64)
```
Native arm64 throughout. Emulation is excluded.

### 2. CPU quota + thread oversubscription  (PRIMARY)
```
docker inspect: NanoCpus=4000000000  (=4.0 CPU)   Memory=4294967296 (4 GB)
compose:        deploy.resources.limits.cpus "4.0", memory 4G   (line ~1395-1399)
cgroup inside:  /sys/fs/cgroup/cpu.max = "400000 100000"   → 4.0 CPU quota
container nproc / os.cpu_count()       = 14   ← reads VM, NOT the cgroup quota
torch.get_num_threads()                = 14
torch.get_num_interop_threads()        = 14
torch.cuda.is_available()              = False
torch.backends.mps.is_available()      = False   (MPS never reaches a Linux container)
```
PyTorch sizes its intra-op OpenMP pool from `os.cpu_count()`=14, **ignoring the 4-core
cgroup quota**. Result: 14 compute threads (plus 14 interop) are scheduled onto a 4-CPU
CFS quota. Under throttling, threads are repeatedly descheduled mid-kernel → cache
thrashing, lock contention, and CFS stalls. The observed effect is decisive:

```
docker stats during active /ner inference:  CPU = 12.1 % … 21.9 %  (≈1.7–3 of 14 cores)
```
A CPU-bound transformer that "should" peg its 4 allotted cores is instead idling at
~1–3 cores of *useful* work — the signature of OMP oversubscription on a throttled cgroup.

### 3. Memory — fully saturated (cause of the exit-137 OOM)
```
docker stats (near idle):  MEM = 3.992 GiB / 4 GiB  = 99.79 %
                           (also seen 3.58 GiB mid-inference)
```
The model resident set alone sits at the 4 GB ceiling. The compose comment claims
"Observed RSS ≈ 2.6 G … cap at 4 G with headroom" — that headroom does **not** exist in
practice on this host; the container lives at 99 %+ and any forward-pass allocation
(activations for an 11-label × N-text padded batch) tips it past the limit → kernel
OOM-kill → exit 137. The 38 h of downtime is explained.

### 4. Inference cost drivers (secondary)
- Per-article structure (`services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py`):
  text is split into sections, each truncated to `gliner_section_token_limit=450` tokens,
  sections batched `gliner_batch_size=32` per forward pass, **all 11 `NER_CLASS_LABELS`**
  passed every call. A 600-word article ≈ 1–2 sections → 1–2 forward passes.
- The server's micro-batcher (`infra/gliner/server.py`) coalesces up to `GLINER_MAX_BATCH=16`
  same-(labels,threshold) texts into one `batch_predict_entities` pass. Under the 3×16
  consumer fleet this means ONE ~16-text padded forward pass runs at a time, serialized.
- Label count matters (GLiNER concatenates each label to the prompt, so 11 labels ≈ 11×
  the entity-side sequence work), but it is a multiplier on top of #1/#2, not the root —
  confirmed by the fact that even a **1-label short-text** call is currently non-responsive.

### Adapter / timeout chain
- `libs/ml-clients/src/ml_clients/adapters/gliner_http.py`: `/ner/batch`, default
  `timeout_seconds=240`. Comment already documents "~79s per 16-text batch … pinned at
  ~1 core of a 14-core host … does not parallelise across cores" — i.e. the team already
  observed the symptom of #1 but mitigated by *raising the timeout* rather than fixing the
  thread/CPU config.
- `services/nlp-pipeline/config.py`: `gliner_request_timeout_s=240`,
  `extraction_timeout_s=300`, `message_processing_timeout_s=900`. The 240 s client timeout
  is what trips when a real article's pass exceeds it.

---

## Prioritised Optimizations (quick wins first)

### P0 — Fix thread oversubscription  (biggest win, config-only, zero risk)
Pin PyTorch/OpenMP threads to the CPU quota so threads match cores. Add to the
`gliner-server` service env in `infra/compose/docker-compose.yml` (~line 1372):
```yaml
      OMP_NUM_THREADS: "4"
      MKL_NUM_THREADS: "4"
      TORCH_NUM_THREADS: "4"        # belt-and-suspenders; server can also call torch.set_num_threads(4)
      OPENBLAS_NUM_THREADS: "4"
```
And/or in `infra/gliner/server.py` at startup (before model load):
```python
import os, torch
n = int(os.environ.get("OMP_NUM_THREADS", "4"))
torch.set_num_threads(n)
torch.set_num_interop_threads(1)
```
**Expected impact:** removes CFS-throttle thrashing; CPU utilization should jump from ~12 %
toward the full 4-core quota. Historically 4 well-pinned threads beat 14 oversubscribed
ones by 2–10× on throttled cgroups. This alone likely brings the real-article pass back
under the 240 s timeout.

### P0 — Raise the memory cap (stops the OOM deaths)
In the same `deploy.resources.limits` block, raise `memory: 4G` → **`6G` or `8G`**
(VM has ~50 GB). The model needs ~2.6–4 GB resident plus batch activations; 4 G has no
headroom. **Expected impact:** eliminates exit-137 OOM-kills entirely.

### P1 — Give it more cores (if host has them to spare)
Raise `cpus: "4.0"` → **`6.0`–`8.0`** (VM=14). Pair with a matching `OMP_NUM_THREADS`.
**Expected impact:** near-linear speedup of the CPU-bound forward pass.

### P1 — Reduce label count per call (cheap latency cut)
GLiNER cost scales with label count. Of the 11 `NER_CLASS_LABELS`, several are rare
(`government_body`, `regulatory_body`, `macroeconomic_indicator`, `index`, `currency`).
Options: (a) split into two passes (high-value labels first), or (b) drop the lowest-yield
labels. **Expected impact:** roughly proportional to the label reduction (e.g. 11→6 ≈ ~40 %
less entity-side compute). Change site: `NER_CLASS_LABELS` in
`services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py`.

### P2 — Smaller / quantized model
Switch `GLINER_MODEL_PATH` to `urchade/gliner_medium-v2.1` (or `small`), or load an
ONNX-INT8 quantized GLiNER via `GLiNER.from_pretrained(..., load_onnx_model=True)`.
**Expected impact:** medium ≈ 2–3× faster than large on CPU with modest recall loss; INT8
ONNX adds a further ~2–4× and cuts memory. Requires a recall A/B before adopting.
Change sites: compose env `GLINER_MODEL_PATH` + `requirements.txt` (add `onnxruntime`,
`optimum`) + `infra/gliner/Dockerfile`.

### P2 — Drop server micro-batch knee under tight CPU
With only 4 cores, the "batch=16 is 13.7× faster" knee (measured on a fatter host) may not
hold. Consider lowering `GLINER_MAX_BATCH` (e.g. 8) so a single pass fits memory and
finishes under timeout, trading peak throughput for tail-latency reliability. Compose env
`GLINER_MAX_BATCH`. Re-measure after P0.

### P3 — GPU / CoreML (out of reach in this setup)
No CUDA in the Linux container; macOS **MPS/CoreML is not accessible from a Docker Linux
guest**. A real GPU path requires either (a) deploying GLiNER off-host on an NVIDIA box
(compose already has a commented GPU-passthrough block), or (b) running GLiNER natively on
the Mac host (outside Docker) to use MPS. Not a quick win here.

---

## Recommended order of action
1. **P0 thread pinning** (`OMP_NUM_THREADS=4` + `torch.set_num_threads(4)`) — try first, config-only.
2. **P0 memory cap → 6–8 G** — stop OOM deaths.
3. Re-measure the 600-word × 11-label case. If still over budget:
4. **P1 cores → 6–8** and/or **P1 label reduction**.
5. Only then consider **P2 medium/quantized model**.

The combination of (1)+(2) is expected to resolve the immediate "every article times out /
container OOM-dies" failure with no model-quality change and no code-behavior risk.
