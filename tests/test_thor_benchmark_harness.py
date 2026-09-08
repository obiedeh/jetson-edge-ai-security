"""Unit tests for the pure parts of deploy/thor/run_benchmark.py.

The harness is a standalone script, so it is loaded from its path. Only the
functions that need no onnxruntime session are exercised here; the smoke test
on real hardware lives in test_thor_smoke.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "thor" / "run_benchmark.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("thor_run_benchmark", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tier(target: float, p95: float, rps: float) -> dict:
    return {"target_rps": target, "p95_ms": p95, "actual_rps": rps}


def test_parse_tegrastats_extracts_ram_temps_and_rails(harness) -> None:
    line = (
        "09-08-2026 13:38:06 RAM 36614/125772MB (lfb 864x4MB) CPU [2%@972,64%@972] "
        "cpu@37.375C tj@39.093C gpu@38.031C VDD_GPU 1965mW/1965mW VIN 24222mW/24300mW"
    )
    sample = harness._parse_tegrastats(line)
    assert sample["ram_used_mb"] == 36614
    assert sample["ram_total_mb"] == 125772
    assert sample["temps_c"] == {"cpu": 37.375, "tj": 39.093, "gpu": 38.031}
    assert sample["rails_mw"] == {"VDD_GPU": 1965, "VIN": 24222}


def test_percentile_is_index_based(harness) -> None:
    vals = [1.0, 2.0, 3.0, 4.0]
    assert harness._percentile(vals, 50) == 3.0  # round(0.5 * 3) == 2 -> 3.0
    assert harness._percentile(vals, 95) == 4.0
    assert harness._percentile([], 50) is None


def test_summarize_window_reports_p50_and_peak(harness) -> None:
    samples = [
        {"mono": 1.0, "rails_mw": {"VIN": 100}, "temps_c": {"tj": 40.0}, "ram_used_mb": 10},
        {"mono": 2.0, "rails_mw": {"VIN": 300}, "temps_c": {"tj": 42.0}, "ram_used_mb": 12},
        {"mono": 3.0, "rails_mw": {"VIN": 200}, "temps_c": {"tj": 41.0}, "ram_used_mb": 11},
    ]
    summary = harness._summarize_window(samples)
    assert summary["n_samples"] == 3
    assert summary["rails_mw"]["VIN"] == {"p50": 200, "peak": 300, "min": 100}
    assert summary["temps_c"]["tj"] == {"p50": 41.0, "peak": 42.0}
    assert summary["board_ram_used_mb"] == {"p50": 11, "peak": 12}
    assert harness._summarize_window([]) == {"n_samples": 0}


def test_gates_pass_when_within_thresholds(harness) -> None:
    results = [
        {"model": "detector", "tiers": [_tier(10, 0.05, 10.0), _tier(1000, 0.03, 999.5)]},
        {"model": "forecaster", "tiers": [_tier(10, 0.05, 10.0), _tier(1000, 0.04, 1000.1)]},
    ]
    gates = harness._evaluate_gates(results, 1000.0, peak_rss_gb=0.35)
    assert {k: v["status"] for k, v in gates.items()} == {
        "detector_p95_latency_ms": "pass",
        "forecaster_p95_latency_ms": "pass",
        "throughput_at_1000_rps": "pass",
        "memory_footprint_gb": "pass",
    }
    assert gates["detector_p95_latency_ms"]["measured"] == 0.03
    # Lowest achieved rate across models is the throughput measurement.
    assert gates["throughput_at_1000_rps"]["measured"] == 999.5


def test_gates_fail_and_not_measured(harness) -> None:
    results = [
        {"model": "detector", "tiers": [_tier(1000, 12.0, 700.0)]},
        {"model": "forecaster", "tiers": [], "error": "provider failed"},
    ]
    gates = harness._evaluate_gates(results, 1000.0, peak_rss_gb=5.0)
    assert gates["detector_p95_latency_ms"]["status"] == "fail"
    assert gates["forecaster_p95_latency_ms"]["status"] == "not measured"
    assert gates["forecaster_p95_latency_ms"]["measured"] is None
    assert gates["throughput_at_1000_rps"]["status"] == "fail"
    assert gates["memory_footprint_gb"]["status"] == "fail"


def test_gate_thresholds_match_committed_template(harness) -> None:
    import json

    template = json.loads((_SCRIPT.parents[2] / "reports" / "thor_benchmark.json").read_text())
    for name, spec in harness.GATES.items():
        assert template["gates"][name]["threshold"] == spec["threshold"]
