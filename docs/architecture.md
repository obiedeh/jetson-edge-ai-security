# Architecture

## System Purpose

This repository provides the edge runtime security layer for the portfolio. It normalizes defensive telemetry into events, creates sliding-window features, emits baseline anomaly signals, and writes evidence reports without adding offensive tooling.

## Current Implementation Status

- **Implemented:** Typer CLI, Pydantic schemas, CSV replay source, sliding-window features, baseline detector, alert builder, runtime reporting, tests, and dataset catalog.
- **Runnable scaffold:** built-in defensive demo and demo report generation.
- **Planned Jetson deployment:** runtime metrics, memory profile, alert-throughput evidence, and hardware profile.
- **Future adapters:** PCAP, Zeek, Suricata, MQTT, and live defensive capture paths.

## Main Components

- `src/jetson_edge_ai_security/sources/`: telemetry source interfaces and CSV replay.
- `schemas.py`: normalized `TelemetryEvent`, window, detection, and alert models.
- `features/`: sliding-window aggregation.
- `detection/`: rule baseline and optional IsolationForest path.
- `alerts/`: alert construction from anomaly results.
- `runtime/`: pipeline orchestration, metrics, and evidence reporting.
- `datasets/`: allowlisted defensive dataset catalog and fetch helpers.
- `cli.py`: reproducible reviewer commands.

## Runtime Flow

The current runnable path uses `edge-security replay-csv`, `edge-security run-demo`, or `edge-security generate-demo-report`. Events are normalized, grouped into windows, scored by the detector, converted into alerts when needed, and summarized into JSONL/Markdown artifacts.

## Data / Telemetry Flow

CSV rows or built-in samples become `TelemetryEvent` records. Event windows become features. Features become anomaly results and alerts. Runtime metrics and reports are written as evidence artifacts.

## Deployment Modes

- **Local development:** CLI replay, tests, built-in demo, and generated reports.
- **Dataset replay:** allowlisted public defensive datasets or local CSV exports.
- **Planned Jetson deployment:** lightweight defensive runtime with metrics and sustained-run artifacts.
- **Future source adapters:** PCAP, Zeek, Suricata, MQTT, and live defensive interface monitoring.

## Evidence Artifacts

- Demo reports are generated under `reports/demo/` when the command is run.
- Reviewer placeholders live in `artifacts/sample-inputs/`, `artifacts/sample-outputs/`, `artifacts/logs/`, and `artifacts/reports/`.
- Diagram sources live in `docs/diagrams/`.

## Known Limitations

- Current proof is defensive replay evidence, not offensive security automation.
- Jetson runtime performance is not claimed until hardware artifacts are committed.
- Optional ML support does not replace the baseline detector evidence path.

## Next Validation Step

Commit one documented public defensive dataset replay with runtime metrics, alert JSONL, limitations, and a Jetson validation plan.
