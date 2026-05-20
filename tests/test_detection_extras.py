"""Tests for BaselineDetector edge cases, fit(), severity, and ModelRunner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jetson_edge_ai_security.detection.baseline import (
    BaselineDetector,
    BaselineThresholds,
    _severity,
)
from jetson_edge_ai_security.detection.model_runner import ModelRunner
from jetson_edge_ai_security.features.windows import build_feature_window
from jetson_edge_ai_security.schemas import TelemetryEvent

_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _events(n: int, attack_count: int = 0) -> list[TelemetryEvent]:
    return [
        TelemetryEvent(
            timestamp=_BASE_TS + timedelta(seconds=idx),
            source_ip=f"10.0.0.{idx + 1}",
            dest_ip="10.0.1.1",
            packet_size=100 + idx,
            attack_label=idx < attack_count,
        )
        for idx in range(n)
    ]


def _window(n: int = 5, attack_count: int = 0):
    return build_feature_window(_events(n, attack_count=attack_count))


# ---------------------------------------------------------------------------
# unfitted IsolationForest — must not crash
# ---------------------------------------------------------------------------

def test_detector_with_unfitted_isolation_forest_does_not_crash():
    """detect() must not raise NotFittedError when IF model exists but fit() was never called."""
    try:
        detector = BaselineDetector(
            BaselineThresholds(attack_count_threshold=1),
            use_isolation_forest=True,
        )
    except ImportError:
        pytest.skip("scikit-learn not installed")

    if not detector.isolation_forest_available:
        pytest.skip("scikit-learn not installed")

    # Should NOT raise; IF branch is skipped until fit() is called
    result = detector.detect(_window(attack_count=1))
    assert result.is_anomaly
    assert "isolation_forest_score" not in result.metadata


# ---------------------------------------------------------------------------
# fit() then detect() — IF branch activates
# ---------------------------------------------------------------------------

def test_detector_fit_then_detect_uses_isolation_forest():
    try:
        detector = BaselineDetector(
            use_isolation_forest=True,
            isolation_forest_kwargs={"random_state": 42, "contamination": 0.1},
        )
    except ImportError:
        pytest.skip("scikit-learn not installed")

    if not detector.isolation_forest_available:
        pytest.skip("scikit-learn not installed")

    training_windows = [_window(5) for _ in range(20)]
    detector.fit(training_windows)

    result = detector.detect(_window(5))
    assert "isolation_forest_score" in result.metadata


def test_detector_fit_with_no_windows_does_not_fit():
    try:
        detector = BaselineDetector(use_isolation_forest=True)
    except ImportError:
        pytest.skip("scikit-learn not installed")

    if not detector.isolation_forest_available:
        pytest.skip("scikit-learn not installed")

    detector.fit([])  # empty — should not set _model_fitted
    assert not detector._model_fitted


def test_detector_fit_without_isolation_forest_is_noop():
    detector = BaselineDetector()
    detector.fit([_window(), _window()])  # no model — should be silent no-op
    assert detector._model is None


# ---------------------------------------------------------------------------
# _severity table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("score", "attack_count", "expected"),
    [
        (0.0, 0, "low"),
        (1.5, 0, "low"),
        (2.0, 0, "medium"),
        (2.0, 1, "medium"),
        (3.0, 0, "high"),
        (3.0, 3, "high"),
        (4.0, 0, "critical"),
        (0.0, 10, "critical"),
        (1.0, 3, "high"),
        (1.0, 1, "medium"),
    ],
)
def test_severity_mapping(score: float, attack_count: int, expected: str) -> None:
    assert _severity(score, attack_count) == expected


# ---------------------------------------------------------------------------
# ModelRunner — thin wrapper
# ---------------------------------------------------------------------------

def test_model_runner_delegates_to_detector():
    detector = BaselineDetector(BaselineThresholds(attack_count_threshold=1))
    runner = ModelRunner(detector)
    window = _window(5, attack_count=1)

    direct = detector.detect(window)
    via_runner = runner.detect(window)

    assert via_runner.is_anomaly == direct.is_anomaly
    assert via_runner.severity == direct.severity
    assert via_runner.score == direct.score


def test_model_runner_returns_non_anomaly():
    detector = BaselineDetector(BaselineThresholds(
        packet_count_threshold=9999,
        event_rate_threshold=9999.0,
        unique_source_ip_threshold=9999,
        attack_count_threshold=9999,
    ))
    runner = ModelRunner(detector)
    result = runner.detect(_window(5, attack_count=0))

    assert not result.is_anomaly
