"""Tests for the model interface contracts."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import (
    DetectionResult,
    DetectorMetadata,
    ForecasterMetadata,
    ForecastResult,
    _default_per_class,
    _softmax,
    measure_latency_ms,
)

# ──────────────────────────────────────────────────────────────────────────────
# DetectorMetadata
# ──────────────────────────────────────────────────────────────────────────────


def test_detector_metadata_construction() -> None:
    md = DetectorMetadata(
        name="test",
        version="1.0.0",
        architecture="mock",
        feature_dim=57,
        input_shape=(57,),
        output_classes=ATTACK_TYPES,
    )
    assert md.name == "test"
    assert md.onnx_path is None
    assert len(md.output_classes) == 15


def test_detector_metadata_onnx_path() -> None:
    md = DetectorMetadata(
        name="x",
        version="1",
        architecture="mock",
        feature_dim=57,
        input_shape=(57,),
        output_classes=ATTACK_TYPES,
        onnx_path="/tmp/model.onnx",
    )
    assert md.onnx_path == "/tmp/model.onnx"


def test_detector_metadata_serialization() -> None:
    md = DetectorMetadata(
        name="x",
        version="1",
        architecture="DNN",
        feature_dim=57,
        input_shape=(57,),
        output_classes=ATTACK_TYPES,
    )
    d = md.model_dump()
    assert d["name"] == "x"
    assert "output_classes" in d


# ──────────────────────────────────────────────────────────────────────────────
# ForecasterMetadata
# ──────────────────────────────────────────────────────────────────────────────


def test_forecaster_metadata_construction() -> None:
    md = ForecasterMetadata(
        name="lstm-v1",
        version="1.0.0",
        architecture="LSTM",
        lookback_bins=20,
        forecast_bins=6,
        bin_seconds=5,
    )
    assert md.lookback_bins == 20
    assert md.forecast_bins == 6
    assert md.bin_seconds == 5


# ──────────────────────────────────────────────────────────────────────────────
# DetectionResult
# ──────────────────────────────────────────────────────────────────────────────


def _make_det_meta() -> DetectorMetadata:
    return DetectorMetadata(
        name="m", version="1", architecture="mock", feature_dim=57,
        input_shape=(57,), output_classes=ATTACK_TYPES
    )


def test_detection_result_probability_bounds() -> None:
    md = _make_det_meta()
    res = DetectionResult(
        probability=0.75,
        attack_type="Normal",
        latency_ms=1.0,
        model_metadata=md,
    )
    assert res.probability == 0.75


def test_detection_result_probability_out_of_bounds() -> None:
    md = _make_det_meta()
    with pytest.raises(ValidationError):
        DetectionResult(
            probability=1.5,  # > 1.0
            attack_type="Normal",
            latency_ms=1.0,
            model_metadata=md,
        )


def test_detection_result_negative_latency_rejected() -> None:
    md = _make_det_meta()
    with pytest.raises(ValidationError):
        DetectionResult(
            probability=0.5,
            attack_type="Normal",
            latency_ms=-1.0,
            model_metadata=md,
        )


def test_detection_result_per_class_probs() -> None:
    md = _make_det_meta()
    probs = {t: 1.0 / 15 for t in ATTACK_TYPES}
    res = DetectionResult(
        probability=0.1,
        attack_type="Normal",
        per_class_probabilities=probs,
        latency_ms=0.0,
        model_metadata=md,
    )
    assert abs(sum(res.per_class_probabilities.values()) - 1.0) < 1e-6


# ──────────────────────────────────────────────────────────────────────────────
# ForecastResult
# ──────────────────────────────────────────────────────────────────────────────


def _make_fcast_meta() -> ForecasterMetadata:
    return ForecasterMetadata(
        name="m", version="1", architecture="mock",
        lookback_bins=20, forecast_bins=6, bin_seconds=5
    )


def test_forecast_result_construction() -> None:
    md = _make_fcast_meta()
    intensity = np.zeros(6, dtype=np.float32)
    res = ForecastResult(
        probability=0.2,
        attack_type="Normal",
        forecast_horizon_bins=6,
        predicted_attack_intensity=intensity,
        predicted_attack_type_per_bin=["Normal"] * 6,
        latency_ms=2.0,
        model_metadata=md,
    )
    assert res.forecast_horizon_bins == 6
    assert len(res.predicted_attack_type_per_bin) == 6


def test_forecast_result_intensity_as_ndarray() -> None:
    md = _make_fcast_meta()
    intensity = np.ones(6, dtype=np.float32) * 0.5
    res = ForecastResult(
        probability=0.5,
        attack_type="DDoS_ICMP",
        forecast_horizon_bins=6,
        predicted_attack_intensity=intensity,
        predicted_attack_type_per_bin=["DDoS_ICMP"] * 6,
        latency_ms=0.0,
        model_metadata=md,
    )
    assert np.allclose(res.predicted_attack_intensity, 0.5)


# ──────────────────────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────────────────────


def test_softmax_sums_to_one() -> None:
    x = np.array([1.0, 2.0, 3.0, 0.5])
    result = _softmax(x)
    assert abs(result.sum() - 1.0) < 1e-6
    assert (result >= 0).all()


def test_softmax_2d() -> None:
    x = np.array([[1.0, 2.0, 3.0], [0.5, 0.5, 0.5]])
    result = _softmax(x)
    assert result.shape == (2, 3)
    np.testing.assert_allclose(result.sum(axis=-1), 1.0, atol=1e-6)


def test_default_per_class_sums_to_one() -> None:
    logits = np.random.default_rng(0).standard_normal(15).astype(np.float32)
    pc = _default_per_class(logits, ATTACK_TYPES)
    assert len(pc) == 15
    assert abs(sum(pc.values()) - 1.0) < 1e-5


def test_measure_latency_ms() -> None:
    result, elapsed = measure_latency_ms(sum, range(1000))
    assert result == sum(range(1000))
    assert elapsed >= 0.0
