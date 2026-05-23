"""Thor smoke tests — auto-skipped unless running on aarch64 + JETSON_SOC set.

These tests verify the full deployment on real Jetson AGX Thor hardware.
On x86 CI they are completely skipped.

To run on Thor:
    JETSON_SOC=tegra-234 pytest tests/test_thor_smoke.py -v
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Skip guard
# ──────────────────────────────────────────────────────────────────────────────

_ON_JETSON = (
    platform.machine() in ("aarch64", "arm64")
    and bool(os.getenv("JETSON_SOC"))
)

jetson_only = pytest.mark.skipif(
    not _ON_JETSON,
    reason="Thor smoke tests require aarch64 hardware + JETSON_SOC env var",
)

# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


@jetson_only
def test_jetson_soc_env_set() -> None:
    """JETSON_SOC must be set on real hardware."""
    soc = os.getenv("JETSON_SOC", "")
    assert soc, "JETSON_SOC is not set"
    assert "tegra" in soc.lower() or soc != "", f"Unexpected SOC value: {soc}"


@jetson_only
def test_onnx_models_exist() -> None:
    """Both reference ONNX models must be present in models/exports/."""
    det = Path("models/exports/gbm_detector.onnx")
    fcast = Path("models/exports/ar_forecaster.onnx")
    assert det.exists(), f"Detector ONNX not found: {det}"
    assert fcast.exists(), f"Forecaster ONNX not found: {fcast}"


@jetson_only
def test_onnx_models_loadable() -> None:
    """Both ONNX models must load without errors under onnxruntime."""
    import onnxruntime as ort

    for name in ("gbm_detector.onnx", "ar_forecaster.onnx"):
        path = Path("models/exports") / name
        if not path.exists():
            pytest.skip(f"{name} not found")
        sess = ort.InferenceSession(str(path))
        assert sess is not None


@jetson_only
def test_detector_onnx_inference_shape() -> None:
    """Detector ONNX must produce (1,) probability and (1, 15) logits."""
    import numpy as np
    import onnxruntime as ort

    path = Path("models/exports/gbm_detector.onnx")
    if not path.exists():
        pytest.skip("gbm_detector.onnx not found")

    sess = ort.InferenceSession(str(path))
    rng = np.random.default_rng(0)
    x = rng.standard_normal((1, 57)).astype(np.float32)
    outputs = sess.run(None, {"X": x})
    assert len(outputs) == 2
    prob, logits = outputs
    assert prob.shape == (1,), f"Expected (1,), got {prob.shape}"
    assert logits.shape == (1, 15), f"Expected (1, 15), got {logits.shape}"
    assert 0.0 <= float(prob[0]) <= 1.0


@jetson_only
def test_forecaster_onnx_inference_shape() -> None:
    """Forecaster ONNX must produce (1, 6) intensity and (1, 6, 15) type_logits."""
    import numpy as np
    import onnxruntime as ort

    path = Path("models/exports/ar_forecaster.onnx")
    if not path.exists():
        pytest.skip("ar_forecaster.onnx not found")

    sess = ort.InferenceSession(str(path))
    rng = np.random.default_rng(0)
    h = rng.standard_normal((1, 20, 57)).astype(np.float32)
    outputs = sess.run(None, {"H": h})
    assert len(outputs) == 2
    intensity, type_logits = outputs
    assert intensity.shape == (1, 6), f"Expected (1, 6), got {intensity.shape}"
    assert type_logits.shape == (1, 6, 15), f"Expected (1, 6, 15), got {type_logits.shape}"
    assert float(intensity.min()) >= 0.0


@jetson_only
def test_api_starts_and_responds() -> None:
    """FastAPI backend must respond on :8080 within 5 seconds."""
    import time
    import urllib.request

    for _ in range(10):
        try:
            with urllib.request.urlopen("http://localhost:8080/health", timeout=2) as r:
                body = r.read()
                assert b"ok" in body
                return
        except Exception:
            time.sleep(0.5)
    pytest.fail("FastAPI backend did not respond on :8080 within 5s")


@jetson_only
def test_trt_engines_present_if_built() -> None:
    """TRT engine files must be present alongside ONNX if build was run."""
    manifest = Path("models/exports/trt_build_manifest.json")
    if not manifest.exists():
        pytest.skip("TRT engines not built yet — run build_tensorrt_engines.py")

    import json
    with manifest.open() as fh:
        data = json.load(fh)

    built = [e for e in data.get("engines", []) if "error" not in e]
    assert len(built) >= 1, "No TRT engines built successfully"

    for engine_info in built:
        trt_path = Path(engine_info["engine_path"])
        assert trt_path.exists(), f"TRT engine not found: {trt_path}"
        assert trt_path.stat().st_size > 0, f"TRT engine is empty: {trt_path}"


@jetson_only
def test_benchmark_script_dry_run() -> None:
    """Benchmark script must complete a 5-second dry run on each model."""
    result = subprocess.run(
        [
            "python3",
            "deploy/thor/run_benchmark.py",
            "--duration", "5",
            "--tiers", "10",
            "--output", "/tmp/thor_benchmark_smoke.json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Benchmark failed:\n{result.stderr}"
    assert Path("/tmp/thor_benchmark_smoke.json").exists()


@jetson_only
def test_benchmark_output_schema() -> None:
    """Benchmark JSON must have expected top-level keys."""
    import json

    path = Path("/tmp/thor_benchmark_smoke.json")
    if not path.exists():
        pytest.skip("Run test_benchmark_script_dry_run first")

    with path.open() as fh:
        data = json.load(fh)

    assert "run_id" in data
    assert "hardware" in data
    assert "models" in data
    assert "source_badge" in data
    assert len(data["models"]) >= 1

    for m in data["models"]:
        assert "model" in m
        assert "tiers" in m
        for tier in m["tiers"]:
            assert "p50_ms" in tier
            assert "p95_ms" in tier
            assert "actual_rps" in tier
