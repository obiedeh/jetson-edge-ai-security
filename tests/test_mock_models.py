"""Tests for MockDetector and MockForecaster."""

from __future__ import annotations

import numpy as np
import pytest

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import DetectionResult, ForecastResult
from jetson_edge_ai_security.models.mock_detector import MockDetector, _mock_compute
from jetson_edge_ai_security.models.mock_forecaster import (
    MockForecaster,
    _mock_forecast_compute,
)

_FEAT_DIM = 57
_NUM_CLASSES = 15


@pytest.fixture
def detector() -> MockDetector:
    return MockDetector(feature_dim=_FEAT_DIM)


@pytest.fixture
def forecaster() -> MockForecaster:
    return MockForecaster(lookback_bins=20, forecast_bins=6, feature_dim=_FEAT_DIM)


# ──────────────────────────────────────────────────────────────────────────────
# MockDetector
# ──────────────────────────────────────────────────────────────────────────────


def test_detector_returns_detection_result(detector: MockDetector) -> None:
    x = np.zeros(_FEAT_DIM, dtype=np.float32)
    result = detector.predict(x)
    assert isinstance(result, DetectionResult)


def test_detector_probability_in_range(detector: MockDetector) -> None:
    rng = np.random.default_rng(42)
    for _ in range(20):
        x = rng.standard_normal(_FEAT_DIM).astype(np.float32)
        result = detector.predict(x)
        assert 0.0 <= result.probability <= 1.0


def test_detector_attack_type_valid(detector: MockDetector) -> None:
    x = np.ones(_FEAT_DIM, dtype=np.float32)
    result = detector.predict(x)
    assert result.attack_type in ATTACK_TYPES


def test_detector_per_class_probs_sum_to_one(detector: MockDetector) -> None:
    x = np.random.default_rng(1).standard_normal(_FEAT_DIM).astype(np.float32)
    result = detector.predict(x)
    total = sum(result.per_class_probabilities.values())
    assert abs(total - 1.0) < 1e-5


def test_detector_per_class_probs_15_entries(detector: MockDetector) -> None:
    x = np.zeros(_FEAT_DIM, dtype=np.float32)
    result = detector.predict(x)
    assert len(result.per_class_probabilities) == _NUM_CLASSES


def test_detector_latency_ms_non_negative(detector: MockDetector) -> None:
    x = np.zeros(_FEAT_DIM, dtype=np.float32)
    assert detector.predict(x).latency_ms >= 0.0


def test_detector_deterministic(detector: MockDetector) -> None:
    x = np.random.default_rng(7).standard_normal(_FEAT_DIM).astype(np.float32)
    r1 = detector.predict(x)
    r2 = detector.predict(x)
    assert r1.probability == r2.probability
    assert r1.attack_type == r2.attack_type


def test_detector_2d_input(detector: MockDetector) -> None:
    """(seq_len, feature_dim) input should be averaged and produce valid output."""
    h = np.random.default_rng(9).standard_normal((20, _FEAT_DIM)).astype(np.float32)
    result = detector.predict(h)
    assert isinstance(result, DetectionResult)
    assert 0.0 <= result.probability <= 1.0


def test_detector_metadata_structure(detector: MockDetector) -> None:
    assert detector.metadata.name == "mock-detector"
    assert detector.metadata.architecture == "mock"
    assert detector.metadata.feature_dim == _FEAT_DIM
    assert len(detector.metadata.output_classes) == _NUM_CLASSES


def test_mock_compute_probability_formula() -> None:
    """prob = tanh(mean(x) / 10) * 0.5 + 0.5."""
    x = np.array([10.0] * _FEAT_DIM, dtype=np.float32)
    prob, _, _ = _mock_compute(x, _NUM_CLASSES)
    expected = float(np.tanh(1.0) * 0.5 + 0.5)
    assert abs(prob - expected) < 1e-5


def test_mock_compute_logits_from_first_n_features() -> None:
    """Logits are computed from x[:num_classes], softmax applied."""
    x = np.zeros(_FEAT_DIM, dtype=np.float32)
    x[0] = 100.0  # first feature very large → first class should dominate
    _, _, per_class = _mock_compute(x, _NUM_CLASSES)
    assert per_class[0] > 0.99


