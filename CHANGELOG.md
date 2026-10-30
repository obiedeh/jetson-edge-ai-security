# Changelog

What changed in this repository, newest first, grouped by the date the
work landed on `main`. A number named here is read from a committed record
under `reports/`.

## Unreleased


- 2026-10-30: Link repository instructions to the shared hygiene policy and summarize board labels, private identifiers, hooks, immutable history and external handoff notes.
- TensorRT on the Thor, measured three ways (engine build, ONNX Runtime
  provider placement, benchmark with the TensorRT provider requested): no
  engine can be built for the shipped `ai.onnx.ml` tree and linear models,
  the provider falls back to the CPU, and the README now says so with the
  records (`reports/thor_tensorrt_*`, `reports/thor_benchmark_trt*`).
- Ingestion micro-benchmark measured on the Jetson AGX Thor
  (`reports/thor_benchmark*`, tegrastats sidecar).
- Reports name boards, not machines.
- Em dashes removed from the operator runbook title and the datasets note.
- This changelog.
