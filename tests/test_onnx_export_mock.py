"""Tests for ONNX export and round-trip validation of mock models.

Acceptance: MockDetector and MockForecaster round-trip through ONNX export
and inference with output equality within fp32 tolerance (atol=1e-4).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import pytest

from jetson_edge_ai_security.models.export_onnx import (
    _NUM_CLASSES,
    _validate_detector_onnx,
    _validate_forecaster_onnx,
    build_mock_detector_onnx,
    build_mock_forecaster_onnx,
    export_mock_detector,
    export_mock_forecaster,
)
from jetson_edge_ai_security.models.mock_detector import MockDetector, _mock_compute
from jetson_edge_ai_security.models.mock_forecaster import (
    MockForecaster,
    _mock_forecast_compute,
)

_FEAT_DIM = 57
_LOOKBACK = 20
_FORECAST = 6


# ──────────────────────────────────────────────────────────────────────────────
# build_mock_detector_onnx
# ──────────────────────────────────────────────────────────────────────────────


def test_build_detector_onnx_is_valid_model() -> None:
    model = build_mock_detector_onnx(feature_dim=_FEAT_DIM, num_classes=_NUM_CLASSES)
    assert isinstance(model, onnx.ModelProto)
    onnx.checker.check_model(model)


def test_build_detector_onnx_opset_17() -> None:
    model = build_mock_detector_onnx()
    opsets = {imp.domain: imp.version for imp in model.opset_import}
    assert opsets.get("", opsets.get("ai.onnx", 0)) == 17


def test_build_detector_onnx_has_two_outputs() -> None:
    model = build_mock_detector_onnx()
    assert len(model.graph.output) == 2
    output_names = {o.name for o in model.graph.output}
    assert "probability" in output_names
    assert "logits" in output_names


# ──────────────────────────────────────────────────────────────────────────────
# Detector round-trip
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 99])
def test_detector_onnx_round_trip(seed: int) -> None:
    """ONNX probability and logits must match Python mock within fp32 tolerance."""
    model = build_mock_detector_onnx(feature_dim=_FEAT_DIM, num_classes=_NUM_CLASSES)
    sess = ort.InferenceSession(model.SerializeToString())

    rng = np.random.default_rng(seed)
    x = rng.standard_normal(_FEAT_DIM).astype(np.float32)

    # Python reference
    prob_py, _, per_class_py = _mock_compute(x, _NUM_CLASSES)

    # ONNX inference
    x_batch = x[np.newaxis, :]  # (1, feature_dim)
    ort_out = sess.run(None, {"X": x_batch})
    prob_ort = float(ort_out[0][0])
    per_class_ort = ort_out[1][0]

    assert abs(prob_ort - prob_py) < 1e-4, (
        f"seed={seed}: probability mismatch — py={prob_py:.6f}, onnx={prob_ort:.6f}"
    )
    np.testing.assert_allclose(per_class_ort, per_class_py, atol=1e-4,
                                err_msg=f"seed={seed}: logits mismatch")


def test_detector_onnx_batch_gt1() -> None:
    """ONNX model should accept batch > 1."""
    model = build_mock_detector_onnx(feature_dim=_FEAT_DIM)
    sess = ort.InferenceSession(model.SerializeToString())
    X = np.random.default_rng(2).standard_normal((4, _FEAT_DIM)).astype(np.float32)
    ort_out = sess.run(None, {"X": X})
    prob = ort_out[0]
    logits = ort_out[1]
    assert prob.shape == (4,)
    assert logits.shape == (4, _NUM_CLASSES)


def test_detector_probability_range_onnx() -> None:
    model = build_mock_detector_onnx(feature_dim=_FEAT_DIM)
    sess = ort.InferenceSession(model.SerializeToString())
    rng = np.random.default_rng(55)
    for _ in range(20):
        x = rng.standard_normal((1, _FEAT_DIM)).astype(np.float32)
        prob = sess.run(["probability"], {"X": x})[0][0]
        assert 0.0 <= prob <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# export_mock_detector (to file)
# ──────────────────────────────────────────────────────────────────────────────


def test_export_detector_writes_file(tmp_path: Path) -> None:
    out = export_mock_detector(tmp_path / "det.onnx")
    assert out.exists()
    assert out.suffix == ".onnx"


def test_export_detector_loadable(tmp_path: Path) -> None:
    out = export_mock_detector(tmp_path / "det.onnx")
    model = onnx.load(str(out))
    onnx.checker.check_model(model)


def test_export_detector_ort_runnable(tmp_path: Path) -> None:
    out = export_mock_detector(tmp_path / "det.onnx")
    sess = ort.InferenceSession(str(out))
    x = np.zeros((1, _FEAT_DIM), dtype=np.float32)
    results = sess.run(None, {"X": x})
    assert results[0].shape == (1,)
    assert results[1].shape == (1, _NUM_CLASSES)


def test_validate_detector_onnx_passes() -> None:
    model = build_mock_detector_onnx(feature_dim=_FEAT_DIM)
    # Should not raise
    _validate_detector_onnx(model, feature_dim=_FEAT_DIM, num_classes=_NUM_CLASSES)


# ──────────────────────────────────────────────────────────────────────────────
# build_mock_forecaster_onnx
# ──────────────────────────────────────────────────────────────────────────────


def test_build_forecaster_onnx_is_valid_model() -> None:
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    assert isinstance(model, onnx.ModelProto)
    onnx.checker.check_model(model)


def test_build_forecaster_onnx_has_two_outputs() -> None:
    model = build_mock_forecaster_onnx(lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM)
    output_names = {o.name for o in model.graph.output}
    assert "intensity" in output_names
    assert "type_logits" in output_names


# ──────────────────────────────────────────────────────────────────────────────
# Forecaster round-trip
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", [0, 3, 13, 42])
def test_forecaster_onnx_round_trip(seed: int) -> None:
    """ONNX intensity and type_logits must match Python mock within fp32 tolerance."""
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    sess = ort.InferenceSession(model.SerializeToString())

    rng = np.random.default_rng(seed)
    h = rng.standard_normal((_LOOKBACK, _FEAT_DIM)).astype(np.float32)

    # Python reference
    intensity_py, type_logits_py, _, _ = _mock_forecast_compute(h, _FORECAST, _NUM_CLASSES)

    # ONNX inference (batch=1)
    h_batch = h[np.newaxis, :, :]  # (1, lookback, feature_dim)
    ort_out = sess.run(None, {"H": h_batch})
    intensity_ort = ort_out[0][0]     # (forecast_bins,)
    type_logits_ort = ort_out[1][0]   # (forecast_bins, num_classes)

    np.testing.assert_allclose(intensity_ort, intensity_py, atol=1e-4,
                                err_msg=f"seed={seed}: intensity mismatch")
    np.testing.assert_allclose(type_logits_ort, type_logits_py, atol=1e-4,
                                err_msg=f"seed={seed}: type_logits mismatch")


def test_forecaster_onnx_output_shapes() -> None:
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    sess = ort.InferenceSession(model.SerializeToString())
    h = np.zeros((2, _LOOKBACK, _FEAT_DIM), dtype=np.float32)
    ort_out = sess.run(None, {"H": h})
    assert ort_out[0].shape == (2, _FORECAST)
    assert ort_out[1].shape == (2, _FORECAST, _NUM_CLASSES)


def test_forecaster_intensity_non_negative_for_positive_input() -> None:
    """Last-step mean > 0 → intensity > 0."""
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    sess = ort.InferenceSession(model.SerializeToString())
    h = np.ones((1, _LOOKBACK, _FEAT_DIM), dtype=np.float32) * 2.0
    ort_out = sess.run(["intensity"], {"H": h})
    assert (ort_out[0] > 0).all()


def test_forecaster_intensity_zero_for_negative_input() -> None:
    """Negative input → clip(intensity, 0) = 0."""
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    sess = ort.InferenceSession(model.SerializeToString())
    h = np.ones((1, _LOOKBACK, _FEAT_DIM), dtype=np.float32) * (-5.0)
    ort_out = sess.run(["intensity"], {"H": h})
    np.testing.assert_allclose(ort_out[0], 0.0, atol=1e-5)


# ──────────────────────────────────────────────────────────────────────────────
# export_mock_forecaster (to file)
# ──────────────────────────────────────────────────────────────────────────────


def test_export_forecaster_writes_file(tmp_path: Path) -> None:
    out = export_mock_forecaster(tmp_path / "fcast.onnx", forecast_bins=_FORECAST)
    assert out.exists()
    assert out.suffix == ".onnx"


def test_export_forecaster_loadable(tmp_path: Path) -> None:
    out = export_mock_forecaster(tmp_path / "fcast.onnx", forecast_bins=_FORECAST)
    model = onnx.load(str(out))
    onnx.checker.check_model(model)


def test_validate_forecaster_onnx_passes() -> None:
    model = build_mock_forecaster_onnx(
        lookback_bins=_LOOKBACK, feature_dim=_FEAT_DIM, forecast_bins=_FORECAST
    )
    # Should not raise
    _validate_forecaster_onnx(
        model,
        lookback_bins=_LOOKBACK,
        feature_dim=_FEAT_DIM,
        forecast_bins=_FORECAST,
        num_classes=_NUM_CLASSES,
    )


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end: Python mock → ONNX → compare
# ──────────────────────────────────────────────────────────────────────────────


def test_end_to_end_detector_mock_vs_onnx(tmp_path: Path) -> None:
    """Full round-trip: export detector to file, load, compare with Python mock."""
    onnx_path = tmp_path / "det.onnx"
    export_mock_detector(onnx_path, validate=True)

    mock = MockDetector(feature_dim=_FEAT_DIM)
    x = np.random.default_rng(0).standard_normal(_FEAT_DIM).astype(np.float32)
    py_result = mock.predict(x)

    sess = ort.InferenceSession(str(onnx_path))
    ort_out = sess.run(None, {"X": x[np.newaxis, :]})
    prob_ort = float(ort_out[0][0])
    per_class_ort = ort_out[1][0]

    assert abs(prob_ort - py_result.probability) < 1e-4
    py_per_class = np.array(list(py_result.per_class_probabilities.values()))
    np.testing.assert_allclose(per_class_ort, py_per_class, atol=1e-4)


def test_end_to_end_forecaster_mock_vs_onnx(tmp_path: Path) -> None:
    """Full round-trip: export forecaster to file, load, compare with Python mock."""
    onnx_path = tmp_path / "fcast.onnx"
    export_mock_forecaster(onnx_path, forecast_bins=_FORECAST, validate=True)

    mock = MockForecaster(lookback_bins=_LOOKBACK, forecast_bins=_FORECAST, feature_dim=_FEAT_DIM)
    h = np.random.default_rng(1).standard_normal((_LOOKBACK, _FEAT_DIM)).astype(np.float32)
    py_result = mock.forecast(h)

    sess = ort.InferenceSession(str(onnx_path))
    ort_out = sess.run(None, {"H": h[np.newaxis, :, :]})
    intensity_ort = ort_out[0][0]
    type_logits_ort = ort_out[1][0]

    np.testing.assert_allclose(
        intensity_ort,
        np.asarray(py_result.predicted_attack_intensity),
        atol=1e-4,
    )
    np.testing.assert_allclose(
        type_logits_ort,
        np.asarray(py_result.raw_type_logits),
        atol=1e-4,
    )
