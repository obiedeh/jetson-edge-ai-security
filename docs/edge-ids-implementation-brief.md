# Edge IDS — Implementation Brief

> **Status:** v1.0 — implementation-ready
> **Owner:** Obinna (obiedeh)
> **Targets:** RTX 5090 (dev/training) → **NVIDIA Jetson AGX Thor (production, on hand)**
> **Date:** 2026-05-21
> **Supersedes:** the bullet list in `docs/production-roadmap.md` Near-Term + Advanced + Jetson Deployment. This brief is the active spec for the next four commits.

## Goal

Take this repo from defensive-telemetry-replay-runtime to a **deployable edge IDS product** that:

1. Ingests Edge-IIoTset-shaped flows (CSV today, PCAP replay simulating SPAN/mirror, real PCAP/Zeek/Suricata in v1.x).
2. Runs **two complementary inference stages** — a reactive per-flow Detector and a proactive temporal Forecaster — through a model-agnostic interface.
3. Surfaces detections + a **60-minute lookback / 30-minute forecast** view on an operator web dashboard.
4. Deploys to **Jetson AGX Thor** with measured latency / throughput / power numbers in the repo's evidence pack.

## Three first-class attack categories (UI focus)

The Edge-IIoTset dataset has 14 attack families + Normal. The product surfaces all 15 in metadata, but the **operator dashboard and demo narrative are built around the three high-signal categories from the source materials**:

- **DDoS_ICMP** — ICMP flood (high volume, easy baseline signal)
- **Uploading** — exfiltration / staged uploads (medium volume, behavioral signal)
- **Ransomware** — ransomware-driven traffic (low volume, critical severity)

Other Edge-IIoTset categories (`DDoS_UDP`, `Vulnerability_Scanner`, `SQL_Injection`, `Password_Brute_Force`, `Port_Scanning`, `Backdoor`, `Injection_Attack`, `XSS`, plus four others) remain in the dataset loader, the model heads, and the alerts API, but are demoted in the UI to a "Other attacks" expandable panel.

## Model selection — **not locked in this brief**

The implementer picks the actual architectures (DNN / 1D-CNN / LSTM / TCN / GBDT / hybrid). The brief defines:

- The `Detector` and `Forecaster` Protocol contracts (§1.2)
- Required performance gates (§5)
- The ONNX export shape per stage (§1.4)
- Latency budget on Thor (§5)

Whatever satisfies the gates inside the latency budget ships. The existing `IsolationForest` + threshold baseline stays as a *fallback* available behind a config flag — useful for cold-start, model loss-of-confidence, and CI runs that can't pull a heavy model.

## Out of scope (do not build)

- Multi-site / fleet aggregation
- SIEM federation / cross-tenant correlation
- Federated learning (mentioned in the source paper as future work; explicit non-goal here)
- Offensive tooling of any kind — already an `AGENTS.md` rule, restated
- Cloud SIEM / Tableau / Power BI integration — we ship our own dashboard
- Auth / RBAC / multi-user — single operator at MVP, like urban-edge
- Audit log UI
- Live MQTT broker ingestion — keep the schema field but no adapter ships at MVP
- Federated retraining — local retrain script only
- GxP-specific compliance modules (Part 11 / OTA manager) — referenced in IoTT paper but biotech-specific; deferred

These items live in **§9 Future Scope** of this brief.

## Operating discipline

- New top-level dirs: `models/` (training + reference impls + ONNX export), `web/` (Vite+React SPA), `deploy/` (Thor container + systemd + scripts). No others.
- `AGENTS.md` rules continue to apply: Pydantic v2 schemas, mock adapter is the test default, no OpenCV/ONNX in core event/analytics/telemetry modules, no autonomous enforcement, no hardcoded `/data` paths.
- New Python deps limited to: `torch` or `tensorflow` (whichever the implementer picks for reference models — pick one, not both), `onnx`, `onnxruntime` (CPU), `pandas`, `scapy` or `dpkt` for PCAP, `sse-starlette` for web push, `aiosqlite` for the alerts store. **No notebook deps in default install path.**
- `ruff check .` and `pytest` green per commit. `pnpm build` green for the web commit.
- No commit trailers, no AI attribution.
- Four commits — see §4.

