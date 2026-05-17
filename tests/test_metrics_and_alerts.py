from datetime import UTC, datetime, timedelta

from jetson_edge_ai_security.alerts.alert_builder import AlertBuilder
from jetson_edge_ai_security.detection.baseline import BaselineDetector, BaselineThresholds
from jetson_edge_ai_security.features.windows import build_feature_window
from jetson_edge_ai_security.runtime.metrics import RuntimeMetrics
from jetson_edge_ai_security.schemas import TelemetryEvent

_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _make_window(attack_count: int = 0):
    events = [
        TelemetryEvent(
            timestamp=_BASE_TS + timedelta(seconds=idx),
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
            packet_size=100,
            attack_label=idx < attack_count,
        )
        for idx in range(5)
    ]
    return build_feature_window(events)


def test_alert_builder_returns_none_for_non_anomaly():
    window = _make_window(attack_count=0)
    thresholds = BaselineThresholds(
        packet_count_threshold=1000,
        event_rate_threshold=1000.0,
        attack_count_threshold=10,
    )
    detector = BaselineDetector(thresholds)
    result = detector.detect(window)

    assert not result.is_anomaly
    assert AlertBuilder().from_detection(result) is None


def test_alert_builder_returns_alert_for_anomaly():
    window = _make_window(attack_count=2)
    thresholds = BaselineThresholds(attack_count_threshold=1)
    detector = BaselineDetector(thresholds)
    result = detector.detect(window)

    alert = AlertBuilder().from_detection(result)

    assert alert is not None
    assert alert.severity in ("low", "medium", "high", "critical")
    assert "anomaly" in alert.title.lower()


def test_runtime_metrics_finish_sets_timestamp():
    metrics = RuntimeMetrics()

    assert metrics.finished_at is None
    metrics.finish()
    assert metrics.finished_at is not None


def test_runtime_metrics_duration_seconds_positive():
    metrics = RuntimeMetrics()
    metrics.events_seen = 10
    metrics.finish()

    assert metrics.duration_seconds >= 0.0


def test_runtime_metrics_duration_before_finish_uses_now():
    metrics = RuntimeMetrics()

    assert metrics.duration_seconds >= 0.0
