#!/usr/bin/env python
"""Ingestion micro-benchmark: events/sec and p95 detection latency per source.

Replicates the small committed fixtures (Suricata EVE JSON and the replayable
CSV) into larger temporary files with monotonically shifted timestamps, then
measures on this machine:

* ``source_only``: iterating ``TrafficSource.events()`` (parse + normalize).
* ``pipeline``: the full PipelineRunner (windows, baseline detector, alerts)
  with per-window ``detector.detect()`` wall time (p50/p95/p99/max ms).
* ``pipeline_jsonl`` / ``pipeline_iot_fake``: the same pipeline with a JSONL
  sink, and with a JSONL sink plus the IoT Core sink driven by an in-process
  no-op client, to show the sink enqueue overhead. No network is used.

Results are written as JSON under ``reports/bench/`` (default name
``ingest_<hostname>.json``). This measures ingestion and detection on the
host it runs on; it is not a capture or line-rate claim.

Run on the workstation::

    .venv/bin/python deploy/bench/bench_sources.py

Run on the Jetson AGX Thor (from the device, after installing the package)::

    .venv/bin/python deploy/bench/bench_sources.py --label thor --output reports/bench/ingest_thor.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jetson_edge_ai_security.detection import BaselineDetector, Detector
from jetson_edge_ai_security.runtime import PipelineRunner
from jetson_edge_ai_security.schemas import DetectionResult, FeatureWindow
from jetson_edge_ai_security.sinks import IotCoreAlertSink, IotCoreSettings, JsonlAlertSink
from jetson_edge_ai_security.sinks.base import AlertSink
from jetson_edge_ai_security.sources import CsvReplaySource, SuricataEveSource, TrafficSource
from jetson_edge_ai_security.sources.suricata_source import SUPPORTED_EVENT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
EVE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "eve_sample.json"
CSV_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "telemetry_replay_sample.csv"
BADGE = "workstation-ingest-benchmark"


# ----------------------------------------------------------------------------
# Fixture replication with shifted timestamps
# ----------------------------------------------------------------------------


def replicate_eve(source: Path, dest: Path, repeat: int) -> int:
    """Write ``repeat`` copies of the EVE fixture, shifting timestamps by the span each copy."""

    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    stamps = [datetime.fromisoformat(r["timestamp"].replace("+0000", "+00:00")) for r in records]
    span = (max(stamps) - min(stamps)).total_seconds() + 1.0
    supported = sum(1 for r in records if r.get("event_type") in SUPPORTED_EVENT_TYPES)
    with dest.open("w", encoding="utf-8") as handle:
        for copy in range(repeat):
            for record, stamp in zip(records, stamps, strict=True):
                shifted = stamp.timestamp() + copy * span
                out = dict(record)
                out["timestamp"] = datetime.fromtimestamp(shifted, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+0000")
                handle.write(json.dumps(out, separators=(",", ":")) + "\n")
    return supported * repeat


def replicate_csv(source: Path, dest: Path, repeat: int) -> int:
    """Write ``repeat`` copies of the CSV fixture, shifting the epoch column by the span each copy."""

    lines = source.read_text(encoding="utf-8").splitlines()
    header, rows = lines[0], lines[1:]
    columns = header.split(",")
    ts_index = columns.index("frame.time_epoch")
    epochs = [float(row.split(",")[ts_index]) for row in rows]
    span = max(epochs) - min(epochs) + 1.0
    with dest.open("w", encoding="utf-8") as handle:
        handle.write(header + "\n")
        for copy in range(repeat):
            for row, epoch in zip(rows, epochs, strict=True):
                cells = row.split(",")
                cells[ts_index] = f"{epoch + copy * span:.6f}"
                handle.write(",".join(cells) + "\n")
    return len(rows) * repeat


# ----------------------------------------------------------------------------
# Timing helpers
# ----------------------------------------------------------------------------


class TimedDetector(Detector):
    """Wrap a detector and record per-window detect() wall time in milliseconds."""

    def __init__(self, inner: Detector) -> None:
        self.inner = inner
        self.samples_ms: list[float] = []

    def detect(self, window: FeatureWindow) -> DetectionResult:
        start = time.perf_counter()
        result = self.inner.detect(window)
        self.samples_ms.append((time.perf_counter() - start) * 1000.0)
        return result


class NoopIotClient:
    def connect(self) -> None:
        return None

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        return None

    def disconnect(self) -> None:
        return None


def percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(pct / 100.0 * (len(ordered) - 1))))
    return ordered[index]


def latency_summary(samples_ms: list[float]) -> dict[str, float | int]:
    return {
        "count": len(samples_ms),
        "p50_ms": round(percentile(samples_ms, 50), 4),
        "p95_ms": round(percentile(samples_ms, 95), 4),
        "p99_ms": round(percentile(samples_ms, 99), 4),
        "max_ms": round(max(samples_ms), 4) if samples_ms else 0.0,
        "mean_ms": round(statistics.fmean(samples_ms), 4) if samples_ms else 0.0,
    }


def bench_source_only(make_source: Any) -> dict[str, Any]:
    source: TrafficSource = make_source()
    start = time.perf_counter()
    count = 0
    with source:
        for _ in source.events():
            count += 1
    seconds = time.perf_counter() - start
    return {"events": count, "seconds": round(seconds, 4), "events_per_sec": round(count / seconds, 1)}


def bench_pipeline(make_source: Any, *, window_size: int, step: int, sinks: list[AlertSink]) -> dict[str, Any]:
    source: TrafficSource = make_source()
    detector = TimedDetector(BaselineDetector())
    start = time.perf_counter()
    with source:
        runner = PipelineRunner(source, window_size=window_size, step=step, detector=detector, sinks=sinks)
        alerts = runner.run()
    seconds = time.perf_counter() - start
    events = runner.metrics.events_seen
    result: dict[str, Any] = {
        "events": events,
        "seconds": round(seconds, 4),
        "events_per_sec": round(events / seconds, 1),
        "windows": runner.metrics.windows_seen,
        "alerts": len(alerts),
        "detect_latency": latency_summary(detector.samples_ms),
        "sink_errors": runner.sink_errors,
    }
    for sink in sinks:
        if isinstance(sink, IotCoreAlertSink):
            result["iot_core_sink"] = sink.stats()
    return result


def median_of(rounds: list[dict[str, Any]], *keys: str) -> float:
    values: list[float] = []
    for entry in rounds:
        current: Any = entry
        for key in keys:
            current = current[key]
        values.append(float(current))
    return round(statistics.median(values), 4)


# ----------------------------------------------------------------------------
# Host provenance
# ----------------------------------------------------------------------------


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def host_info(label: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "label": label or platform.node(),
        "hostname": platform.node(),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_avg_1m": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None,
    }
    model = Path("/proc/device-tree/model")
    if model.exists():
        info["device_model"] = model.read_text(errors="replace").strip("\x00\n")
    if shutil.which("nvpmodel"):
        try:
            info["nvpmodel"] = subprocess.run(
                ["nvpmodel", "-q"], capture_output=True, text=True, check=False, timeout=5
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return info


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eve-repeat", type=int, default=5000, help="Copies of the 12-line EVE fixture (8 events each).")
    parser.add_argument("--csv-repeat", type=int, default=100, help="Copies of the 360-row CSV fixture.")
    parser.add_argument("--rounds", type=int, default=3, help="Timed rounds per measurement (median reported).")
    parser.add_argument("--window-size", type=int, default=50)
    parser.add_argument("--step", type=int, default=10)
    parser.add_argument("--label", default=None, help="Host label for the artifact (default: hostname).")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path (default: reports/bench/ingest_<label>.json).")
    args = parser.parse_args(argv)

    label = args.label or platform.node()
    output = args.output or REPO_ROOT / "reports" / "bench" / f"ingest_{label}.json"

    with tempfile.TemporaryDirectory(prefix="edge-bench-") as tmp:
        tmp_dir = Path(tmp)
        eve_path = tmp_dir / "eve.json"
        csv_path = tmp_dir / "telemetry.csv"
        eve_expected = replicate_eve(EVE_FIXTURE, eve_path, args.eve_repeat)
        csv_expected = replicate_csv(CSV_FIXTURE, csv_path, args.csv_repeat)

        sources: dict[str, dict[str, Any]] = {
            "suricata_eve": {
                "fixture": str(EVE_FIXTURE.relative_to(REPO_ROOT)),
                "repeat": args.eve_repeat,
                "expected_events": eve_expected,
                "make": lambda: SuricataEveSource(eve_path),
            },
            "csv_replay": {
                "fixture": str(CSV_FIXTURE.relative_to(REPO_ROOT)),
                "repeat": args.csv_repeat,
                "expected_events": csv_expected,
                "make": lambda: CsvReplaySource(csv_path),
            },
        }

        results: dict[str, Any] = {}
        for name, spec in sources.items():
            make = spec["make"]
            print(f"[{name}] {spec['expected_events']} events from {spec['fixture']} x{spec['repeat']}", file=sys.stderr)
            source_rounds = [bench_source_only(make) for _ in range(args.rounds)]
            pipeline_rounds = [
                bench_pipeline(make, window_size=args.window_size, step=args.step, sinks=[]) for _ in range(args.rounds)
            ]
            jsonl_rounds = [
                bench_pipeline(
                    make,
                    window_size=args.window_size,
                    step=args.step,
                    sinks=[JsonlAlertSink(tmp_dir / f"{name}_{i}.jsonl")],
                )
                for i in range(args.rounds)
            ]
            iot_settings = IotCoreSettings(endpoint="bench.invalid", thing_name="bench", cert_path="-", key_path="-")
            iot_rounds = [
                bench_pipeline(
                    make,
                    window_size=args.window_size,
                    step=args.step,
                    sinks=[
                        JsonlAlertSink(tmp_dir / f"{name}_iot_{i}.jsonl"),
                        IotCoreAlertSink(iot_settings, client_factory=lambda _s: NoopIotClient(), queue_size=10000),
                    ],
                )
                for i in range(args.rounds)
            ]
            results[name] = {
                "fixture": spec["fixture"],
                "repeat": spec["repeat"],
                "expected_events": spec["expected_events"],
                "source_only": {
                    "events_per_sec_median": median_of(source_rounds, "events_per_sec"),
                    "rounds": source_rounds,
                },
                "pipeline": {
                    "events_per_sec_median": median_of(pipeline_rounds, "events_per_sec"),
                    "detect_p95_ms_median": median_of(pipeline_rounds, "detect_latency", "p95_ms"),
                    "rounds": pipeline_rounds,
                },
                "pipeline_jsonl": {
                    "events_per_sec_median": median_of(jsonl_rounds, "events_per_sec"),
                    "rounds": jsonl_rounds,
                },
                "pipeline_iot_fake": {
                    "events_per_sec_median": median_of(iot_rounds, "events_per_sec"),
                    "rounds": iot_rounds,
                },
            }
            print(
                f"[{name}] source-only {results[name]['source_only']['events_per_sec_median']:.0f} ev/s; "
                f"pipeline {results[name]['pipeline']['events_per_sec_median']:.0f} ev/s; "
                f"detect p95 {results[name]['pipeline']['detect_p95_ms_median']:.4f} ms; "
                f"jsonl sink {results[name]['pipeline_jsonl']['events_per_sec_median']:.0f} ev/s; "
                f"jsonl+iot(fake) {results[name]['pipeline_iot_fake']['events_per_sec_median']:.0f} ev/s",
                file=sys.stderr,
            )

    artifact = {
        "source_badge": BADGE,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "command": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]) if argv is None else " ".join(argv),
        "hardware": host_info(args.label),
        "config": {"window_size": args.window_size, "step": args.step, "rounds": args.rounds, "detector": "BaselineDetector"},
        "boundary": (
            "Ingestion and detection throughput on the named host with replicated committed fixtures; "
            "sink runs use a local file and an in-process no-op IoT client. No capture, network, "
            "or line-rate claim."
        ),
        "sources": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
