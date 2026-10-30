# RTX 5090 Host Benchmarks

These are matched CPU-only runs of `deploy/thor/run_benchmark.py` on the RTX
5090 development host. They use the shipped ONNX exports and the same 300-second
tiers as the Thor run. The GPU was not used by this harness.

| Field | Recorded value |
| --- | --- |
| Host | `rtx-5090-workstation` |
| CPU architecture | x86_64, 24 logical CPUs |
| Python / ONNX Runtime / NumPy | 3.12.3 / 1.26.0 / 1.26.4 |
| Governor | Not exposed by the harness or recorded in this run |
| Runs | `rtx5090_cpu.json` defaults; `rtx5090_cpu_single_thread.json` with one intra/inter-op thread and spin disabled |
| Date | 2026-09-09 UTC |

The artifact hardware blocks are authoritative for the recorded provenance.
No RTX GPU execution or power measurement is claimed.

## Ingestion micro-benchmark

`ingest_rtx-5090-workstation.json` is one run of `deploy/bench/bench_sources.py` on the
same host (defaults: EVE fixture x5000 = 40,000 events, CSV fixture
x100 = 36,000 rows, 3 rounds, `window_size` 50, `step` 10, baseline
detector). It records source-only parsing throughput, full-pipeline
throughput, per-window `detect()` latency percentiles, and the same pipeline
with a JSONL sink and with JSONL plus an in-process no-op IoT Core client.
`git_commit` in the artifact is the commit the script ran against (the parent
of the commit that added the artifact). No network, capture, or line-rate
claim; the Thor run (`ingest_thor.json`) is pending.

## Ingestion micro-benchmark on the Jetson AGX Thor

`ingest_jetson-agx-thor.json` is the same `deploy/bench/bench_sources.py` run
(same fixtures, repeats, rounds, window and detector) on the Jetson AGX Thor
Developer Kit: aarch64, 14 CPUs, NV Power Mode 120W, Python 3.12.3, load
average 0.92 before the run. Medians of 3 rounds: Suricata EVE source-only
43,903 ev/s, pipeline 34,525 ev/s, detect p95 0.0042 ms; CSV replay
source-only 36,796 ev/s, pipeline 31,084 ev/s, detect p95 0.0032 ms. The
run log is `ingest_jetson-agx-thor_run.log`. The board held a copy of commit
`7d36841` without `.git`; the artifact's `git_commit` field records that.
CPU only; no GPU, capture, network or line-rate claim.
