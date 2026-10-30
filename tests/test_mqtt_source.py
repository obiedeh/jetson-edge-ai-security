"""Tests for the MQTT telemetry source using a fake client (no broker)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from jetson_edge_ai_security.cli import app
from jetson_edge_ai_security.config import AppConfig, MqttConfig, load_config
from jetson_edge_ai_security.sources import MqttTelemetrySource
from jetson_edge_ai_security.sources import mqtt_source as mqtt_module
from jetson_edge_ai_security.sources.mqtt_source import (
    DEFAULT_FIELD_MAP,
    merge_field_map,
    parse_broker_url,
)


@dataclass
class FakeMessage:
    topic: str
    payload: bytes


@dataclass
class FakeReasonCode:
    is_failure: bool = False


@dataclass
class FakeClient:
    """Minimal stand-in for paho's Client: delivers scripted messages on loop_start."""

    scripted: list[tuple[str, Any]] = field(default_factory=list)
    connect_failure: bool = False
    deliver_in_thread: bool = False
    on_connect: Any = None
    on_message: Any = None
    connected_to: tuple[str, int, int] | None = None
    subscriptions: list[tuple[str, int]] = field(default_factory=list)
    loop_started: bool = False
    loop_stopped: bool = False
    disconnected: bool = False

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.connected_to = (host, port, keepalive)

    def subscribe(self, topics: list[tuple[str, int]]) -> None:
        self.subscriptions.extend(topics)

    def loop_start(self) -> None:
        self.loop_started = True
        self.on_connect(self, None, {}, FakeReasonCode(self.connect_failure), None)
        if self.deliver_in_thread:
            threading.Thread(target=self._deliver, daemon=True).start()
        else:
            self._deliver()

    def _deliver(self) -> None:
        for topic, payload in self.scripted:
            if self.deliver_in_thread:
                time.sleep(0.005)
            self.inject(topic, payload)

    def inject(self, topic: str, payload: Any) -> None:
        raw = payload if isinstance(payload, bytes | str) else json.dumps(payload)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        self.on_message(self, None, FakeMessage(topic, raw))

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        self.disconnected = True


def _factory(client: FakeClient):
    def build(client_id: str, use_tls: bool) -> FakeClient:
        client.built_with = (client_id, use_tls)  # type: ignore[attr-defined]
        return client

    return build


SAMPLE = {
    "frame.time_epoch": 1758961800.5,
    "ip.src_host": "192.168.10.24",
    "ip.dst_host": "192.168.10.5",
    "tcp.srcport": 49212,
    "tcp.dstport": "1883",
    "_ws.col.Protocol": "mqtt",
    "frame.len": 128.0,
    "tcp.flags": "PA",
    "Attack_label": 1,
    "Attack_type": "DDoS_TCP",
    "device_temp_c": 41.5,
    "firmware": "1.4.2",
}


def test_default_mapping_and_unmapped_keys() -> None:
    client = FakeClient(scripted=[("edge-security/telemetry/sensor-1", SAMPLE)])
    source = MqttTelemetrySource(
        "mqtt://broker.local:1883",
        "edge-security/telemetry/#",
        client_factory=_factory(client),
        idle_timeout=0.05,
        poll_interval=0.01,
    )

    with source:
        events = list(source.events())

    assert len(events) == 1
    event = events[0]
    assert event.timestamp.isoformat() == "2025-09-27T08:30:00.500000+00:00"
    assert event.source_ip == "192.168.10.24"
    assert event.dest_ip == "192.168.10.5"
    assert event.source_port == 49212
    assert event.dest_port == 1883
    assert event.protocol == "MQTT"
    assert event.packet_size == 128
    assert event.tcp_flags == "PA"
    assert event.attack_label is True
    assert event.attack_type == "DDoS_TCP"
    assert event.source_type == "mqtt-telemetry"
    assert event.metadata["topic"] == "edge-security/telemetry/sensor-1"
    assert event.metadata["raw_source"] == "mqtt-telemetry"
    assert event.metadata["unmapped"] == {"device_temp_c": 41.5, "firmware": "1.4.2"}
    assert source.messages_seen == 1
    assert source.events_emitted == 1
    assert source.rows_skipped == 0


