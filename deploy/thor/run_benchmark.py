#!/usr/bin/env python3
"""Thor benchmark: latency, throughput, memory, power and thermal evidence.

Runs paced inference against the shipped ONNX models at several load tiers
(default 10/100/1000 events per second, 300 s each) and writes one JSON
artifact that the static reports and the API read directly.

What is recorded:

- per model and tier: sample count, achieved events/sec, p50/p95/p99/min/max/
  mean latency, pacing deadline misses, execution provider actually used
- process memory: peak RSS via ``resource.getrusage`` plus current RSS
- Jetson only: a 1 Hz ``tegrastats`` time series (RAM, temperatures, rails)
  written beside the artifact, and per-tier power/thermal summaries
- hardware and software provenance: device-tree compatible string, L4T
  release line, ``nvpmodel`` mode, kernel, Python, onnxruntime, numpy,
  available providers, CPU count, load average, total RAM, git commit
- gate evaluation against the thresholds committed in the template

Usage::

    python3 deploy/thor/run_benchmark.py [--models-dir models/exports]
                                         [--models-spec models.json]
                                         [--output reports/thor_benchmark.json]
                                         [--duration 300]
                                         [--tiers 10,100,1000]
                                         [--trt]

Requirements: numpy, onnxruntime (``onnxruntime-gpu`` for CUDA/TensorRT
providers). Optional: psutil (current RSS), tegrastats (Jetson rails).

The script measures what it can and records nulls for what it cannot. It
never fabricates a value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import resource
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Gate thresholds. These mirror reports/thor_benchmark.json and the README
# table; change them in one place only.
GATES: dict[str, dict[str, Any]] = {
    "detector_p95_latency_ms": {"threshold": 10.0, "unit": "ms", "op": "<="},
    "forecaster_p95_latency_ms": {"threshold": 50.0, "unit": "ms", "op": "<="},
    "throughput_at_1000_rps": {"threshold": 1000.0, "unit": "events/s", "op": ">="},
    "memory_footprint_gb": {"threshold": 4.0, "unit": "GB", "op": "<="},
}
#: A paced loop cannot land exactly on the target; accept this fraction.
THROUGHPUT_TOLERANCE = 0.99


# ──────────────────────────────────────────────────────────────────────────────
# Hardware and software provenance
# ──────────────────────────────────────────────────────────────────────────────

def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def _jetson_compatible() -> list[str]:
    raw = _read_text("/sys/firmware/devicetree/base/compatible")
    if not raw:
        return []
    return [part for part in raw.split("\x00") if part]


def _jetson_soc() -> str | None:
    soc = os.getenv("JETSON_SOC")
    if soc:
        return soc
    compat = _jetson_compatible()
    for part in compat:
        if part.startswith("nvidia,tegra"):
            return part.split(",", 1)[1]
    return compat[0] if compat else None


def _l4t_release() -> str | None:
    text = _read_text("/etc/nv_tegra_release")
    if not text:
        return None
    return text.splitlines()[0].strip()


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _nvpmodel() -> str | None:
    text = _run(["nvpmodel", "-q"])
    return text.replace("\n", " ") if text else None


def _mem_total_gb() -> float | None:
    text = _read_text("/proc/meminfo")
    if not text:
        return None
    match = re.search(r"MemTotal:\s+(\d+) kB", text)
    return round(int(match.group(1)) / 1024 / 1024, 2) if match else None


def _git_sha(repo_hint: Path) -> str | None:
    return _run(["git", "-C", str(repo_hint), "rev-parse", "--short", "HEAD"])


def _hardware_info(models_dir: Path) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as ort

    soc = _jetson_soc()
    try:
        load1, load5, _ = os.getloadavg()
    except OSError:
        load1 = load5 = None
    return {
        "host": platform.node(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "soc": soc,
        "devicetree_compatible": _jetson_compatible(),
        "is_jetson": soc is not None,
        "l4t_release": _l4t_release(),
        "nvpmodel": _nvpmodel(),
        "cpu_count": os.cpu_count(),
        "mem_total_gb": _mem_total_gb(),
        "loadavg_1m_at_start": load1,
        "loadavg_5m_at_start": load5,
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "numpy": np.__version__,
        "available_providers": ort.get_available_providers(),
        "git_sha": _git_sha(models_dir),
        "benchmark_started_at": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Memory
# ──────────────────────────────────────────────────────────────────────────────

def _peak_rss_gb() -> float:
    # ru_maxrss is kilobytes on Linux.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 4)


def _current_rss_gb() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return round(psutil.Process().memory_info().rss / 1024 ** 3, 4)
    except Exception:
        text = _read_text("/proc/self/status")
        if not text:
            return None
        match = re.search(r"VmRSS:\s+(\d+) kB", text)
        return round(int(match.group(1)) / 1024 / 1024, 4) if match else None


# ──────────────────────────────────────────────────────────────────────────────
# tegrastats sampler (Jetson only)
# ──────────────────────────────────────────────────────────────────────────────

_RAIL_RE = re.compile(r"(V[A-Z0-9_]+)\s+(\d+)mW/(\d+)mW")
_TEMP_RE = re.compile(r"([a-z0-9]+)@([0-9.]+)C")
_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")


def _parse_tegrastats(line: str) -> dict[str, Any]:
    sample: dict[str, Any] = {"t": time.time(), "mono": time.monotonic()}
    ram = _RAM_RE.search(line)
    if ram:
        sample["ram_used_mb"] = int(ram.group(1))
        sample["ram_total_mb"] = int(ram.group(2))
    sample["temps_c"] = {name: float(val) for name, val in _TEMP_RE.findall(line)}
    sample["rails_mw"] = {name: int(inst) for name, inst, _avg in _RAIL_RE.findall(line)}
    return sample


class TegrastatsSampler:
    """Run ``tegrastats`` in the background and keep every parsed sample."""

    def __init__(self, interval_ms: int = 1000) -> None:
        self.interval_ms = interval_ms
        self.samples: list[dict[str, Any]] = []
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                ["tegrastats", "--interval", str(self.interval_ms)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
        except OSError:
            return False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if line.strip():
                self.samples.append(_parse_tegrastats(line))

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def window(self, mono_start: float, mono_end: float) -> list[dict[str, Any]]:
        return [s for s in self.samples if mono_start <= s["mono"] <= mono_end]


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    return sorted_vals[round((p / 100.0) * (n - 1))]


def _summarize_window(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"n_samples": 0}
    rails: dict[str, list[int]] = {}
    temps: dict[str, list[float]] = {}
    ram: list[int] = []
    for s in samples:
        for k, v in s.get("rails_mw", {}).items():
            rails.setdefault(k, []).append(v)
        for k, v in s.get("temps_c", {}).items():
            temps.setdefault(k, []).append(v)
        if "ram_used_mb" in s:
            ram.append(s["ram_used_mb"])
    return {
        "n_samples": len(samples),
        "rails_mw": {
            k: {"p50": _percentile(sorted(v), 50), "peak": max(v), "min": min(v)}
            for k, v in rails.items()
        },
        "temps_c": {k: {"p50": _percentile(sorted(v), 50), "peak": max(v)} for k, v in temps.items()},
        "board_ram_used_mb": {"p50": _percentile(sorted(ram), 50), "peak": max(ram)} if ram else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Inference
# ──────────────────────────────────────────────────────────────────────────────

def _session_options(intra: int, inter: int, spin: bool) -> Any:
    """Build onnxruntime SessionOptions; 0 threads means the runtime default."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    if intra > 0:
        so.intra_op_num_threads = intra
    if inter > 0:
        so.inter_op_num_threads = inter
    if not spin:
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return so