---

## 1. Backend additions

### 1.1 Data + temporal binning

Add `src/jetson_edge_ai_security/datasets/edge_iiotset.py`:

- Loader that accepts the official Edge-IIoTset CSV (DNN-EdgeIIoT partition recommended — 500K-row subset is fine for portfolio; full 2.1M-row for stress test).
- Column normalization → `TelemetryEvent` schema.
- Two-target retention: `attack_label` (binary), `attack_type` (15-class).
- Time-aware 80/20 split helper (no random shuffling across time).

Add `src/jetson_edge_ai_security/features/temporal_binning.py`:

- **5-second bins** by default (configurable). Numeric features averaged across the bin; `event_count` appended; binary attack label = bin max; modal attack type assigned for attack-positive bins.
- **20-bin sequences** by default → 100s history. Slide-by-1 by default. Configurable.
- Output tensor shape: `(seq_len=20, feature_dim=57)`. The 57-feature shape matches the IoTT paper after preprocessing.

The binning module is pure functions over a `pandas.DataFrame` or an iterable of `TelemetryEvent`. No model imports.

### 1.2 Model interfaces

New module `src/jetson_edge_ai_security/models/interfaces.py`:

```python
from typing import Protocol
from pydantic import BaseModel
import numpy as np

class DetectorMetadata(BaseModel):
    name: str
    version: str
    architecture: str          # informational only — "1D-CNN", "DNN", "LSTM", "LightGBM", ...
    feature_dim: int
    input_shape: tuple[int, ...]
    output_classes: list[str]  # 15 entries — Normal + 14 attack types
    onnx_path: str | None = None

class Detector(Protocol):
    metadata: DetectorMetadata
    def predict(self, features: np.ndarray) -> "DetectionResult": ...

class ForecasterMetadata(BaseModel):
    name: str
    version: str
    architecture: str
    lookback_bins: int
    forecast_bins: int
    bin_seconds: int
    onnx_path: str | None = None

class Forecaster(Protocol):
    metadata: ForecasterMetadata
    def forecast(self, history: np.ndarray) -> "ForecastResult": ...
```

`DetectionResult` and `ForecastResult` are Pydantic models (defined in the file) with:
- `probability` (0..1, binary attack confidence)
- `attack_type` (one of 15 classes)
- `per_class_probabilities` (dict[str, float])
- `forecast_horizon_bins` (int, on `ForecastResult` only)
- `predicted_attack_intensity` (np.ndarray of len `forecast_bins`, on `ForecastResult`)
- `predicted_attack_type_per_bin` (list[str] of len `forecast_bins`)
- `latency_ms` (measured per-prediction)
- `model_metadata` (back-pointer)

### 1.3 Reference implementations — implementer picks

The brief requires **at least one Detector** and **at least one Forecaster** that beat the existing baseline by the gates in §5. Suggested-but-not-mandatory starting points:

- **Detector:** any of {1D-CNN, small DNN, small LSTM, LightGBM}. Pick whichever satisfies the latency budget first; document the choice + measured numbers.
- **Forecaster:** any of {small LSTM, TCN, small Transformer}. Same rule.

A `MockDetector` and `MockForecaster` (deterministic, no GPU, no training) stay in tree for CI and for environments without the model deps installed. These are existing-test-compatible.

### 1.4 ONNX export contract

Every shipped Detector and Forecaster must export to ONNX with:
- **Detector**: input `(batch, feature_dim)` or `(batch, seq_len, feature_dim)` depending on architecture; output `{probability: (batch,), logits: (batch, num_classes)}`. Opset ≥ 17.
- **Forecaster**: input `(batch, lookback_bins, feature_dim)`; output `{intensity: (batch, forecast_bins), type_logits: (batch, forecast_bins, num_classes)}`. Opset ≥ 17.

Export script: `models/export_onnx.py`. Validates ONNX model with `onnxruntime` against the trained model on a fixed test fixture before writing the file.

### 1.5 Pipeline integration