def test_lifecycle_connects_subscribes_and_disconnects() -> None:
    client = FakeClient()
    source = MqttTelemetrySource(
        "mqtts://broker.local",
        ["a/#", "b/+/c"],
        client_id="unit-test",
        qos=1,
        keepalive=15,
        client_factory=_factory(client),
        idle_timeout=0.01,
        poll_interval=0.005,
    )

    with source:
        assert client.built_with == ("unit-test", True)  # type: ignore[attr-defined]
        assert client.connected_to == ("broker.local", 8883, 15)
        assert client.subscriptions == [("a/#", 1), ("b/+/c", 1)]
        assert source.connected.is_set()
        list(source.events())

    assert client.loop_stopped and client.disconnected
    assert not source.connected.is_set()


def test_connect_refusal_does_not_subscribe() -> None:
    client = FakeClient(connect_failure=True)
    source = MqttTelemetrySource("mqtt://x", "t/#", client_factory=_factory(client))
    source.open()
    assert client.subscriptions == []
    assert not source.connected.is_set()
    source.close()


def test_custom_field_map_overrides_defaults() -> None:
    client = FakeClient(scripted=[("t", {"when": "2026-01-01 00:00:00", "from": "10.0.0.1", "size": 7})])
    source = MqttTelemetrySource(
        "mqtt://x",
        "t",
        field_map={"timestamp": ["when"], "source_ip": ["from"]},
        client_factory=_factory(client),
        idle_timeout=0.05,
        poll_interval=0.01,
    )
    events = list(source.events())
    assert events[0].source_ip == "10.0.0.1"
    assert events[0].timestamp.isoformat() == "2026-01-01T00:00:00+00:00"
    assert events[0].packet_size == 7  # default alias still applies to other fields
    assert events[0].metadata["unmapped"] == {}


def test_merge_field_map_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Unknown TelemetryEvent field"):
        merge_field_map({"not_a_field": ["x"]})
    merged = merge_field_map({"protocol": ["p"]})
    assert merged["protocol"] == ("p",)
    assert merged["timestamp"] == DEFAULT_FIELD_MAP["timestamp"]


def test_malformed_payloads_are_counted_or_raised() -> None:
    bad = [
        ("t", b"{not json"),
        ("t", b"[1, 2, 3]"),
        ("t", {"source_port": 70000}),
        ("t", {"packet_size": "big"}),
        ("t", {"source_ip": "10.0.0.9"}),
    ]
    client = FakeClient(scripted=bad)
    source = MqttTelemetrySource("mqtt://x", "t", client_factory=_factory(client), idle_timeout=0.05, poll_interval=0.01)
    events = list(source.events())
    assert len(events) == 1
    assert source.rows_skipped == 4

    strict = MqttTelemetrySource(
        "mqtt://x", "t", client_factory=_factory(FakeClient(scripted=bad)), strict=True, idle_timeout=0.05
    )
    with pytest.raises(ValueError):
        list(strict.events())


def test_bounded_queue_drops_newest_and_counts() -> None:
    client = FakeClient(scripted=[("t", {"source_ip": f"10.0.0.{i}"}) for i in range(6)])
    source = MqttTelemetrySource(
        "mqtt://x", "t", client_factory=_factory(client), queue_size=2, idle_timeout=0.05, poll_interval=0.01
    )
    events = list(source.events())
    assert [e.source_ip for e in events] == ["10.0.0.0", "10.0.0.1"]
    assert source.messages_seen == 6
    assert source.messages_dropped == 4


def test_limit_and_stop_event() -> None:
    client = FakeClient(scripted=[("t", {"source_ip": f"10.0.0.{i}"}) for i in range(10)])
    source = MqttTelemetrySource("mqtt://x", "t", client_factory=_factory(client), limit=3, poll_interval=0.01)
    assert len(list(source.events())) == 3

    stop = threading.Event()
    client = FakeClient(scripted=[], deliver_in_thread=True)
    source = MqttTelemetrySource("mqtt://x", "t", client_factory=_factory(client), stop_event=stop, poll_interval=0.01)
    threading.Timer(0.05, stop.set).start()
    started = time.monotonic()
    assert list(source.events()) == []
    assert time.monotonic() - started < 2.0


