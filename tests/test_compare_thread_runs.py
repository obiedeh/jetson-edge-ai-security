"""Unit tests for deploy/thor/compare_thread_runs.py (pure comparison logic)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "thor" / "compare_thread_runs.py"


@pytest.fixture(scope="module")
def compare_mod():
    spec = importlib.util.spec_from_file_location("compare_thread_runs", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact(run_id: str, *, vin: float, misses: int, p95: float, spin: bool) -> dict:
    tier = {
        "target_rps": 1000.0, "actual_rps": 1000.0, "p50_ms": 0.02, "p95_ms": p95, "p99_ms": 0.03,
        "max_ms": 1.0, "deadline_misses": misses, "process_rss_gb": 0.35, "provider": "CPUExecutionProvider",
        "tegrastats": {"rails_mw": {"VIN": {"p50": vin, "peak": vin + 1000}, "VDD_CPU_SOC_MSS": {"p50": vin / 2}},
                       "temps_c": {"tj": {"peak": 50.0}}},
    }
    return {
        "run_id": run_id,
        "hardware": {"soc": "tegra264", "loadavg_1m_at_start": 1.0},
        "duration_per_tier_s": 120,
        "session_options": {"allow_spinning": spin},
        "idle_baseline": {"before_load": {"rails_mw": {"VIN": {"p50": 24000}}}},
        "models": [
            {"model": "detector", "tiers": [tier]},
            {"model": "forecaster", "tiers": [dict(tier, p95_ms=0.014)]},
        ],
    }


def test_compare_reports_deltas_per_model(compare_mod) -> None:
    base = _artifact("base", vin=54000, misses=40000, p95=0.024, spin=True)
    var = _artifact("var", vin=25000, misses=0, p95=0.030, spin=False)
    out = compare_mod.compare(base, var)
    assert out["same_device"] is True
    assert out["baseline"]["idle_vin_p50_mw"] == 24000
    det = [r for r in out["rows"] if r["model"] == "detector"][0]
    assert det["delta"]["vin_p50_mw"] == -29000.0
    assert det["delta"]["deadline_misses"] == -40000
    assert det["delta"]["p95_ms"] == pytest.approx(0.006)
    assert det["baseline"]["provider"] == "CPUExecutionProvider"
    assert {r["model"] for r in out["rows"]} == {"detector", "forecaster"}


def test_compare_skips_tiers_missing_on_either_side(compare_mod) -> None:
    base = _artifact("base", vin=1, misses=0, p95=0.1, spin=True)
    var = _artifact("var", vin=1, misses=0, p95=0.1, spin=False)
    var["models"][0]["tiers"][0]["target_rps"] = 100.0  # detector tier no longer matches
    out = compare_mod.compare(base, var)
    assert [r["model"] for r in out["rows"]] == ["forecaster"]


def test_compare_tolerates_missing_tegrastats(compare_mod) -> None:
    base = _artifact("base", vin=1, misses=0, p95=0.1, spin=True)
    var = _artifact("var", vin=1, misses=0, p95=0.1, spin=False)
    for m in var["models"]:
        m["tiers"][0]["tegrastats"] = None
    out = compare_mod.compare(base, var)
    det = out["rows"][0]
    assert det["variant"]["vin_p50_mw"] is None
    assert det["delta"]["vin_p50_mw"] is None
