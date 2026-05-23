# Historical Implementation Notes

This file is retained only as historical context for earlier implementation planning. It is not the current public evidence contract for the repository.

Current public positioning lives in:

- [README](../README.md)
- [Architecture](architecture.md)
- [Jetson sniffer upgrade plan](jetson-sniffer-upgrade-plan.md)
- [Thor operator runbook](../deploy/thor/operator-runbook.md)

## Current Evidence Path

```text
fixed CSV telemetry
  -> normalized events
  -> lookback analytics
  -> forecasting
  -> operator-reviewed alerts
  -> dashboard and reports
```

## Planned Jetson Ingestion Path

```text
SPAN/TAP/local interface
  -> rotating PCAP
  -> Zeek / Suricata / CICFlow-style flow extraction
  -> generated CSV
  -> existing analytics pipeline
```

## Boundary

This repo does not claim a live production IDS deployment, line-rate capture, autonomous response, offensive tooling, exploit replay, malware generation, or measured Thor-class performance until the relevant evidence artifacts are committed.

