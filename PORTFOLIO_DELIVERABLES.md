# Portfolio Deliverables

This repository is scoped to a defensive edge security telemetry runtime with CSV replay, normalized events, feature windows, baseline detection, alerts, and runtime metrics.

## One-Command Checks

```bash
make install-dev
make verify
```

CI validates linting, type checks, tests, demo replay artifact generation, and artifact existence on Ubuntu.

## Proof Artifacts

| Artifact | Purpose |
| --- | --- |
| `reports/demo/runtime_metrics.json` | Machine-readable replay counters and alert severity counts |
| `reports/demo/alerts.jsonl` | Alert records emitted by the baseline detector |
| `reports/demo/replay_report.md` | Human-readable defensive replay summary |

## Current Evidence

- `TrafficSource` abstraction is implemented.
- `CsvReplaySource` maps Edge-IIoT style columns into normalized telemetry events.
- Sliding window features and baseline threshold detection are tested.
- The built-in demo replay generates alerts and runtime metrics without live capture or offensive tooling.

## Credibility Boundary

This repo does not generate malware, exploit systems, run autonomous attacks, or claim live production IDS coverage.

Jetson AGX Thor-class Linux is the measured edge target; see `reports/thor_benchmark.json` for what has and has not been measured. Sustained runtime and capture-path benchmarks remain pending.