# ──────────────────────────────────────────────────────────────────────────────
# MockForecaster
# ──────────────────────────────────────────────────────────────────────────────


def test_forecaster_returns_forecast_result(forecaster: MockForecaster) -> None:
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    result = forecaster.forecast(h)
    assert isinstance(result, ForecastResult)


def test_forecaster_intensity_shape(forecaster: MockForecaster) -> None:
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    result = forecaster.forecast(h)
    intensity = np.asarray(result.predicted_attack_intensity)
    assert intensity.shape == (6,)


def test_forecaster_type_per_bin_length(forecaster: MockForecaster) -> None:
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    result = forecaster.forecast(h)
    assert len(result.predicted_attack_type_per_bin) == 6


def test_forecaster_type_per_bin_valid_classes(forecaster: MockForecaster) -> None:
    h = np.random.default_rng(3).standard_normal((20, _FEAT_DIM)).astype(np.float32)
    result = forecaster.forecast(h)
    for t in result.predicted_attack_type_per_bin:
        assert t in ATTACK_TYPES


def test_forecaster_probability_in_range(forecaster: MockForecaster) -> None:
    rng = np.random.default_rng(5)
    for _ in range(10):
        h = rng.standard_normal((20, _FEAT_DIM)).astype(np.float32)
        result = forecaster.forecast(h)
        assert 0.0 <= result.probability <= 1.0


def test_forecaster_deterministic(forecaster: MockForecaster) -> None:
    h = np.random.default_rng(11).standard_normal((20, _FEAT_DIM)).astype(np.float32)
    r1 = forecaster.forecast(h)
    r2 = forecaster.forecast(h)
    assert r1.probability == r2.probability
    assert r1.predicted_attack_type_per_bin == r2.predicted_attack_type_per_bin
    np.testing.assert_array_equal(
        np.asarray(r1.predicted_attack_intensity),
        np.asarray(r2.predicted_attack_intensity),
    )


def test_forecaster_metadata_structure(forecaster: MockForecaster) -> None:
    assert forecaster.metadata.name == "mock-forecaster"
    assert forecaster.metadata.lookback_bins == 20
    assert forecaster.metadata.forecast_bins == 6
    assert forecaster.metadata.bin_seconds == 5


def test_forecaster_requires_2d_input(forecaster: MockForecaster) -> None:
    with pytest.raises(ValueError):
        forecaster.forecast(np.zeros(_FEAT_DIM, dtype=np.float32))


def test_forecaster_latency_non_negative(forecaster: MockForecaster) -> None:
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    assert forecaster.forecast(h).latency_ms >= 0.0


def test_forecaster_horizon_bins_matches_metadata(forecaster: MockForecaster) -> None:
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    result = forecaster.forecast(h)
    assert result.forecast_horizon_bins == forecaster.metadata.forecast_bins


def test_mock_forecast_compute_intensity_constant() -> None:
    """Intensity should be a constant array equal to clip(mean(last_step), 0)."""
    h = np.ones((20, _FEAT_DIM), dtype=np.float32) * 5.0
    intensity, _, _, _ = _mock_forecast_compute(h, forecast_bins=6)
    # last_step mean = 5.0, clipped = 5.0
    np.testing.assert_allclose(intensity, 5.0, atol=1e-5)


def test_mock_forecast_compute_negative_intensity_clipped() -> None:
    """Negative input mean → intensity clipped to 0."""
    h = np.ones((20, _FEAT_DIM), dtype=np.float32) * (-3.0)
    intensity, _, _, _ = _mock_forecast_compute(h, forecast_bins=6)
    np.testing.assert_allclose(intensity, 0.0, atol=1e-5)


def test_mock_forecast_compute_normal_dominant() -> None:
    """Class 0 (Normal) should dominate due to the class0 bias of 10.0."""
    h = np.zeros((20, _FEAT_DIM), dtype=np.float32)
    _, _, per_class, type_per_bin = _mock_forecast_compute(h, forecast_bins=6)
    assert all(t == "Normal" for t in type_per_bin)
    assert (per_class[:, 0] > 0.99).all()