def _load_session(
    model_path: Path,
    use_trt: bool = False,
    cpu_only: bool = False,
    session_options: Any = None,
):
    import onnxruntime as ort

    available = ort.get_available_providers()
    providers: list[Any] = []
    if cpu_only:
        return ort.InferenceSession(
            str(model_path), sess_options=session_options, providers=["CPUExecutionProvider"]
        )
    if use_trt and "TensorrtExecutionProvider" in available:
        providers.append(("TensorrtExecutionProvider", {
            "trt_fp16_enable": True,
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": str(model_path.parent / "trt_cache"),
        }))
    if "CUDAExecutionProvider" in available:
        providers.append("CUDAExecutionProvider")
    providers.append("CPUExecutionProvider")
    return ort.InferenceSession(str(model_path), sess_options=session_options, providers=providers)


def _model_configs(models_dir: Path, spec_path: str | None) -> list[tuple[str, str, str, tuple[int, ...]]]:
    if not spec_path:
        return [("detector", "gbm_detector.onnx", "X", (1, 57)), ("forecaster", "ar_forecaster.onnx", "H", (1, 20, 57))]
    entries = json.loads(Path(spec_path).read_text())
    if not isinstance(entries, list) or not entries:
        raise ValueError("models spec must be a non-empty JSON list")
    configs = []
    for entry in entries:
        if not isinstance(entry, dict) or not all(k in entry for k in ("name", "file", "input_name", "shape")):
            raise ValueError("each models spec entry requires name, file, input_name, and shape")
        shape = tuple(int(d) for d in entry["shape"])
        if not shape or any(d <= 0 for d in shape):
            raise ValueError("model shape must contain positive dimensions")
        configs.append((str(entry["name"]), str(entry["file"]), str(entry["input_name"]), shape))
    return configs


