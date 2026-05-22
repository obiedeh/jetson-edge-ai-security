#!/usr/bin/env python3
"""Thor benchmark — measures p50/p95/p99 latency, throughput, and power.

Runs synthetic inference at three load tiers (10/100/1000 events/sec),
sustained for 5 minutes per tier.  Reads ``tegrastats`` for board power
if running on Jetson.

Writes results to ``reports/thor_benchmark.json``.

Usage:
    python3 deploy/thor/run_benchmark.py [--models-dir models/exports]
                                         [--output reports/thor_benchmark.json]
                                         [--duration 300]
                                         [--tiers 10,100,1000]

Requirements:
    - onnxruntime-gpu (CUDA or TensorRT EP)
    - numpy
    - Optional: pynvml (GPU memory), tegrastats (Jetson power)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Hardware detection
# ──────────────────────────────────────────────────────────────────────────────

def _jetson_soc() -> str | None:
    """Return Jetson SoC string if running on Jetson, else None."""
    soc = os.getenv("JETSON_SOC")
    if soc:
        return soc
    compat = Path("/sys/firmware/devicetree/base/compatible")
    if compat.exists():
        try:
            return compat.read_text(errors="replace").split("\x00")[0]
        except OSError:
            pass
    return None


def _jetpack_version() -> str | None:
    release = Path("/etc/nv_tegra_release")
    if release.exists():
        try:
            first = release.read_text().splitlines()[0]
            return first.strip()
        except OSError:
            pass
    return None


def _gpu_memory_mb() -> float | None:
    try:
        import pynvml  # type: ignore[import]
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return mem.used / (1024 * 1024)
    except Exception:
        return None


def _read_tegrastats_power_mw() -> float | None:
    """Sample instantaneous board power via tegrastats (Jetson only)."""
    try:
        result = subprocess.run(
            ["tegrastats", "--interval", "100"],
            capture_output=True, text=True, timeout=0.5,
        )
        # Find "POM_5V_IN X/Y" or "VDD_CPU_CV X/Y mW" pattern
        line = result.stdout.strip().split("\n")[0] if result.stdout else ""
        for tok in line.split():
            if "/" in tok:
                try:
                    return float(tok.split("/")[0])
                except ValueError:
                    pass
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Inference helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_session(model_path: Path, use_trt: bool = False):
    """Load an OnnxRuntime session, preferring TensorRT EP on Jetson."""
    import onnxruntime as ort  # type: ignore[import]

    providers: list[str | tuple] = []
    if use_trt and "TensorrtExecutionProvider" in ort.get_available_providers():
        providers.append(("TensorrtExecutionProvider", {
            "trt_fp16_enable": True,
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": str(model_path.parent / "trt_cache"),
        }))
    if "CUDAExecutionProvider" in ort.get_available_providers():
        providers.append("CUDAExecutionProvider")
    providers.append("CPUExecutionProvider")

    return ort.InferenceSession(str(model_path), providers=providers)


def _benchmark_session(
    sess,
    input_data: dict,
    *,
    target_rps: float,
    duration_s: float,
    warmup_n: int = 20,
) -> dict[str, Any]:
    """Benchmark a session at *target_rps* for *duration_s* seconds.

    Returns latency percentiles and actual throughput.
    """
    # Warm-up
    for _ in range(warmup_n):
        sess.run(None, input_data)

    inter_event_s = 1.0 / target_rps if target_rps > 0 else 0.0
    latencies: list[float] = []
    deadline = time.monotonic() + duration_s
    next_event = time.monotonic()

    while time.monotonic() < deadline:
        # Pace to target RPS
        now = time.monotonic()
        if now < next_event:
            time.sleep(next_event - now)
        next_event += inter_event_s

        t0 = time.perf_counter()
        sess.run(None, input_data)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    if not latencies:
        return {"error": "no samples collected"}

    lat = sorted(latencies)
    n = len(lat)
    actual_rps = n / duration_s
    return {
        "n_samples": n,
        "actual_rps": round(actual_rps, 1),
        "p50_ms": round(lat[n // 2], 3),
        "p95_ms": round(lat[int(n * 0.95)], 3),
        "p99_ms": round(lat[int(n * 0.99)], 3),
        "min_ms": round(lat[0], 3),
        "max_ms": round(lat[-1], 3),
        "mean_ms": round(sum(latencies) / n, 3),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Edge IDS Thor benchmark.")
    parser.add_argument("--models-dir", default="models/exports")
    parser.add_argument("--output", default="reports/thor_benchmark.json")
    parser.add_argument("--duration", type=int, default=300,
                        help="Seconds per load tier (default: 300 = 5 min).")
    parser.add_argument("--tiers", default="10,100,1000",
                        help="Comma-separated target RPS tiers.")
    parser.add_argument("--trt", action="store_true", default=False,
                        help="Use TensorRT EP (requires .trt engine cache).")
    args = parser.parse_args()

    try:
        import numpy as np
        import onnxruntime  # noqa: F401
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    import numpy as np

    models_dir = Path(args.models_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tiers = [float(t) for t in args.tiers.split(",")]
    duration_s = float(args.duration)

    # Hardware info
    soc = _jetson_soc()
    hw_info = {
        "machine": platform.machine(),
        "soc": soc,
        "jetpack": _jetpack_version(),
        "is_jetson": soc is not None,
        "benchmark_started_at": datetime.now(UTC).isoformat(),
    }
    print("Hardware:", json.dumps(hw_info, indent=2))

    rng = np.random.default_rng(42)

    # Model configs: name → (onnx_name, input_name, input_shape)
    model_configs = [
        ("detector", "gbm_detector.onnx", "X", (1, 57)),
        ("forecaster", "ar_forecaster.onnx", "H", (1, 20, 57)),
    ]

    all_results: list[dict[str, Any]] = []
    run_hash = hashlib.sha256(f"{time.time()}{soc}".encode()).hexdigest()[:12]

    for model_role, onnx_name, input_name, input_shape in model_configs:
        onnx_path = models_dir / onnx_name
        if not onnx_path.exists():
            print(f"\nSkipping {model_role}: {onnx_path} not found")
            continue

        print(f"\n{'='*60}")
        print(f"Benchmarking: {model_role} ({onnx_name})")
        print(f"Input shape: {input_shape}")

        try:
            sess = _load_session(onnx_path, use_trt=args.trt)
        except Exception as e:
            print(f"  ERROR loading model: {e}")
            continue

        x = rng.standard_normal(input_shape).astype(np.float32)
        input_data = {input_name: x}

        # One-off single inference latency
        warmup_lat: list[float] = []
        for _ in range(100):
            t0 = time.perf_counter()
            sess.run(None, input_data)
            warmup_lat.append((time.perf_counter() - t0) * 1000)
        single_p50 = sorted(warmup_lat)[50]
        print(f"  Single-inference p50: {single_p50:.3f} ms")

        with onnx_path.open("rb") as fh:
            model_hash = hashlib.sha256(fh.read()).hexdigest()[:16]

        tier_results: list[dict[str, Any]] = []
        for rps in tiers:
            print(f"\n  Tier: {rps:.0f} events/sec  ({duration_s:.0f}s run)")
            gpu_mb_before = _gpu_memory_mb()
            power_before = _read_tegrastats_power_mw()

            tier = _benchmark_session(
                sess, input_data,
                target_rps=rps,
                duration_s=duration_s,
            )

            gpu_mb_after = _gpu_memory_mb()
            power_after = _read_tegrastats_power_mw()

            tier.update({
                "target_rps": rps,
                "gpu_memory_used_mb": gpu_mb_after,
                "power_mw_before": power_before,
                "power_mw_after": power_after,
            })
            tier_results.append(tier)
            print(f"    actual={tier.get('actual_rps')} rps  "
                  f"p50={tier.get('p50_ms')}ms  "
                  f"p95={tier.get('p95_ms')}ms  "
                  f"p99={tier.get('p99_ms')}ms")

        all_results.append({
            "model": model_role,
            "onnx": onnx_name,
            "onnx_hash": model_hash,
            "single_inference_p50_ms": round(single_p50, 3),
            "trt_ep": args.trt,
            "tiers": tier_results,
        })

    # Write benchmark report
    report = {
        "run_id": run_hash,
        "hardware": hw_info,
        "benchmark_finished_at": datetime.now(UTC).isoformat(),
        "duration_per_tier_s": duration_s,
        "models": all_results,
        "source_badge": "validated-thor-benchmark" if soc else "measured-cpu",
    }

    with output_path.open("w") as fh:
        json.dump(report, fh, indent=2)

    print(f"\nBenchmark report written: {output_path}")
    print(f"Run ID: {run_hash}")


if __name__ == "__main__":
    main()
