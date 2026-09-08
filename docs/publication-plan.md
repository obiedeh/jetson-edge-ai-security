# Publication Plan: What a Research-Level Write-Up Still Needs

Updated 2026-09-08. This records what evidence exists, what it does and does
not support, and the ordered work needed before a technical write-up
(newsletter post first, preprint second) can make defensible claims about an
edge physical-AI security system. Every item names the artifact that must be
committed before the claim is written.

## What exists today

| Evidence | Artifact | What it supports | What it does not support |
| --- | --- | --- | --- |
| Detector and forecaster training record | `reports/training_run.json` | Pipeline correctness: GBM AUC 0.9796 vs IsolationForest 0.6433, Ridge MAE 7.49 vs lag-1 10.24, on the **synthetic** 5k fixture with 5-fold CV; CPU latency on the RTX 5090 dev box | Any detection-performance claim. The fixture has class-conditional synthetic signatures, so separability is by construction |
| ONNX exports | `models/exports/*.onnx` | Deployability of the two models, opset 17, hashed in the Thor artifact | Accuracy parity between pickle and ONNX (not measured) |
| Deterministic demo replay | `reports/demo/*` | The runtime emits alerts, windows and metrics from a fixed input; regenerated in CI | Anything about real traffic |
| Thor benchmark | `reports/thor_benchmark.json`, `_tegrastats.jsonl`, `_run.log` | Measured inference latency, throughput, process RSS, board rails and temperatures on Jetson AGX Thor at 10/100/1000 events/s, CPU execution provider | Capture, flow extraction, end-to-end pipeline latency, GPU execution (the PyPI `onnxruntime-gpu` wheel has no kernels for Thor's GPU; the failure is recorded in the artifact) |
| Runtime alert database | `data/alerts.db` (ignored) | Nothing citable. 20,501 alerts from replaying the synthetic fixture through the dashboard between 2026-05-22 and 2026-05-30, all forecasts from the mock forecaster | Do not cite |

## Observations from run 3cac5ed2b7bd (2026-09-08)

- Detector at 1000 events/s: p50 0.0213 ms, p95 0.0237 ms, p99 0.028 ms, max 14.7371 ms, 43118 of 300001 pacing deadlines missed by more than one interval.
- Forecaster at 1000 events/s: p50 0.0138 ms, p95 0.0141 ms, no pacing misses.
- Board power: idle 24170 mW; forecaster tiers about 24424 mW; detector tiers at 100 and 1000 events/s about 54298 mW with junction temperature peaking at 59.562 C. Hypothesis: onnxruntime's default intra-op thread pool spins between runs for the tree-ensemble graph. **Unverified.** The next measurement is the same run with `intra_op_num_threads=1` and spinning disabled, committed as a sibling artifact; until then the write-up reports the power numbers as observed and the cause as open.
- Forecaster at 10 events/s showed p50 0.2218 ms versus 0.0138 ms at 1000 events/s, consistent with CPU frequency scaling at low duty cycle. Also unverified; report as observed.
- Process peak RSS 0.3639 GB. 1914 tegrastats samples retained.

## Claims that are defensible now

1. The runtime is source-agnostic and deterministic: fixed input produces
   fixed alerts and metrics, validated in CI.
2. On Jetson AGX Thor the two shipped models run at sub-millisecond per-event
   latency on CPU with under 0.5 GB process RSS, so inference is not the
   bottleneck for a 1000 events/s edge node. State the provider, the synthetic
   inputs, and that capture is unmeasured every time this is said.
3. A GPU execution provider is not currently available for this model
   format on JetPack 7 through PyPI or the NVIDIA Jetson index; for models
   this small it would not help. Recorded, not asserted.

## Work order before a write-up

Each step ends with a committed artifact. Implementation runs; review follows
the claim boundary before the number is quoted anywhere.

### 1. Real dataset evaluation (largest credibility gap)

- Fetch one allowlisted public dataset with `edge-security fetch-dataset`
  (WUSTL-IIoT-2021 is the smallest; Edge-IIoTset is the closest match to the
  fixture schema and needs manual download per `docs/datasets.md`).
- Record dataset SHA-256, row count, class distribution, and the exact split.
  Use a time-ordered or device-held-out split, not random rows, and say why.
- Train and evaluate with the existing `train detector` and
  `train forecaster` commands. Report AUC, F1, per-class precision/recall,
  false-positive rate at the alert threshold, and the IsolationForest
  baseline on the same split.
- Artifact: `reports/eval/<dataset>_<split>.json` plus the command and seed.
  Update `training_run.json` only if the shipped models are retrained.

### 2. End-to-end pipeline latency on Thor

- Extend `deploy/thor/run_benchmark.py` or add a sibling that replays the
  real dataset CSV through `CsvReplaySource` to alert emission on Thor and
  records per-event wall time from row read to alert write, with
  tegrastats sampling.
- Artifact: `reports/thor_pipeline_benchmark.json` with the same provenance
  block as the inference benchmark.

### 3. Capture path measurement (required before any "sniffer" claim)

- Implement one adapter first (Zeek `conn.log` is the smallest surface),
  then the PCAP replay stage using a public PCAP, on Thor.
- Record every field listed in `docs/jetson-sniffer-upgrade-plan.md`
  under "Measurement Requirements": interface, mode, packets observed and
  dropped, flows and rows generated, rows skipped, alerts, inference
  percentiles, memory, tegrastats note.
- Artifact: `reports/capture/<run>.json`. Until it exists the write-up says
  "capture is planned and unmeasured".

### 3b. Thread-pool power comparison (small, do before the newsletter)

- Re-run the inference benchmark with onnxruntime session options
  `intra_op_num_threads=1`, `inter_op_num_threads=1`, spinning disabled, at
  100 and 1000 events/s for 120 s each, and compare VIN and pacing misses with
  the default run.
- Artifact: `reports/thor_benchmark_threads.json` with the same provenance
  block. This turns the power observation above into a measured statement.

### 4. Sustained run

- 60 minutes at the 1000 events/s tier on Thor with tegrastats at 1 Hz, to
  show thermal and power steadiness. The current 300 s tiers are short runs.
- Artifact: `reports/thor_soak_<date>.json` and the tegrastats series.

### 5. Cross-device comparison (optional, strengthens the story)

- Same inference benchmark on the Orin NX host used in the robotics
  repository, and the RTX 5090 dev box on CPU, with the same script and
  duration. Report per-device tables side by side with power.
- Artifact: `reports/bench/<device>.json`.

### 6. Write-up assembly

- Every number in the draft links to a tracked artifact path. Run the
  citation check on the draft.
- Figures are generated by a committed script from the JSON artifacts, with
  source hashes recorded, following `scripts/plot_evidence.py` in the
  robotics repository.
- Newsletter post first (system story plus the measured Thor numbers and
  their limits). Preprint only after steps 1 through 4 exist, because a
  preprint needs the real-dataset evaluation and the capture measurement to
  say anything about intrusion detection rather than about a runtime.

## Cross-repository note

The robotics repository (`physical-ai-jetson-robotics`) already holds
measured Thor GR00T inference and Orin day-one probes with the same
provenance style. A combined "edge physical-AI system" write-up can cite
both, but each number stays attributed to its own repository and artifact.
Do not pool measurements taken with different scripts or on different dates
into one table without saying so.