def _benchmark_session(
    sess: Any,
    input_data: dict[str, Any],
    *,
    target_rps: float,
    duration_s: float,
    warmup_n: int = 20,
) -> dict[str, Any]:
    for _ in range(warmup_n):
        sess.run(None, input_data)

    interval = 1.0 / target_rps if target_rps > 0 else 0.0
    latencies: list[float] = []
    misses = 0
    start = time.monotonic()
    deadline = start + duration_s
    next_event = start

    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        if now < next_event:
            time.sleep(next_event - now)
        elif interval and now - next_event > interval:
            misses += 1
        next_event += interval
        t0 = time.perf_counter()
        sess.run(None, input_data)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    elapsed = time.monotonic() - start
    if not latencies:
        return {"error": "no samples collected"}
    lat = sorted(latencies)
    n = len(lat)
    return {
        "n_samples": n,
        "elapsed_s": round(elapsed, 3),
        "actual_rps": round(n / elapsed, 1),
        "deadline_misses": misses,
        "p50_ms": round(_percentile(lat, 50) or 0.0, 4),
        "p95_ms": round(_percentile(lat, 95) or 0.0, 4),
        "p99_ms": round(_percentile(lat, 99) or 0.0, 4),
        "min_ms": round(lat[0], 4),
        "max_ms": round(lat[-1], 4),
        "mean_ms": round(sum(lat) / n, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Gates
# ──────────────────────────────────────────────────────────────────────────────

def _tier(results: list[dict[str, Any]], model: str, target: float) -> dict[str, Any] | None:
    for entry in results:
        if entry["model"] != model:
            continue
        for tier in entry["tiers"]:
            if tier.get("target_rps") == target and "error" not in tier:
                return tier
    return None


def _gate(name: str, measured: float | None, *, criterion: str) -> dict[str, Any]:
    spec = GATES[name]
    if measured is None:
        status = "not measured"
    elif spec["op"] == "<=":
        status = "pass" if measured <= spec["threshold"] else "fail"
    else:
        status = "pass" if measured >= spec["threshold"] * THROUGHPUT_TOLERANCE else "fail"
    return {
        "threshold": spec["threshold"],
        "unit": spec["unit"],
        "measured": measured,
        "status": status,
        "criterion": criterion,
    }


def _evaluate_gates(results: list[dict[str, Any]], top_tier: float, peak_rss_gb: float) -> dict[str, Any]:
    det = _tier(results, "detector", top_tier)
    fc = _tier(results, "forecaster", top_tier)
    throughputs = [t["actual_rps"] for t in (det, fc) if t]
    return {
        "detector_p95_latency_ms": _gate(
            "detector_p95_latency_ms", det["p95_ms"] if det else None,
            criterion=f"p95 single-event latency at the {top_tier:.0f} events/s tier",
        ),
        "forecaster_p95_latency_ms": _gate(
            "forecaster_p95_latency_ms", fc["p95_ms"] if fc else None,
            criterion=f"p95 single-sequence latency at the {top_tier:.0f} events/s tier",
        ),
        "throughput_at_1000_rps": _gate(
            "throughput_at_1000_rps", min(throughputs) if throughputs else None,
            criterion=(
                f"lowest achieved events/s across models at the {top_tier:.0f} events/s tier; "
                f"pass at >= {THROUGHPUT_TOLERANCE:.0%} of target"
            ),
        ),
        "memory_footprint_gb": _gate(
            "memory_footprint_gb", peak_rss_gb,
            criterion="peak resident set size of the benchmark process (ru_maxrss)",
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Edge IDS Thor benchmark.")
    parser.add_argument("--models-dir", default="models/exports")
    parser.add_argument("--models-spec", help="JSON list of model name, file, input_name, and shape entries.")
    parser.add_argument("--output", default="reports/thor_benchmark.json")
    parser.add_argument("--duration", type=int, default=300, help="Seconds per load tier.")
    parser.add_argument("--tiers", default="10,100,1000", help="Comma-separated target events/s.")
    parser.add_argument("--trt", action="store_true", help="Prefer the TensorRT execution provider.")
    parser.add_argument(
        "--provider", choices=("auto", "cpu"), default="auto",
        help="auto: best available provider, falling back to CPU if it fails at run time; cpu: CPU only.",
    )
    parser.add_argument("--warmup", type=int, default=100, help="Single-inference warmup iterations.")
    parser.add_argument("--intra-op-threads", type=int, default=0, help="onnxruntime intra-op threads; 0 = runtime default.")
    parser.add_argument("--inter-op-threads", type=int, default=0, help="onnxruntime inter-op threads; 0 = runtime default.")
    parser.add_argument("--no-spin", action="store_true", help="Disable onnxruntime thread-pool spin waiting between runs.")
    parser.add_argument(
        "--idle-seconds", type=int, default=30,
        help="Jetson only: seconds of idle tegrastats sampling before and after the load tiers.",
    )
    args = parser.parse_args()

    try:
        import numpy as np
        import onnxruntime  # noqa: F401
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    models_dir = Path(args.models_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tiers = [float(t) for t in args.tiers.split(",") if t.strip()]
    duration_s = float(args.duration)

    hw_info = _hardware_info(models_dir)
    print("Hardware:", json.dumps(hw_info, indent=2))

    sampler: TegrastatsSampler | None = None
    if hw_info["is_jetson"]:
        sampler = TegrastatsSampler()
        if not sampler.start():
            print("tegrastats unavailable; rails and temperatures will be null")
            sampler = None

    idle_before: dict[str, Any] | None = None
    if sampler and args.idle_seconds > 0:
        print(f"\nIdle baseline: sampling {args.idle_seconds}s before load")
        t0 = time.monotonic()
        time.sleep(args.idle_seconds)
        idle_before = _summarize_window(sampler.window(t0, time.monotonic()))

    rng = np.random.default_rng(42)
    try:
        model_configs = _model_configs(models_dir, args.models_spec)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: invalid models spec: {exc}", file=sys.stderr)
        return 1

    all_results: list[dict[str, Any]] = []
    rss_before_gb = _current_rss_gb()
    try:
        for model_role, onnx_name, input_name, input_shape in model_configs:
            onnx_path = models_dir / onnx_name
            if not onnx_path.exists():
                print(f"\nSkipping {model_role}: {onnx_path} not found")
                continue
            print(f"\n{'=' * 60}\nBenchmarking: {model_role} ({onnx_name}) input {input_shape}")
            x = rng.standard_normal(input_shape).astype(np.float32)
            input_data = {input_name: x}
            provider_error: str | None = None
            try:
                sess = _load_session(
                    onnx_path, use_trt=args.trt, cpu_only=args.provider == "cpu",
                    session_options=_session_options(args.intra_op_threads, args.inter_op_threads, not args.no_spin),
                )
                sess.run(None, input_data)
            except Exception as exc:  # a provider that fails at run time is evidence too
                provider_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                print(f"  Provider failed, falling back to CPU: {provider_error}")
                try:
                    sess = _load_session(
                        onnx_path, cpu_only=True,
                        session_options=_session_options(args.intra_op_threads, args.inter_op_threads, not args.no_spin),
                    )
                    sess.run(None, input_data)
                except Exception as exc2:
                    all_results.append({
                        "model": model_role, "onnx": onnx_name,
                        "error": f"{type(exc2).__name__}: {str(exc2)[:300]}",
                        "provider_error": provider_error, "tiers": [],
                    })
                    print(f"  ERROR: CPU fallback also failed: {exc2}")
                    continue
            provider = sess.get_providers()[0]
            print(f"  Execution provider: {provider}")
            warm: list[float] = []
            for _ in range(max(args.warmup, 1)):
                t0 = time.perf_counter()
                sess.run(None, input_data)
                warm.append((time.perf_counter() - t0) * 1000)
            single_p50 = _percentile(sorted(warm), 50) or 0.0
            print(f"  Single-inference p50: {single_p50:.4f} ms")
            model_hash = hashlib.sha256(onnx_path.read_bytes()).hexdigest()[:16]

            tier_results: list[dict[str, Any]] = []
            for rps in tiers:
                print(f"\n  Tier {rps:.0f} events/s for {duration_s:.0f}s")
                mono_start = time.monotonic()
                tier = _benchmark_session(sess, input_data, target_rps=rps, duration_s=duration_s)
                mono_end = time.monotonic()
                tier["target_rps"] = rps
                tier["provider"] = provider
                tier["process_rss_gb"] = _current_rss_gb()
                tier["tegrastats"] = _summarize_window(sampler.window(mono_start, mono_end)) if sampler else None
                tier_results.append(tier)
                if "error" not in tier:
                    print(
                        f"    n={tier['n_samples']} actual={tier['actual_rps']} ev/s "
                        f"p50={tier['p50_ms']} p95={tier['p95_ms']} p99={tier['p99_ms']} ms "
                        f"misses={tier['deadline_misses']}"
                    )

            all_results.append({
                "model": model_role,
                "onnx": onnx_name,
                "onnx_sha256_16": model_hash,
                "provider": provider,
                "provider_error": provider_error,
                "provider_requested": args.provider,
                "trt_requested": args.trt,
                "single_inference_p50_ms": round(single_p50, 4),
                "tiers": tier_results,
            })
        if sampler and args.idle_seconds > 0:
            print(f"\nIdle baseline: sampling {args.idle_seconds}s after load")
            t0 = time.monotonic()
            time.sleep(args.idle_seconds)
            idle_after = _summarize_window(sampler.window(t0, time.monotonic()))
        else:
            idle_after = None
    finally:
        if sampler:
            sampler.stop()

    peak_rss_gb = _peak_rss_gb()
    top_tier = max(tiers) if tiers else 0.0
    gates = _evaluate_gates(all_results, top_tier, peak_rss_gb)
    finished = datetime.now(UTC).isoformat()
    run_hash = hashlib.sha256(f"{hw_info['benchmark_started_at']}{hw_info['soc']}".encode()).hexdigest()[:12]

    tegrastats_path: str | None = None
    if sampler and sampler.samples:
        side = output_path.with_name(output_path.stem + "_tegrastats.jsonl")
        with side.open("w") as fh:
            for s in sampler.samples:
                fh.write(json.dumps(s) + "\n")
        tegrastats_path = side.name

    report = {
        "run_id": run_hash,
        "note": (
            "Measured on the device described in `hardware`. Synthetic Gaussian inputs of the "
            "model input shapes; batch 1; single process; paced open-loop load. This is inference "
            "latency and throughput, not capture or flow-extraction performance."
        ),
        "hardware": hw_info,
        "benchmark_finished_at": finished,
        "duration_per_tier_s": duration_s,
        "tiers_requested_rps": tiers,
        "session_options": {
            "intra_op_num_threads": args.intra_op_threads or "runtime default",
            "inter_op_num_threads": args.inter_op_threads or "runtime default",
            "allow_spinning": not args.no_spin,
            "provider_requested": args.provider,
        },
        "models": all_results,
        "memory": {
            "process_peak_rss_gb": peak_rss_gb,
            "process_rss_before_gb": rss_before_gb,
            "process_rss_after_gb": _current_rss_gb(),
            "note": "Process RSS only. Board RAM is in the tegrastats summaries when present.",
        },
        "idle_baseline": {
            "seconds": args.idle_seconds if sampler else 0,
            "before_load": idle_before,
            "after_load": idle_after,
            "note": "Board rails and temperatures while this process slept; other host activity is included.",
        },
        "tegrastats_samples_file": tegrastats_path,
        "tegrastats_sample_count": len(sampler.samples) if sampler else 0,
        "gates": gates,
        "source_badge": "validated-thor-benchmark" if hw_info["is_jetson"] else "measured-cpu",
    }
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nWrote {output_path}")
    print("Gates:", json.dumps({k: v["status"] for k, v in gates.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
