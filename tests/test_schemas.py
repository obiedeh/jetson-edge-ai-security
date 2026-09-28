from datetime import datetime

import pytest
from pydantic import ValidationError

from jetson_edge_ai_security.schemas import TelemetryEvent


def test_telemetry_event_normalizes_protocol_and_attack_label() -> None:
    event = TelemetryEvent(
        timestamp="2026-01-01 00:00:00",
        source_ip="10.0.0.1",
        dest_ip="10.0.0.2",
        protocol="tcp",
        packet_size=128,
        attack_label="Attack",
    )

    assert isinstance(event.timestamp, datetime)
    assert event.protocol == "TCP"
    assert event.attack_label is True


def test_telemetry_event_rejects_bad_port() -> None:
    with pytest.raises(ValidationError):
        TelemetryEvent(source_port=70000)



def test_telemetry_event_accepts_epoch_timestamps() -> None:
    from datetime import UTC, datetime

    expected = datetime(2025, 1, 1, 0, 0, 0, 129686, tzinfo=UTC)
    assert TelemetryEvent(timestamp="1735689600.129686").timestamp == expected
    assert TelemetryEvent(timestamp=1735689600.129686).timestamp == expected
    assert TelemetryEvent(timestamp=1735689600).timestamp == expected.replace(microsecond=0)
    # Millisecond epochs are recognised by magnitude.
    assert TelemetryEvent(timestamp=1735689600129).timestamp == expected.replace(microsecond=129000)
