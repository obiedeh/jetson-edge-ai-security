#!/usr/bin/env python3
"""Compare two run_benchmark.py artifacts that differ only in session options.

Reads a baseline artifact (onnxruntime defaults) and a variant artifact
(for example ``--intra-op-threads 1 --inter-op-threads 1 --no-spin``) and
writes one comparison JSON with, per model and tier, the latency
percentiles, achieved rate, pacing misses, board VIN power and junction
temperature from each run and the deltas between them.

Usage::

    python3 deploy/thor/compare_thread_runs.py \\
        --baseline reports/thor_threads/default.json \\
        --variant reports/thor_threads/single_thread.json \\
        --output reports/thor_benchmark_threads.json

No new measurement is taken. The output records the source file hashes so
every number traces to a committed artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FIELDS = ("actual_rps", "p50_ms", "p95_ms", "p99_ms", "max_ms", "deadline_misses", "process_rss_gb")


def _tiers(artifact: dict[str, Any], model: str) -> dict[float, dict[str, Any]]:
    for entry in artifact.get("models", []):
        if entry.get("model") == model:
            return {float(t["target_rps"]): t for t in entry.get("tiers", []) if "error" not in t}
    return {}


def _rail(tier: dict[str, Any], rail: str, stat: str) -> float | None:
    tegra = tier.get("tegrastats") or {}
    value = (tegra.get("rails_mw") or {}).get(rail, {}).get(stat)
    return float(value) if isinstance(value, (int, float)) else None


def _temp(tier: dict[str, Any], sensor: str, stat: str) -> float | None:
    tegra = tier.get("tegrastats") or {}
    value = (tegra.get("temps_c") or {}).get(sensor, {}).get(stat)
    return float(value) if isinstance(value, (int, float)) else None


def _idle_vin(artifact: dict[str, Any]) -> float | None:
    window = (artifact.get("idle_baseline") or {}).get("before_load") or {}
    value = (window.get("rails_mw") or {}).get("VIN", {}).get("p50")
    return float(value) if isinstance(value, (int, float)) else None


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(b - a, 4)


def compare(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    base_models = [m["model"] for m in baseline.get("models", [])]
    var_models = {m["model"] for m in variant.get("models", [])}
    for model in [m for m in base_models if m in var_models]:
        base_tiers = _tiers(baseline, model)
        var_tiers = _tiers(variant, model)
        for target in sorted(set(base_tiers) & set(var_tiers)):
            b, v = base_tiers[target], var_tiers[target]
            row: dict[str, Any] = {"model": model, "target_rps": target, "baseline": {}, "variant": {}, "delta": {}}
            for field in FIELDS:
                bv, vv = b.get(field), v.get(field)
                row["baseline"][field] = bv
                row["variant"][field] = vv
                row["delta"][field] = _delta(bv, vv) if isinstance(bv, (int, float)) and isinstance(vv, (int, float)) else None
            for label, getter in (
                ("vin_p50_mw", lambda t: _rail(t, "VIN", "p50")),
                ("vin_peak_mw", lambda t: _rail(t, "VIN", "peak")),
                ("vdd_cpu_soc_mss_p50_mw", lambda t: _rail(t, "VDD_CPU_SOC_MSS", "p50")),
                ("tj_peak_c", lambda t: _temp(t, "tj", "peak")),
            ):
                bv, vv = getter(b), getter(v)
                row["baseline"][label] = bv
                row["variant"][label] = vv
                row["delta"][label] = _delta(bv, vv)
            row["baseline"]["provider"] = b.get("provider")
            row["variant"]["provider"] = v.get("provider")
            rows.append(row)

    same_device = (baseline.get("hardware") or {}).get("soc") == (variant.get("hardware") or {}).get("soc")
    return {
        "note": (
            "Two runs of deploy/thor/run_benchmark.py on the same device differing only in onnxruntime "
            "session options. Deltas are variant minus baseline. Board power includes unrelated host "
            "activity; the idle baselines of each run are given for reference."
        ),
        "same_device": same_device,
        "baseline": {
            "run_id": baseline.get("run_id"),
            "session_options": baseline.get("session_options"),
            "idle_vin_p50_mw": _idle_vin(baseline),
            "duration_per_tier_s": baseline.get("duration_per_tier_s"),
            "loadavg_1m_at_start": (baseline.get("hardware") or {}).get("loadavg_1m_at_start"),
        },
        "variant": {
            "run_id": variant.get("run_id"),
            "session_options": variant.get("session_options"),
            "idle_vin_p50_mw": _idle_vin(variant),
            "duration_per_tier_s": variant.get("duration_per_tier_s"),
            "loadavg_1m_at_start": (variant.get("hardware") or {}).get("loadavg_1m_at_start"),
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text())
    variant = json.loads(args.variant.read_text())
    result = compare(baseline, variant)
    result["sources"] = {
        str(args.baseline): hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        str(args.variant): hashlib.sha256(args.variant.read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for row in result["rows"]:
        d = row["delta"]
        print(
            f"{row['model']:<10} {row['target_rps']:>6.0f} ev/s  "
            f"p95 {row['baseline']['p95_ms']} -> {row['variant']['p95_ms']} ms  "
            f"VIN p50 {row['baseline']['vin_p50_mw']} -> {row['variant']['vin_p50_mw']} mW (delta {d['vin_p50_mw']})  "
            f"misses {row['baseline']['deadline_misses']} -> {row['variant']['deadline_misses']}"
        )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
