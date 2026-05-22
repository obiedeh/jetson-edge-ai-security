# Claude Code Kickoff Prompts

Ready-to-paste prompts for the implementer (Claude Code on the other station).
Authoritative spec: `docs/edge-ids-implementation-brief.md`. `AGENTS.md` rules
also apply throughout (Pydantic v2, mock adapter as test default, no OpenCV
or model imports in core event/analytics/telemetry modules, no autonomous
enforcement, no hardcoded `/data` paths).

---

## Commit 1 — Data, interfaces, mock impls, ONNX hook, training CLI

```
Your sole authoritative spec is `docs/edge-ids-implementation-brief.md`.
Read sections 1 through 5 end-to-end before writing any code. AGENTS.md
also applies.

Scope of this run: COMMIT 1 only.

Implement the file list under "COMMIT 1" in the brief's section 4. That
includes:
  - datasets/edge_iiotset.py (Edge-IIoTset loader with column normalization
    and time-aware 80/20 split helper)
  - features/temporal_binning.py (5-second bins, 20-bin sequences,
    deterministic shape (20, 57))
  - models/ new top-level package: interfaces.py, mock_detector.py,
    mock_forecaster.py, export_onnx.py, train.py (Typer subcommand wiring;
    no architecture in this commit)
  - tests/test_edge_iiotset_loader.py, test_temporal_binning.py,
    test_models_interfaces.py, test_mock_models.py, test_onnx_export_mock.py
  - tests/fixtures/edge_iiotset_sample_5k.csv (5k-row deterministic
    subset — generate from a fixed seed if Edge-IIoTset is not present
    locally; document the seed)

Modifications limited to: src/jetson_edge_ai_security/cli.py (add
`edge-security train`, `edge-security export onnx`, `edge-security bench`
subcommands as no-op placeholders for now), pyproject.toml (add onnx,
onnxruntime, pandas; put torch / tensorflow under a [ml] extra),
docs/datasets.md (Edge-IIoTset manual-download section).

Hard guardrails:
- One commit. Do NOT implement Commit 2, 3, or 4.
- No new top-level packages beyond models/.
- DO NOT pick a model architecture in this commit. Mock impls only.
- Pydantic v2 only. Type hints everywhere.
- No torch / tensorflow imports outside the [ml] extra. Mock impls must
  run with the default install path.
- ruff check . and pytest -q must be green before commit.
- No commit trailers, no AI attribution.
- Mock detector and mock forecaster are DETERMINISTIC given a seed.

Acceptance per the brief's COMMIT 1 section:
- MockDetector and MockForecaster round-trip through ONNX export and
  inference with output equality within fp32 tolerance
- 5-second binning + 20-bin sequencing produces deterministic shape
  (20, 57) on the fixture
- ruff + pytest green on default install (no [ml] extras)

Push to a feature branch named `claude-code-commit-1`. Do not push to
main. When done, open with: "Ready for review."

If anything in the brief is unclear or contradicts existing code, STOP
and ask before implementing.
```

---

## Commit 2 — Reference models + measured baselines

> **Prerequisite:** Commit 1 reviewed and merged to main. RTX 5090 dev box available with `[ml]` extras installed.

