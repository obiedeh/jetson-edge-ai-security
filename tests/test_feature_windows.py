from datetime import UTC, datetime, timedelta

import pytest

from jetson_edge_ai_security.features import SlidingWindowExtractor
from jetson_edge_ai_security.features.windows import build_feature_window, window_stream
from jetson_edge_ai_security.schemas import TelemetryEvent


def test_sliding_window_feature_creation() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        TelemetryEvent(
            timestamp=start + timedelta(seconds=index),
            source_ip=f"10.0.0.{index}",
            dest_ip="10.0.1.1",
            protocol="TCP" if index % 2 else "UDP",
            packet_size=100 + index,
            tcp_flags="S" if index % 2 else None,
            attack_label=index == 2,
        )
        for index in range(5)
    ]

    windows = list(SlidingWindowExtractor(window_size=3, step=1).windows(events))

    assert len(windows) == 3
    assert windows[0].packet_count == 3
    assert windows[0].max_packet_size == 102
    assert windows[0].protocol_counts["UDP"] == 2
    assert windows[0].attack_count == 1
    assert windows[0].unique_source_ip_count == 3


def test_window_stream_convenience_wrapper() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        TelemetryEvent(
            timestamp=start + timedelta(seconds=i),
            source_ip="10.0.0.1",
            dest_ip="10.0.1.1",
            packet_size=64,
        )
        for i in range(10)
    ]

    windows = list(window_stream(events, window_size=5, step=2))

    assert len(windows) > 0
    assert all(w.packet_count == 5 for w in windows)


def test_build_feature_window_empty_raises() -> None:
    with pytest.raises(ValueError, match="no events"):
        build_feature_window([])


def test_sliding_window_invalid_params() -> None:
    with pytest.raises(ValueError, match="window_size"):
        SlidingWindowExtractor(window_size=0, step=1)
    with pytest.raises(ValueError, match="step"):
        SlidingWindowExtractor(window_size=5, step=0)


def test_sliding_window_fewer_events_than_window_size_yields_nothing() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        TelemetryEvent(timestamp=start + timedelta(seconds=i), packet_size=100)
        for i in range(3)
    ]

    windows = list(SlidingWindowExtractor(window_size=10, step=1).windows(events))

    assert windows == []

