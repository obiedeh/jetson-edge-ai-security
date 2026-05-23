# Edge IDS - Historical Implementation Brief

This file is retained as historical planning context. The current public evidence path is the fixed CSV fixture, generated reports, dashboard, architecture document, and pending Thor-class benchmark template.

The current positioning is:

```text
fixed CSV telemetry
  -> normalized events
  -> lookback analytics
  -> forecasting
  -> operator-reviewed alerts
  -> dashboard and reports
```

The planned Jetson sniffer path is:

```text
SPAN/TAP/local interface
  -> rotating PCAP
  -> Zeek / Suricata / CICFlow-style flow extraction
  -> generated CSV
  -> existing analytics pipeline
```

## Current Boundary

- This is defensive telemetry and intrusion-detection evidence only.
- Fixed CSV is the deterministic test fixture, not the product ceiling.
- Planned capture and flow-ingestion work must be measured before it is presented as completed Jetson evidence.
- Thor-class benchmark numbers remain pending until the exact device SKU, JetPack version, memory configuration, NIC/interface, capture mode, packet drops, throughput, latency, memory, power, and thermal notes are recorded in a committed artifact.
- No malware generation, exploit replay, offensive tooling, autonomous response, line-rate capture claim, or production IDS deployment claim is made.

## Active Documents

- [README](../README.md)
- [Architecture](architecture.md)
- [Jetson sniffer upgrade plan](jetson-sniffer-upgrade-plan.md)
- [Thor operator runbook](../deploy/thor/operator-runbook.md)
- [Production roadmap](production-roadmap.md)