```
Your sole authoritative spec is `docs/edge-ids-implementation-brief.md`,
sections 1.3, 1.4, 1.5, 4 COMMIT 2, and 5 (performance gates). Commit 1
is on main.

Scope of this run: COMMIT 2 only — pick reference model architectures
and train them.

Implement per the brief's COMMIT 2 file list:
  - models/detectors/<chosen_arch>.py — one Detector implementation that
    beats the existing IsolationForest baseline by >= 0.05 AUC on the
    5k fixture. Pick the architecture you can defend on the latency
    budget (Thor p95 <= 10 ms per flow). Document the choice in the
    file's module docstring with one paragraph of rationale.
  - models/forecasters/<chosen_arch>.py — one Forecaster that beats
    Naive Lag-1 by >= 20% MAE reduction. Same rule — pick, document.
  - models/training/train_detector.py and train_forecaster.py with
    deterministic seeds and a "make train-detector" / "make
    train-forecaster" target.
  - models/eval/eval_detector.py (AUC, F1, per-class FPR) and
    eval_forecaster.py (MAE, RMSE, per-type forecast accuracy)
  - reports/training_run.json — committed with REAL measured numbers
    from your training run. Include: training run hash, dataset hash,
    AUC, F1, per-class FPR, MAE for forecaster, CPU latency p50/p95,
    CUDA latency p50/p95 if available. Do not fabricate.
  - All listed test files

Modifications limited to: cli.py (wire `edge-security models list` and
`edge-security models set-active`), runtime/pipeline.py (replace
Naive Lag-1 with the active Forecaster).

Hard guardrails:
- One commit.
- DO NOT ship both a fast model and a deep model — pick ONE Detector
  and ONE Forecaster. The IsolationForest baseline stays as a fallback.
- IsolationForest baseline is NOT to be removed. It remains under
  `detection/baseline.py`.
- Models must export to ONNX successfully. ONNX round-trip output
  equality test is REQUIRED.
- Numbers in reports/training_run.json must be from a real training
  run on the 5k fixture. Do not copy from the brief or papers.
- ruff check . and pytest -q must be green.
- pytest must include the gates: detector AUC >= baseline + 0.05,
  forecaster MAE reduction >= 20%.

Acceptance per the brief's COMMIT 2 section:
- Reference Detector beats IsolationForest by >= 0.05 AUC on the
  5k fixture (real measured numbers, in reports/training_run.json)
- Reference Forecaster beats Naive Lag-1 by >= 20% MAE on the 5k
  fixture
- Both export to ONNX cleanly, round-trip-equal within fp32 tolerance
- ruff + pytest green

Push to branch `claude-code-commit-2`. Do not push to main.
```

---

## Commit 3 — Pipeline integration + web dashboard

> **Prerequisite:** Commit 2 reviewed and merged to main.

```
Your sole authoritative spec is `docs/edge-ids-implementation-brief.md`,
sections 1.5, 1.6, 1.7, 2 (web), 3 (API), and 4 COMMIT 3.

Scope of this run: COMMIT 3 only — PCAP replay source, alerts store,
FastAPI surface, web dashboard.

Implement per the brief:
  - datasets/pcap_replay.py (flow-aggregate PCAP into Edge-IIoTset-
    shaped feature rows via 5-tuple + 1s window)
  - alerts/store.py + schema.sql (alerts, model_runs,
    forecast_snapshots tables; SQLite, append-only)
  - api/main.py (FastAPI), api/sse.py (SSE event stream); all
    endpoints in section 3 of the brief
  - web/ — entire Vite + React + TypeScript + Tailwind + shadcn/ui
    SPA with five screens (alerts, lookback, model-health, artifacts,
    settings) per section 2 of the brief

Scaffold web/:
  pnpm create vite web -- --template react-ts
  cd web && pnpm install
  pnpm add tailwindcss postcss autoprefixer
  pnpm dlx tailwindcss init -p
  pnpm dlx shadcn@latest init
  Add only these shadcn components: button, card, badge, input,
  scroll-area, skeleton, alert, dialog, tooltip, table, chart, select

Hard guardrails:
- One commit. Do NOT implement Commit 4 in this run.
- shadcn/ui only — no Material UI, no Chakra, no Ant Design.
- useState + useEffect only — no Redux, no Zustand, no React Query.
  Use fetch + a tiny in-memory cache.
- No streaming chat anywhere — the model is not conversational.
- No auth, no login screen.
- The data-source badge MUST be sourced server-side; client may not
  decide it. Allowed values: replay-csv, replay-pcap, live-mirror,
  validated-thor-benchmark, mock (mock only in dev with banner).
- The latency badge MUST be sourced from measured numbers in
  reports/training_run.json or reports/thor_benchmark.json. Never
  fabricated.
- pnpm build must succeed.
- Root .gitignore must exclude web/node_modules, web/dist,
  web/.env.local.

Acceptance per the brief's COMMIT 3 section:
- cd web && pnpm install && pnpm dev starts on :3000
- Backend on :8080 answers /alerts, /alerts/sse, /lookback, /forecast,
  /models, /model-health, /artifacts/*
- /lookback?minutes=60 + /forecast render a continuous time-series on
  S2 when piping a CSV or PCAP through the pipeline
- S1 alerts list updates via SSE within 1s of API emit
- S3 Model Health renders AUC sparkline, F1, per-class FPR, retrain
  flag (using values from reports/training_run.json)
- S4 Artifacts lists reports/, artifacts/, and models/exports/ files
- pnpm build green; no console errors on any screen
- ruff + pytest green

Push to branch `claude-code-commit-3`. Do not push to main.
```

