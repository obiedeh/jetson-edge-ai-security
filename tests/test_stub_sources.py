"""Tests verifying stub sources correctly signal NotImplementedError."""

from __future__ import annotations

import pytest

from jetson_edge_ai_security.sources.live_capture import LiveCaptureSource
from jetson_edge_ai_security.sources.mqtt_source import MqttTelemetrySource
from jetson_edge_ai_security.sources.pcap_replay import PcapReplaySource
from jetson_edge_ai_security.sources.suricata_source import SuricataEveSource
from jetson_edge_ai_security.sources.zeek_source import ZeekLogSource


def test_pcap_replay_open_raises():
    with pytest.raises(NotImplementedError):
        PcapReplaySource("/tmp/fake.pcap").open()


def test_pcap_replay_events_raises():
    with pytest.raises(NotImplementedError):
        list(PcapReplaySource("/tmp/fake.pcap").events())


def test_zeek_log_open_raises():
    with pytest.raises(NotImplementedError):
        ZeekLogSource("/tmp/conn.log").open()


def test_zeek_log_events_raises():
    with pytest.raises(NotImplementedError):
        list(ZeekLogSource("/tmp/conn.log").events())


def test_suricata_eve_open_raises():
    with pytest.raises(NotImplementedError):
        SuricataEveSource("/tmp/eve.json").open()


def test_suricata_eve_events_raises():
    with pytest.raises(NotImplementedError):
        list(SuricataEveSource("/tmp/eve.json").events())


def test_mqtt_source_open_raises():
    with pytest.raises(NotImplementedError):
        MqttTelemetrySource("mqtt://localhost", "telemetry/#").open()


def test_mqtt_source_events_raises():
    with pytest.raises(NotImplementedError):
        list(MqttTelemetrySource("mqtt://localhost", "telemetry/#").events())


def test_live_capture_open_raises():
    with pytest.raises(NotImplementedError):
        LiveCaptureSource("eth0").open()


def test_live_capture_events_raises():
    with pytest.raises(NotImplementedError):
        list(LiveCaptureSource("eth0").events())


def test_stub_sources_close_silently():
    """close() on uninitialized stubs must not raise."""
    PcapReplaySource("/tmp/fake.pcap").close()
    ZeekLogSource("/tmp/conn.log").close()
    SuricataEveSource("/tmp/eve.json").close()
    MqttTelemetrySource("mqtt://localhost", "t/#").close()
    LiveCaptureSource("eth0").close()