def test_messages_delivered_from_network_thread() -> None:
    scripted = [("edge-security/telemetry/n", {"source_ip": f"10.1.0.{i}", "frame.len": i}) for i in range(25)]
    client = FakeClient(scripted=scripted, deliver_in_thread=True)
    source = MqttTelemetrySource(
        "mqtt://x", "edge-security/telemetry/#", client_factory=_factory(client), idle_timeout=0.3, poll_interval=0.01
    )
    events = list(source.events())
    assert [e.packet_size for e in events] == list(range(25))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("mqtt://broker:1883", ("broker", 1883, False)),
        ("mqtt://broker", ("broker", 1883, False)),
        ("tcp://10.0.0.5:1884", ("10.0.0.5", 1884, False)),
        ("mqtts://broker", ("broker", 8883, True)),
        ("ssl://broker:9000", ("broker", 9000, True)),
        ("broker:1900", ("broker", 1900, False)),
    ],
)
def test_parse_broker_url(url: str, expected: tuple[str, int, bool]) -> None:
    assert parse_broker_url(url) == expected


def test_parse_broker_url_rejects_bad_schemes() -> None:
    with pytest.raises(ValueError):
        parse_broker_url("http://broker")
    with pytest.raises(ValueError):
        parse_broker_url("mqtt://")


def test_from_config_and_default_yaml() -> None:
    config = load_config(Path(__file__).parent.parent / "configs" / "default.yaml")
    assert config.mqtt.topics == ["edge-security/telemetry/#"]
    assert "frame.time_epoch" in config.mqtt.field_map["timestamp"]

    client = FakeClient()
    source = MqttTelemetrySource.from_config(config.mqtt, client_factory=_factory(client), idle_timeout=0.01)
    assert source.topics == ["edge-security/telemetry/#"]
    assert source.qos == 0
    assert source.field_map["timestamp"] == tuple(config.mqtt.field_map["timestamp"])
    assert source.field_map["icmp_type"] == DEFAULT_FIELD_MAP["icmp_type"]

    custom = AppConfig.model_validate(
        {"mqtt": {"broker_url": "mqtts://edge", "topics": ["a", "b"], "qos": 2, "queue_size": 5}}
    )
    source = MqttTelemetrySource.from_config(custom.mqtt, client_factory=_factory(FakeClient()))
    assert (source.host, source.port, source.use_tls, source.qos) == ("edge", 8883, True, 2)
    assert source._queue.maxsize == 5


def test_mqtt_config_validates_qos() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MqttConfig(qos=3)


def test_cli_run_mqtt_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rows = []
    for i in range(60):
        rows.append(
            {
                "timestamp": f"2026-01-01 00:00:{i % 60:02d}",
                "source_ip": f"10.0.0.{i + 1}",
                "dest_ip": "10.0.1.1",
                "source_port": 1000 + i,
                "dest_port": 443,
                "protocol": "TCP",
                "packet_size": 100,
                "attack_label": 1,
            }
        )
    client = FakeClient(scripted=[("edge-security/telemetry/x", row) for row in rows], deliver_in_thread=True)
    monkeypatch.setattr(mqtt_module, "paho_client_factory", _factory(client))

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "runtime:\n  window_size: 5\n  step: 5\n"
        "detector:\n  packet_count_threshold: 5\n  attack_count_threshold: 1\n"
        "mqtt:\n  broker_url: mqtt://localhost:1883\n  topics: [\"edge-security/telemetry/#\"]\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "evidence"
    result = CliRunner().invoke(
        app,
        [
            "run-mqtt",
            "--config",
            str(config_path),
            "--idle-timeout",
            "0.3",
            "--json-output",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "events=60" in result.output
    assert "messages=60" in result.output
    metrics = json.loads((output_dir / "runtime_metrics.json").read_text(encoding="utf-8"))
    assert metrics["events_seen"] == 60
    assert metrics["alerts_emitted"] >= 1
    assert metrics["source"] == "mqtt:mqtt://localhost:1883"