---

## Commit 4 — Thor deployment + measured validation

> **Prerequisite:** Commit 3 reviewed and merged to main. Jetson AGX Thor on hand. JetPack and TensorRT installed.

```
Your sole authoritative spec is `docs/edge-ids-implementation-brief.md`,
section 4 COMMIT 4 and section 5 (performance gates). Commits 1-3 are
on main.

Scope of this run: COMMIT 4 only — Thor deployment + measured
validation. This commit produces REAL numbers from running on Thor.

Implement per the brief's COMMIT 4 file list:
  - deploy/thor/Dockerfile (aarch64 base, TensorRT runtime, copies
    models/exports/*.onnx and the FastAPI app and web/dist/)
  - deploy/thor/build_tensorrt_engines.py (onnx -> trt for each
    shipped model)
  - deploy/thor/run_benchmark.py (measures p50/p95/p99 latency at
    synthetic load tiers 10/100/1000 events/sec, sustained throughput,
    GPU memory, board power via tegrastats if available, 5 minutes
    per tier)
  - deploy/thor/edge-security.service (systemd unit)
  - deploy/thor/install.sh
  - deploy/thor/operator-runbook.md (install / upgrade / rollback /
    collect-logs procedures)
  - reports/thor_benchmark.json (committed with REAL measured numbers
    from a Thor run — SKU, JetPack version, TensorRT version, run
    hash, per-model latency tiers, throughput, power)
  - tests/test_thor_smoke.py (runs only on aarch64 with JETSON_SOC
    env var set; auto-skipped elsewhere)

Modifications limited to: web/components/latency-badge.tsx (flip to
validated-thor when reading from thor_benchmark.json),
web/pages/model-health.tsx (render Thor-measured numbers), README.md
(add "Validated on Jetson AGX Thor" section with the measured numbers),
PORTFOLIO_DELIVERABLES.md (update credibility-boundary section).

Hard guardrails:
- One commit.
- Numbers in reports/thor_benchmark.json MUST be from a real Thor
  run. Do not fabricate. Do not copy from the brief or papers.
- If a performance gate from section 5 of the brief is not met,
  DOCUMENT the deviation in operator-runbook.md and in the README's
  Validated on Thor section. Do not adjust the gate to hide the miss.
- The validated-thor badge in the UI must read from thor_benchmark.json
  and flip on only when a file with matching hardware tag is present.
  No mocking, no fallback to fabricated numbers.
- README's "Validated on Thor" section reports whatever the runs
  actually showed, not aspirational targets.
- ruff + pytest green on x86 (Thor smoke test auto-skips). Manual
  smoke run on Thor passes before commit.

Acceptance per the brief's COMMIT 4 section:
- TensorRT engines build on Thor from shipped ONNX
- edge-security.service starts on Thor and survives reboot
- POST /benchmark/thor produces thor_benchmark.json with measured,
  non-fabricated numbers; dashboard renders validated-thor badge
- README and PORTFOLIO_DELIVERABLES.md updated with the actual
  measured Thor numbers

Push to branch `claude-code-commit-4`. Do not push to main.
```

---

## After each commit

The reviewer (Claude in the original conversation) will:

1. Verify scope matches the brief — no scope creep
2. Run git diff and inspect key files
3. Check ruff + pytest in CI (and pnpm build for the web commit, and the Thor smoke test for Commit 4)
4. Verify the performance gates are honestly reported
5. Verify the credibility-badge wiring is server-sourced
6. Approve merge or request specific changes

Cosmetic differences that meet acceptance criteria are accepted as written. Functional deviations from the brief or unmet performance gates that are not documented as such require a brief amendment or a fix.
