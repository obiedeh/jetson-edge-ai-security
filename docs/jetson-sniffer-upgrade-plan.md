# Jetson Sniffer Upgrade Plan

## Goal

Use Jetson AGX Thor-class hardware as a defensive network telemetry node that captures mirrored traffic, converts packet captures into flow-level CSV records, and feeds the existing lookback, forecast, alert, and dashboard pipeline.

## Why This Upgrade Matters

The current fixed CSV fixture proves the analytics and reporting path. The next step is proving that Jetson-generated flow CSVs can enter the same contract without rewriting the detector, forecast, alert, or dashboard layers.

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

## Capture Safety Boundary

- No malware generation.
- No exploit replay.
- No offensive tooling.
- No autonomous response.
- No line-rate capture claim until packet drops, throughput, storage write rate, and flow extraction performance are measured and committed.

## Proposed Adapters

| Adapter | Status | Purpose |
|---|---|---|
| `CsvTrafficSource` | Implemented | Current deterministic fixture and local dataset replay path. |
| `ZeekConnLogSource` | Planned | Convert Zeek `conn.log` records into the existing event contract. |
| `SuricataEveJsonSource` | Planned | Convert Suricata `eve.json` flow and alert records into the existing event contract. |
| `CicFlowCsvSource` | Planned | Convert CICFlow-style CSV rows into the existing event contract. |
| `PcapCaptureStage` / `PcapFlowSource` | Planned | Capture or replay packets, rotate PCAP files, and hand flow extraction to a defensive parser. |

## Dashboard Metrics to Add Later

- Capture duration.
- Capture mode.
- Interface name.
- Packets observed.
- Packets dropped.
- PCAP files generated.
- Flows generated.
- CSV rows generated.
- Rows skipped.
- Alerts emitted.
- Inference p50/p95/p99.
- Memory footprint.
- Power and thermal notes from `tegrastats`, when available.

## Measurement Requirements Before Claiming Performance

Before claiming Jetson sniffer performance, commit an artifact that records:

- capture duration
- interface name
- capture mode
- packets observed
- packets dropped
- PCAP files generated
- flows generated
- CSV rows generated
- rows skipped
- alerts emitted
- inference p50/p95/p99
- memory footprint
- `tegrastats` power/thermal note, if available