Extend `src/jetson_edge_ai_security/runtime/pipeline.py`:

- New `lookback_window: int = 60 * 60 // 5` (60 minutes of 5s bins = 720)
- New `forecast_horizon: int = 30 * 60 // 5` (30 minutes of 5s bins = 360)
- Replaces the existing Naive Lag-1 forecaster output with the LSTM/TCN forecaster's `predicted_attack_intensity` + `predicted_attack_type_per_bin`.
- Emits **two report objects per pipeline tick**:
  - `LookbackReport` — past 60 min, observed attack counts per type, peak intensity, durations.
  - `ForecastReport` — next 30 min, predicted attack intensity per type, predicted peak time/intensity, confidence.
- Both are added to the existing `reports/demo/` evidence pack at run time.

### 1.6 PCAP replay source (simulating SPAN mirror)

New module `src/jetson_edge_ai_security/datasets/pcap_replay.py`:

- Reads a PCAP using `scapy` or `dpkt` (implementer's call — prefer `dpkt` for speed if installed).
- Flow-aggregates packets (5-tuple) using a sliding 1-second window into Edge-IIoTset-shaped feature rows.
- Emits `TelemetryEvent` instances at wall-clock or accelerated rate (CLI flag).
- Treats a PCAP as a stand-in for live SPAN/mirror traffic — same downstream pipeline.

Live SPAN capture (`libpcap` against an actual network interface) is **deferred to v1.x** behind a `live-mirror` source. Architecture is the same; the only difference is the source loader.

### 1.7 Alerts store

New SQLite-backed store under `src/jetson_edge_ai_security/alerts/store.py` (extends current `alert_builder.py`). Tables:

- `alerts(id, timestamp, attack_type, severity, confidence, source, model_run_id, payload_json)`
- `model_runs(id, started_at, ended_at, dataset_hash, training_run_hash, detector_name, detector_version, forecaster_name, forecaster_version, auc, f1, fpr, mae)`
- `forecast_snapshots(id, generated_at, model_run_id, lookback_window_seconds, forecast_horizon_seconds, payload_json)`

The store backs the web dashboard's Live Alerts, Lookback, Forecast, and Model Health views. Append-only. Local file, no migrations framework — one `schema.sql`.

---

## 2. Web dashboard — `web/`

Vite + React + TypeScript + Tailwind + shadcn/ui. Same pattern as the urban-edge wrapper.

### 2.1 Screens (five — no more)

| Screen | What it does | Acceptance |
|---|---|---|
| **S1 Live Alerts** | Live event stream (SSE) with filterable list by attack type, severity, confidence | New alerts ≤ 1s after API emit. Filter chips for DDoS_ICMP / Uploading / Ransomware / Other. |
| **S2 Lookback & Forecast** | The 60-min lookback + 30-min forecast time-series + the "Peak Impact Comparison" gauges from the infographic | Renders the dashboard timeline from the infographic against real or mock data. Time-range picker. |
| **S3 Model Health** | Per-model AUC, F1, per-class FPR, drift KPI (moving-average AUC) with a `retrain_recommended` flag when below threshold | Three tiles per model: AUC sparkline, F1 score, FPR by class. Retrain flag triggers when AUC < `retrain_auc_floor` (default 0.90, configurable). |
| **S4 Evidence Artifacts** | Read-only browser over `reports/`, `artifacts/`, `models/exports/` | Lists each artifact (kind, size, last-updated). Renders JSON inline. ONNX model file shows metadata + size. |
| **S5 Settings** | Input source switcher (csv / pcap / live-mirror), model selector (mock / reference / available ONNX runs), threshold + window editors, Thor benchmark trigger | Source switch writes to config + reloads the runtime. Thor benchmark button runs the benchmark script on Thor and persists results. |

No login screen, no audit log UI, no separate cameras page, no PDF export.

### 2.2 Data-source / credibility badges

Every Live Alert, Forecast snapshot, and Model Health tile carries one of:

- `replay-csv` — replayed from CSV
- `replay-pcap` — replayed from PCAP (simulating SPAN mirror)
- `live-mirror` — live SPAN/mirror port capture against an actual interface
- `validated-thor-benchmark` — derived from a benchmark run on Thor with its run hash + timestamp

`mock` is **internal-test-only** — never shown in the production UI. Mock sources render the same UI but with a persistent banner: *"Mock source — does not reflect real or replayed network traffic. Use only for UI development."*

Per-model latency on the Model Health page carries a separate badge:

- `measured-cpu` (RTX 5090 dev box, CPU-only)
- `measured-cuda` (RTX 5090 GPU, ONNX Runtime CUDA)
- `validated-thor` (TensorRT engine, run on Thor)

CPU and CUDA latencies come from `models/export_onnx.py --bench`. Thor latencies come from Commit 4's benchmark.

### 2.3 File layout

```
web/
  app/
    routes.tsx
    pages/
      alerts.tsx          # S1
      lookback.tsx        # S2
      model-health.tsx    # S3
      artifacts.tsx       # S4
      settings.tsx        # S5
  components/
    ui/                   # shadcn primitives
    attack-type-chip.tsx
    severity-badge.tsx
    data-source-badge.tsx
    latency-badge.tsx
    lookback-forecast-chart.tsx
    peak-impact-gauges.tsx
    model-health-tile.tsx
  lib/
    api.ts                # fetch client
    sse.ts                # event stream
    utils.ts              # shadcn cn() helper
  package.json
  tsconfig.json
  vite.config.ts
  tailwind.config.ts
  postcss.config.js
  components.json
  .env.local.example
  .gitignore
```

---

## 3. API contract additions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/alerts` | Cursor-paginated alerts. Filters: `attack_type`, `severity`, `since`, `source`. |
| `GET` | `/alerts/sse` | SSE stream of new alerts. |
| `GET` | `/lookback` | Past `N` minutes (default 60) of bucketed attack counts + intensity per type. |
| `GET` | `/forecast` | Most recent `ForecastReport` from the pipeline. |
| `GET` | `/models` | List available `Detector` and `Forecaster` implementations + their metadata + AUC / F1 / FPR / MAE measurements. |
| `POST` | `/models/active` | Set the active `Detector` and `Forecaster` for the runtime. |
| `GET` | `/model-health` | Drift KPI: moving-average AUC, FPR per class, `retrain_recommended` boolean per model. |
| `GET` | `/artifacts` | List files under `reports/`, `artifacts/`, `models/exports/`. |
| `GET` | `/artifacts/{path}` | Stream a single artifact. |
| `POST` | `/benchmark/thor` | Trigger a Thor benchmark run (only valid when running on Thor; 409 otherwise). |
| `GET` | `/benchmark/runs` | List benchmark runs with run-hash, hardware tag, p50/p95/p99 latency, throughput, power. |

All endpoints carry the data-source badge in their response payload.

---

## 4. Implementation order — four commits

### COMMIT 1 — Data, interfaces, mock impls, ONNX hook, training CLI

**New files:**
- `src/jetson_edge_ai_security/datasets/edge_iiotset.py`
- `src/jetson_edge_ai_security/features/temporal_binning.py`
- `src/jetson_edge_ai_security/models/__init__.py`
- `src/jetson_edge_ai_security/models/interfaces.py`
- `src/jetson_edge_ai_security/models/mock_detector.py`
- `src/jetson_edge_ai_security/models/mock_forecaster.py`
- `src/jetson_edge_ai_security/models/export_onnx.py`
- `src/jetson_edge_ai_security/models/train.py` — Typer subcommand wiring; no architecture yet
- `tests/test_edge_iiotset_loader.py`
- `tests/test_temporal_binning.py`
- `tests/test_models_interfaces.py`
- `tests/test_mock_models.py`
- `tests/test_onnx_export_mock.py`
- `tests/fixtures/edge_iiotset_sample_5k.csv` (5k-row subset committed for tests)

**Modified:**
- `src/jetson_edge_ai_security/cli.py` — add `edge-security train detector|forecaster`, `edge-security export onnx`, `edge-security bench cpu|cuda`
- `pyproject.toml` — add `onnx`, `onnxruntime`, `pandas`. Make `torch` / `tensorflow` extras under `[ml]` so default install stays light.
- `docs/datasets.md` — add Edge-IIoTset section with manual-download instructions (no auto-fetch unless a stable allowlisted URL is found)

**Acceptance:**
- `MockDetector` + `MockForecaster` round-trip through ONNX export and inference
- 5-second binning + 20-bin sequencing produces deterministic shape `(20, 57)` on the fixture
- `ruff` + `pytest` green

### COMMIT 2 — Reference models + measured baselines

**New files:**
- `models/detectors/<chosen_arch>.py` — at least one reference Detector (implementer picks architecture per §1.3)
- `models/forecasters/<chosen_arch>.py` — at least one reference Forecaster
- `models/training/train_detector.py` — training script with deterministic seed
- `models/training/train_forecaster.py`
- `models/eval/eval_detector.py` — AUC, F1, per-class FPR
- `models/eval/eval_forecaster.py` — MAE, RMSE, per-type forecast accuracy
- `tests/test_reference_detector.py` — verifies trained model beats `IsolationForest` baseline by ≥ 0.05 AUC on the 5k fixture
- `tests/test_reference_forecaster.py` — verifies trained forecaster beats Naive Lag-1 by ≥ 20% MAE reduction
- `reports/training_run.json` — committed: hash, dataset hash, AUC, F1, FPR, MAE, latency (CPU + CUDA), per-class breakdown

**Modified:**
- `src/jetson_edge_ai_security/cli.py` — wire `edge-security models list|set-active`
- `src/jetson_edge_ai_security/runtime/pipeline.py` — replace Naive Lag-1 with the active Forecaster

**Acceptance:**
- Reference Detector AUC > IsolationForest AUC by ≥ 0.05 on the 5k fixture (numbers go in `reports/training_run.json` — whatever they actually are)
- Reference Forecaster MAE < Naive Lag-1 MAE by ≥ 20% on the 5k fixture
- Both models export to ONNX and round-trip via `onnxruntime` (CPU) with output equality within fp32 tolerance
- `ruff` + `pytest` green

### COMMIT 3 — Pipeline integration + web dashboard

**New files:**
- `src/jetson_edge_ai_security/datasets/pcap_replay.py`
- `src/jetson_edge_ai_security/alerts/store.py` + `schema.sql`
- `src/jetson_edge_ai_security/api/main.py` (if not already a FastAPI app), routes per §3
- `src/jetson_edge_ai_security/api/sse.py`
- All of `web/` per §2.3
- `tests/test_pcap_replay.py`
- `tests/test_alerts_store.py`
- `tests/test_api_lookback_forecast.py`
- `tests/test_api_model_health.py`

**Modified:**
- `pyproject.toml` — add `dpkt`, `fastapi`, `sse-starlette`, `aiosqlite`
- `Makefile` — add `make web-install`, `make web-dev`, `make web-build`
- `.github/workflows/ci.yml` — add `pnpm build` step for web/

**Acceptance:**
- `pnpm dev` boots web on `:3000`; backend on `:8080`
- `/lookback?minutes=60` and `/forecast` return real data when piping CSV replay or PCAP replay through the pipeline
- S1 alerts list updates via SSE within 1s of new emit
- S2 lookback chart renders the 60-min historical and the 30-min forecast in one continuous time-series
- S3 Model Health shows AUC sparkline + FPR per class + retrain flag when AUC drifts
- S4 Artifacts shows `reports/training_run.json` and any committed ONNX files
- All UI surfaces carry the right data-source badge
- `ruff`, `pytest`, `pnpm build` green

### COMMIT 4 — Thor deployment + measured validation

**Prerequisite:** Commits 1–3 merged to main. Thor on hand.

**New files:**
- `deploy/thor/Dockerfile` — aarch64 base, TensorRT runtime, copies `models/exports/*.onnx` + the FastAPI app + `web/dist/`
- `deploy/thor/build_tensorrt_engines.py` — `onnx → trt` for each shipped Detector / Forecaster
- `deploy/thor/run_benchmark.py` — measures p50/p95/p99 latency at synthetic load (10/100/1000 events/sec), sustained throughput, GPU memory, board power if `tegrastats` available, runs for 5 min per load tier
- `deploy/thor/edge-security.service` — systemd unit
- `deploy/thor/install.sh` — copy unit, reload daemon, enable + start service
- `deploy/thor/operator-runbook.md` — install / upgrade / rollback / collect-logs procedures
- `reports/thor_benchmark.json` — committed: Thor SKU, JetPack version, TensorRT version, run hash, per-model latency tiers, throughput, power
- `tests/test_thor_smoke.py` — runs only on aarch64 + with `JETSON_SOC` env var set; skipped otherwise

**Modified:**
- `web/components/latency-badge.tsx` — flip to `validated-thor` when reading from `thor_benchmark.json`
- `web/pages/model-health.tsx` — render Thor-measured numbers
- `README.md` — add a "Validated on Jetson AGX Thor" section with the measured numbers (whatever they are, not aspirational)
- `PORTFOLIO_DELIVERABLES.md` — flip the credibility-boundary section to acknowledge measured Thor numbers; keep the rest

**Acceptance:**
- TensorRT engines build on Thor from the shipped ONNX
- `edge-security.service` starts on Thor; survives a reboot
- `/benchmark/thor` produces a `thor_benchmark.json` with non-fabricated numbers; dashboard renders the `validated-thor` badge
- README's "Validated on Thor" section has the measured numbers — whatever the runs actually showed
- `ruff` + `pytest` green on x86 (Thor smoke test is auto-skipped); manual smoke run on Thor passes

---

## 5. Performance gates (the real product bar)

| Gate | Threshold | Why |
|---|---|---|
| Detector AUC on Edge-IIoTset 5k fixture | ≥ baseline + 0.05 | Beats the existing IsolationForest. Specific value reported, not promised. |
| Forecaster MAE reduction vs Naive Lag-1 | ≥ 20% | Beats persistence. Reasonable threshold; tighten as work matures. |
| Detector p95 latency on Thor (TensorRT) | ≤ 10 ms per flow | Matches the infographic claim. Measured, not aspirational. |
| Forecaster p95 latency on Thor (TensorRT) | ≤ 50 ms per (20, 57) sequence | Forecasting can be slower; still real-time. |
| End-to-end pipeline throughput on Thor | ≥ 1000 events/sec sustained for 5 min | A practical IIoT load. Adjust based on what we actually measure. |
| Memory footprint on Thor (resident, both engines + service) | ≤ 4 GB | Leaves headroom on AGX Thor 64 GB. |
| Drift KPI: AUC must stay within 5% of training-run AUC for 24 h replay | yes | Otherwise retrain flag fires. |

If a gate fails on first run, the brief is **not invalidated** — the numbers go in the report honestly, and the implementer documents the deviation. The credibility-badge story keeps the UI honest.

---

## 6. Settings additions — `configs/default.yaml`

```yaml
binning:
  bin_seconds: 5
  sequence_bins: 20
  stride_bins: 1

pipeline:
  lookback_minutes: 60
  forecast_minutes: 30

models:
  detector_active: "reference"   # mock | reference | <onnx-run-id>
  forecaster_active: "reference"
  retrain_auc_floor: 0.90
  retrain_fpr_ceiling_per_class: 0.05

source:
  type: "replay_csv"   # replay_csv | replay_pcap | live_mirror
  path: "data/edge-iiotset.csv"
  replay_rate: 1.0     # wall-clock multiplier

api:
  host: "0.0.0.0"
  port: 8080
  sse_max_clients: 25

web:
  cors_allow_origin: "http://localhost:3000"
  credibility_banner_dismissible: true

deploy:
  thor:
    tensorrt_engine_dir: "deploy/thor/engines"
    benchmark_load_tiers_eps: [10, 100, 1000]
    benchmark_duration_seconds: 300
```

No environment variables introduced beyond what already exists.

---

## 7. CI

Existing CI (Ubuntu x86_64). Add:

1. Install `[dev]` extras (no `[ml]`).
2. `pnpm install --frozen-lockfile` in `web/` after Commit 3.
3. `pnpm build` in `web/`.
4. Verify `web/dist/index.html`.
5. Mock-model ONNX round-trip test (no GPU).

A second optional CI job (manual trigger) installs `[ml]` and runs `models/training/train_detector.py` against the 5k fixture, then asserts the gate from §5 on the 5k fixture. This is slow; gate it behind a label or schedule.

Thor smoke tests are auto-skipped in CI (no Thor in CI environment).

---

## 8. Repo file layout (proposed end state)

```
src/jetson_edge_ai_security/
  alerts/
    __init__.py
    alert_builder.py        # existing
    store.py                # new (Commit 3)
    schema.sql              # new (Commit 3)
  api/
    __init__.py             # new (Commit 3)
    main.py                 # new (Commit 3)
    sse.py                  # new (Commit 3)
  datasets/
    __init__.py
    catalog.py              # existing
    fetcher.py              # existing
    edge_iiotset.py         # new (Commit 1)
    pcap_replay.py          # new (Commit 3)
  detection/
    baseline.py             # existing — kept as fallback
    model_runner.py         # existing
  features/
    extractors.py           # existing
    windows.py              # existing
    temporal_binning.py     # new (Commit 1)
  forecasting/
    attack_count.py         # existing — Naive Lag-1 retained as fallback
  models/                   # NEW top-level (Commit 1)
    __init__.py
    interfaces.py
    mock_detector.py
    mock_forecaster.py
    detectors/
      <chosen>.py           # Commit 2
    forecasters/
      <chosen>.py           # Commit 2
    training/
      train_detector.py     # Commit 2
      train_forecaster.py   # Commit 2
    eval/
      eval_detector.py
      eval_forecaster.py
    export_onnx.py
    exports/                # gitignored — generated artifacts
  runtime/
    metrics.py              # existing
    pipeline.py             # existing — modified Commit 3
    reporting.py            # existing
  config.py                 # existing — extended

web/                        # new (Commit 3)
deploy/thor/                # new (Commit 4)

reports/                    # existing — extended with training_run.json and thor_benchmark.json
artifacts/                  # existing
configs/                    # existing — extended
tests/                      # existing — extended per commit
```

---

## 9. Future scope (deliberately deferred — do not build)

| Item | Why deferred |
|---|---|
| Live `libpcap` SPAN/mirror source | Needs a real network interface mirrored from a 5G edge switch. PCAP replay covers the demo. |
| MQTT / Zeek / Suricata adapters | Architecture supports them via `TrafficSource`; build when a real source exists. |
| Federated learning across edge nodes | Single-node MVP. Federation needs ≥ 2 deployments. |
| Cloud SIEM / SOAR integration | Out of scope by product definition. |
| GxP / Part 11 / OTA manager | Biotech-specific narrative in the IoTT paper; not generic edge IDS. |
| Multi-tenant / auth / RBAC | Single operator. |
| Adversarial-robustness evaluation | Worth doing eventually; not a deployable-product blocker. |
| Power-aware model switching on Thor | Cool research direction; not MVP. |
| Encrypted-traffic feature engineering (TLS fingerprints, JA3, etc.) | Edge-IIoTset is plaintext-feature-based. Encrypted-flow features come with their own dataset story. |
| Quantization beyond TensorRT FP16/INT8 defaults | Defer until baseline numbers exist. |

---

## 10. Role split

| Who | Does what |
|---|---|
| User | Reviews this brief; engages Claude Code on the other station; physically connects Thor for Commit 4; reviews each commit |
| Reviewer (Claude — this assistant) | Wrote this brief; reviews each commit; flags scope creep; helps interpret Thor benchmark results |
| Implementer (Claude Code on the other station) | Writes all code; picks the model architectures; ships four commits; tests green per commit |

Brief is locked. Deviations require a new entry in the **Change log** below before implementing.

---

## 11. Change log

- 2026-05-21 (v1.0): Initial implementation-ready brief. Three first-class attack categories, model-agnostic interfaces with performance gates, web dashboard, Thor deployment with measured validation. Four commits.
