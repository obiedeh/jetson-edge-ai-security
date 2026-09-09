# Jetson Edge Intrusion Detection

**Defensive edge telemetry, lookback analytics, forecasting, and operator-reviewed IDS alerts for Jetson-class network nodes.**

Jetson Edge Intrusion Detection is a defensive edge telemetry system for Jetson-class nodes. The current implementation uses fixed CSV telemetry as a deterministic fixture for lookback analytics, forecasting, operator-reviewed alerts, reports, and dashboard evidence.

Fixed CSV is the deterministic test fixture, not the product ceiling. The planned Jetson sniffer upgrade adds Jetson-generated flow CSVs from packet capture and defensive telemetry sources such as Zeek logs, Suricata `eve.json`, and CICFlow-style records.

> [Open the evidence landing page](https://obiedeh.github.io/jetson-edge-ai-security/reports/index.html) | [Open the static dashboard](https://obiedeh.github.io/jetson-edge-ai-security/reports/dashboard.html) | [Architecture](docs/architecture.md) | [Thor runbook](deploy/thor/operator-runbook.md) | [Sniffer upgrade plan](docs/jetson-sniffer-upgrade-plan.md)

## Current Implementation

The working pipeline is intentionally small and inspectable:

```text
fixed CSV telemetry
  -> normalized TelemetryEvent records
  -> lookback analytics and sliding-window features
  -> baseline detection and forecasting evidence
  -> operator-reviewed alerts
  -> dashboard, reports, and benchmark artifacts
```

Implemented today:

- Pluggable `TrafficSource` API with context-manager lifecycle.
- `TelemetryEvent` and `Alert` schemas using Pydantic.
- CSV replay for Edge-IIoT-style datasets and similar IDS exports.
- Sliding-window feature extraction over iterable event streams.
- Rule-based baseline detector with optional `sklearn` IsolationForest support.
- Pipeline runner that tracks events, windows, detections, skipped rows, and emitted alerts.
- Typer CLI for config validation, CSV replay, demo execution, and static report generation.
- Static evidence pack under `reports/`.

## Why This Matters

Edge nodes, robotics cells, private-network sites, and AI-enabled systems need local defensive telemetry that can be reviewed close to the runtime environment. The value here is not replacing a SIEM or claiming a production IDS. The value is making local flow-style signals observable, forecastable, reviewable, and benchmarkable near the edge.

## Run This Demo

```bash
git clone https://github.com/obiedeh/jetson-edge-ai-security.git
cd jetson-edge-ai-security
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
edge-security run-demo
edge-security generate-demo-report --output-dir reports/demo
edge-security build-static-reports --reports-dir reports
```

Optional ML detector support:

```bash
python -m pip install -e ".[ml]"
```

## View the Evidence Pack

- [Landing page](reports/index.html)
- [Dashboard](reports/dashboard.html)
- [Demo replay report](reports/demo/replay_report.md)
- [Runtime metrics](reports/demo/runtime_metrics.json)
- [Training evidence](reports/training_run.json)
- [Thor benchmark, measured](reports/thor_benchmark.json) with the [1 Hz tegrastats series](reports/thor_benchmark_tegrastats.jsonl) and [run log](reports/thor_benchmark_run.log)
- [Thread-pool power comparison](reports/thor_benchmark_threads.json) built from [`reports/thor_threads/`](reports/thor_threads/) by [deploy/thor/compare_thread_runs.py](deploy/thor/compare_thread_runs.py)
- [Publication plan: what a write-up can and cannot claim yet](docs/publication-plan.md)
- [Portfolio deliverables](PORTFOLIO_DELIVERABLES.md)

GitHub shows committed HTML files as source code. Use the GitHub Pages links at the top of this README to open rendered pages.

## Current vs Planned

| Layer | Current working system | Planned Jetson ingestion upgrade |
|---|---|---|
| Input source | Fixed CSV fixture | Jetson-generated flow CSV |
| Capture mode | Deterministic replay | SPAN, TAP, or local interface capture |
| Packet stage | Not required for current evidence | Rotating PCAP files |
| Flow extraction | CSV columns normalized into `TelemetryEvent` | Zeek `conn.log`, Suricata `eve.json`, CICFlow-style records |
| Analytics path | Lookback analytics, forecasting, alerts, reports | Same existing analytics path |
| Dashboard impact | Implemented | No detector/dashboard rewrite intended |
| Hardware benchmark | Measured inference run committed (CPU provider) | Capture and flow-extraction measurement |

Adapters may change. The analytics pipeline should not.

## Defensive Boundary

This repo is defensive only.

- No malware generation.
- No exploit replay.
- No offensive tooling.
- No autonomous response.
- No line-rate capture claim.
- No production IDS deployment claim.
- Thor numbers are inference-only measurements from the committed artifact, on the CPU execution provider, with synthetic inputs. No capture, flow-extraction, or end-to-end latency claim.

## Planned Jetson Sniffer Upgrade

The planned upgrade is documented in [docs/jetson-sniffer-upgrade-plan.md](docs/jetson-sniffer-upgrade-plan.md).

Planned pipeline:

```text
SPAN/TAP/local interface
  -> rotating PCAP
  -> Zeek / Suricata / CICFlow-style flow extraction
  -> generated CSV
  -> existing lookback, forecasting, alert, and dashboard pipeline
```

The intent is source-agnostic flow ingestion. New sources should normalize into the same event/schema contract instead of forcing a detector or dashboard rewrite.

## Evidence Status

| Evidence | Status |
|---|---|
| Fixed CSV fixture replay | Implemented |
| Lookback analytics | Implemented |
| Forecasting evidence | Implemented |
| Operator-reviewed alerts | Implemented |
| Static landing page and dashboard | Implemented |
| Zeek / Suricata / CICFlow adapters | Planned |
| Jetson-generated flow CSV | Planned |
| Thor-class hardware benchmark | Measured, inference only, CPU provider |

## Architecture and Evidence

- [Architecture overview](docs/architecture.md)
- [System architecture diagram](docs/diagrams/system-architecture.mmd)
- [Runtime flow diagram](docs/diagrams/runtime-flow.mmd)
- [Data flow diagram](docs/diagrams/data-flow.mmd)
- [Deployment view diagram](docs/diagrams/deployment-view.mmd)

The `artifacts/` directories are reserved for future capture-stage evidence and currently hold only placeholders. Committed evidence lives under `reports/` and `models/exports/`.

```mermaid
flowchart LR
    A["Fixed CSV telemetry fixture"] --> B["TrafficSource API"]
    B --> C["Normalized TelemetryEvent"]
    C --> D["Lookback analytics and feature windows"]
    D --> E["Forecasting and baseline detection"]
    E --> F["Operator-reviewed alerts"]
    F --> G["Dashboard and evidence reports"]
    H["Planned Jetson flow ingestion<br/>PCAP / Zeek / Suricata / CICFlow"] -. "generated CSV" .-> B
```

## Core Stack

**Implemented:** Python, Typer, Pydantic, CSV replay, sliding-window features, baseline anomaly detection, pytest.

**Planned ingestion path:** Jetson-generated flow CSVs, Zeek logs, Suricata `eve.json`, CICFlow-style records, Thor-class benchmark evidence.

<p>
  <img src="https://img.shields.io/badge/Python-3.x-blue" alt="Python" />
  <img src="https://img.shields.io/badge/Typer-CLI-2F855A" alt="Typer" />
  <img src="https://img.shields.io/badge/Pydantic-schemas-E92063" alt="Pydantic" />
  <img src="https://img.shields.io/badge/scikit--learn-optional-F7931E" alt="scikit-learn optional" />
  <img src="https://img.shields.io/badge/Pytest-tested-brightgreen" alt="Pytest" />
  <img src="https://img.shields.io/badge/Jetson-integration%20path-76B900" alt="NVIDIA Jetson integration path" />
  <img src="https://img.shields.io/badge/Defensive%20Security-telemetry-555555" alt="Defensive Security" />
</p>

## Commands

Validate config:

```bash
edge-security validate-config --config configs/default.yaml
```

Run CSV replay:

```bash
edge-security replay-csv --path data/sample.csv --limit 1000
```

Enforce malformed-row handling:

```bash
edge-security replay-csv --path data/sample.csv --strict
```

List known public defensive datasets:

```bash
edge-security list-datasets
```

Fetch and replay an allowlisted dataset:

```bash
edge-security fetch-dataset wustl-iiot-2021
edge-security replay-dataset wustl-iiot-2021 --limit 1000
```

Run tests:

```bash
python -m pytest
```

Run the full verification path:

```bash
make verify
```

## Thor-Class Deployment Readiness

**Measured device:** Jetson AGX Thor Developer Kit (`tegra264`), R38 (release), `nvpmodel` 120W, 14 CPU cores, 122 GB RAM, Python 3.12.3, onnxruntime 1.29.0. Run `3cac5ed2b7bd`, 2026-09-08, 300 s per tier at 10, 100 and 1000 events/s, 60 s idle sampling before and after. Artifact: [`reports/thor_benchmark.json`](reports/thor_benchmark.json); 1 Hz board telemetry: [`reports/thor_benchmark_tegrastats.jsonl`](reports/thor_benchmark_tegrastats.jsonl); console log: [`reports/thor_benchmark_run.log`](reports/thor_benchmark_run.log).

| Gate | Threshold | Measured at 1000 events/s | Status |
|---|---|---|---|
| Detector p95 latency | <= 10 ms per flow | **0.0237 ms** (p50 0.0213, p99 0.028, max 14.7371) | pass |
| Forecaster p95 latency | <= 50 ms per `(20, 57)` sequence | **0.0141 ms** (p50 0.0138, p99 0.0143, max 1.0395) | pass |
| Throughput at 1000 events/sec | >= 1000 events/sec | **1000.0 events/s** achieved by both models | pass |
| Memory footprint | <= 4 GB | **0.3639 GB** peak process RSS | pass |

What these numbers are and are not:

- **CPU execution provider.** The PyPI `onnxruntime-gpu` 1.29.0 wheel loads a CUDA provider on Thor but fails at run time with `cudaErrorNoKernelImageForDevice`; the NVIDIA Jetson package index has no JetPack 7 build. The harness recorded the failure and fell back to CPU. For models this small (106 KB and 3 KB ONNX) the GPU would not change the result.
- **Inference only.** Inputs are synthetic Gaussian tensors of the model input shapes, batch 1, one process, open-loop pacing. Packet capture, flow extraction and end-to-end packet-to-alert latency are not measured.
- **Board power and the thread pool.** Idle VIN was 24170 mW and the forecaster tiers stayed near idle. In the full run the detector session drew about 54 W at 100 and 1000 events/s with 43118 pacing misses at the top tier. A matched comparison ([`reports/thor_benchmark_threads.json`](reports/thor_benchmark_threads.json), 120 s per tier, runs `1e430379de9b` and `42314e8252e9`) measured the cause: with onnxruntime defaults the detector drew **54102 mW** with **16944** misses at 1000 events/s; with `intra_op_num_threads=1`, `inter_op_num_threads=1` and spin waiting disabled it drew **24312 mW** with **0** misses, p95 0.0238 to 0.0219 ms, max 14.4675 to 0.9852 ms, junction peak 56.562 to 40.375 C. The CPU rail fell from 35366 to 7469 mW. The forecaster changed by under 0.2 W either way. For models this small the default spin-waiting thread pool costs about 30 W and buys nothing; the runbook now recommends the single-thread options for deployment. Raw runs: [`reports/thor_threads/`](reports/thor_threads/).
- **Host state.** One-minute load average was 3.1 at start from unrelated desktop activity, recorded in the artifact.

Reproduce on the device with the harness in [deploy/thor/run_benchmark.py](deploy/thor/run_benchmark.py); see [deploy/thor/operator-runbook.md](deploy/thor/operator-runbook.md) for install, upgrade, rollback, and benchmark procedures.

## Roadmap

The next steps are intentionally narrow:

- Add source adapters that generate the same CSV/event contract from Zeek, Suricata, and CICFlow-style records.
- Measure end-to-end packet-to-alert latency on Thor; the inference-only benchmark and the thread-pool power comparison are committed.
- Add packet-drop and flow-extraction measurements before making capture-performance claims.
- Keep all response actions operator-reviewed.

