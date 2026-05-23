# Architecture

## System Purpose

Jetson Edge Intrusion Detection provides a defensive edge telemetry layer for Jetson-class nodes. It normalizes flow-style telemetry into events, creates lookback features, runs forecasting and baseline alert logic, and publishes evidence reports without adding offensive tooling or autonomous response.

## Architecture Principle

Adapters may change. The analytics pipeline should not.

The current system validates the analytics and forecasting layer with a fixed CSV fixture. The planned Jetson sniffer upgrade adds a packet/flow ingestion stage before the existing CSV/event contract. The detector, lookback, forecasting, alerting, and dashboard layers should remain stable as sources change.

## Current Pipeline

```text
fixed CSV
  -> normalized events
  -> lookback analytics
  -> forecasting
  -> alerts
  -> dashboard
```

## Planned Pipeline

```text
SPAN/TAP/local interface
  -> rotating PCAP
  -> Zeek / Suricata / CICFlow-style flow extraction
  -> generated CSV
  -> existing analytics pipeline
```

## Source Adapter Status

| Adapter | Status | Role |
|---|---|---|
| `CsvTrafficSource` | Implemented / current fixture | Reads deterministic CSV telemetry and normalizes rows into `TelemetryEvent` records. |
| `ZeekConnLogSource` | Planned | Normalize Zeek `conn.log` records into the same event contract. |
| `SuricataEveJsonSource` | Planned | Normalize Suricata `eve.json` flow/alert records into the same event contract. |
| `CicFlowCsvSource` | Planned | Normalize CICFlow-style CSV exports into the same event contract. |
| `PcapFlowSource` / `PcapCaptureStage` | Planned | Capture or replay packets, rotate PCAP files, and hand flow extraction to a defensive parser. |

## Main Components

- `src/jetson_edge_ai_security/sources/`: telemetry source interfaces and CSV replay.
- `schemas.py`: normalized `TelemetryEvent`, window, detection, and alert models.
- `features/`: sliding-window aggregation.
- `detection/`: rule baseline and optional IsolationForest path.
- `alerts/`: alert construction from anomaly results.
- `runtime/`: pipeline orchestration, metrics, and evidence reporting.
- `datasets/`: allowlisted defensive dataset catalog and fetch helpers.
- `cli.py`: reproducible CLI commands for validation, replay, demo reports, and static pages.

## Runtime Flow

The current runnable path uses `edge-security replay-csv`, `edge-security run-demo`, or `edge-security generate-demo-report`. Events are normalized, grouped into windows, scored by the detector, converted into alerts when needed, and summarized into JSONL, Markdown, and static HTML artifacts.

## Deployment Modes

- **Local development:** CLI replay, tests, built-in demo, and generated reports.
- **Dataset replay:** allowlisted public defensive datasets or local CSV exports.
- **Planned Jetson deployment:** lightweight defensive runtime with measured metrics and sustained-run artifacts.
- **Planned source adapters:** generated flow CSV from Zeek, Suricata, CICFlow-style records, or PCAP-derived flow extraction.

## Evidence Artifacts

- Demo reports are generated under `reports/demo/`.
- Static evidence pages are generated under `reports/index.html` and `reports/dashboard.html`.
- Thor-class benchmark status lives in `reports/thor_benchmark.json`.
- Diagram sources live in `docs/diagrams/`.

## Known Limitations

- Current proof is defensive replay evidence, not a production IDS deployment.
- Jetson runtime performance is not claimed until hardware artifacts are committed.
- Planned adapters are labeled as planned until measured source ingestion runs exist.
- The system does not generate malware, replay exploits, or execute autonomous response actions.

## Next Validation Step

Run a documented Jetson-generated flow CSV path and commit the measured capture duration, packets observed, packet drops, flows generated, rows skipped, alerts emitted, inference latency, memory footprint, and thermal/power notes.

