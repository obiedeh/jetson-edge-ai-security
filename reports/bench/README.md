# RTX 5090 Host Benchmarks

These are matched CPU-only runs of `deploy/thor/run_benchmark.py` on the RTX
5090 development host. They use the shipped ONNX exports and the same 300-second
tiers as the Thor run. The GPU was not used by this harness.

| Field | Recorded value |
| --- | --- |
| Host | `aimlstation` |
| CPU architecture | x86_64, 24 logical CPUs |
| Python / ONNX Runtime / NumPy | 3.12.3 / 1.26.0 / 1.26.4 |
| Governor | Not exposed by the harness or recorded in this run |
| Runs | `rtx5090_cpu.json` defaults; `rtx5090_cpu_single_thread.json` with one intra/inter-op thread and spin disabled |
| Date | 2026-09-09 UTC |

The artifact hardware blocks are authoritative for the recorded provenance.
No RTX GPU execution or power measurement is claimed.

## Ingestion micro-benchmark

`ingest_aimlstation.json` is one run of `deploy/bench/bench_sources.py` on the
same host (defaults: EVE fixture x5000 = 40,000 events, CSV fixture
x100 = 36,000 rows, 3 rounds, `window_size` 50, `step` 10, baseline
detector). It records source-only parsing throughput, full-pipeline
throughput, per-window `detect()` latency percentiles, and the same pipeline
with a JSONL sink and with JSONL plus an in-process no-op IoT Core client.
`git_commit` in the artifact is the commit the script ran against (the parent
of the commit that added the artifact). No network, capture, or line-rate
claim; the Thor run (`ingest_thor.json`) is pending.
