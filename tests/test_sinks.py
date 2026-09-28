"""Tests for alert sinks: base contract, JSONL, SQLite, IoT Core (fake client), config, pipeline."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jetson_edge_ai_security.config import AppConfig, load_config
from jetson_edge_ai_security.detection import BaselineDetector, BaselineThresholds
from jetson_edge_ai_security.runtime import PipelineRunner
from jetson_edge_ai_security.schemas import Alert, FeatureWindow
from jetson_edge_ai_security.sinks import (
    AlertSink,
    IotCoreAlertSink,
    IotCoreSettings,
    JsonlAlertSink,
    SqliteAlertSink,
    build_sinks,
    resolve_iot_core_settings,
)
from jetson_edge_ai_security.sinks.sqlite import confidence_from_alert
from jetson_edge_ai_security.sources import CsvReplaySource

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_SETTINGS = IotCoreSettings(
    endpoint="example-ats.iot.us-east-1.amazonaws.com",
    thing_name="thor-01",
    cert_path="/run/secrets/device.pem.crt",
    key_path="/run/secrets/private.pem.key",
    ca_path="/run/secrets/AmazonRootCA1.pem",
)


def _alert(index: int = 0, severity: str = "medium", **metadata: Any) -> Alert:
    window = FeatureWindow(
        window_start=_TS,
        window_end=_TS,
        packet_count=10 + index,
        mean_packet_size=100.0,
        max_packet_size=128,
        attack_count=index,
    )
    return Alert(
        timestamp=_TS,
        severity=severity,  # type: ignore[arg-type]
        title=f"Test anomaly {index}",
        description="Feature window triggered detection rules: test.",
        source="unit-test",
        features=window.model_dump(mode="json"),
        recommended_action="Investigate.",
        metadata={"score": 2.0, **metadata},
    )


# ----------------------------------------------------------------------------
# Base contract
# ----------------------------------------------------------------------------


class RecordingSink(AlertSink):
    name = "recording"

    def __init__(self, *, fail_on_publish: bool = False) -> None:
        self.alerts: list[Alert] = []
        self.health: list[dict[str, Any]] = []
        self.opened = 0
        self.closed = 0
        self.flushed = 0
        self.fail_on_publish = fail_on_publish

    def open(self) -> None:
        self.opened += 1

    def publish(self, alert: Alert) -> None:
        if self.fail_on_publish:
            raise RuntimeError("boom")
        self.alerts.append(alert)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed += 1

    def close(self) -> None:
        self.closed += 1

    def publish_health(self, payload: dict[str, Any]) -> None:
        self.health.append(payload)


def test_alert_sink_is_abstract_and_a_context_manager() -> None:
    with pytest.raises(TypeError):
        AlertSink()  # type: ignore[abstract]

    class Minimal(AlertSink):
        name = "minimal"

        def open(self) -> None: ...

        def publish(self, alert: Alert) -> None: ...

        def flush(self, timeout: float | None = None) -> None: ...

        def close(self) -> None: ...

    sink = RecordingSink()
    with sink as entered:
        assert entered is sink
        assert sink.opened == 1
    assert sink.closed == 1
    assert Minimal().publish_health({"x": 1}) is None  # default no-op


# ----------------------------------------------------------------------------
# JSONL
# ----------------------------------------------------------------------------


def test_jsonl_sink_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "alerts.jsonl"
    alerts = [_alert(i, severity=s) for i, s in enumerate(("low", "high", "critical"))]

    with JsonlAlertSink(path) as sink:
        for alert in alerts:
            sink.publish(alert)
        sink.flush()
    assert sink.published == 3

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [Alert.model_validate(json.loads(line)) for line in lines] == alerts
    assert json.loads(lines[0]) == json.loads(json.dumps(alerts[0].model_dump(mode="json"), sort_keys=True))

    with JsonlAlertSink(path) as sink:  # append by default
        sink.publish(_alert(9))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 4

    with JsonlAlertSink(path, append=False) as sink:
        sink.publish(_alert(10))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


# ----------------------------------------------------------------------------
# SQLite (dashboard AlertStore)
# ----------------------------------------------------------------------------


def test_sqlite_sink_feeds_alert_store(tmp_path: Path) -> None:
    from jetson_edge_ai_security.alerts.store import AlertStore

    db_path = tmp_path / "alerts.db"
    with SqliteAlertSink(db_path) as sink:
        sink.publish(_alert(1, severity="high", attack_type="DDoS_TCP"))
        sink.publish(_alert(2, severity="low"))
    assert sink.published == 2 and sink.failures == 0

    rows = asyncio.run(AlertStore(db_path=db_path).get_alerts())
    assert len(rows) == 2
    newest, oldest = rows
    assert oldest["attack_type"] == "DDoS_TCP"
    assert oldest["severity"] == "high"
    assert oldest["source"] == "unit-test"
    assert oldest["confidence"] == pytest.approx(0.5)
    assert newest["attack_type"] == "anomaly"
    payload = json.loads(oldest["payload_json"])
    assert payload["title"] == "Test anomaly 1"
    assert payload["features"]["packet_count"] == 11


def test_confidence_from_alert_is_clamped() -> None:
    assert confidence_from_alert(_alert(score=9.0)) == 1.0
    assert confidence_from_alert(_alert(score=-1.0)) == 0.0
    assert confidence_from_alert(_alert(score="bad")) == 0.0
    assert confidence_from_alert(_alert(score=1.0)) == pytest.approx(0.25)


# ----------------------------------------------------------------------------
# IoT Core with a fake client
# ----------------------------------------------------------------------------


@dataclass
class FakeIotClient:
    fail_connects: int = 0
    fail_publishes: int = 0
    always_fail: bool = False
    hold: threading.Event | None = None
    connects: int = 0
    disconnects: int = 0
    published: list[tuple[str, dict[str, Any], int]] = field(default_factory=list)
    attempts: int = 0

    def connect(self) -> None:
        self.connects += 1
        if self.always_fail or self.connects <= self.fail_connects:
            raise ConnectionError("connect refused")

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        self.attempts += 1
        if self.hold is not None:
            self.hold.wait()
        if self.always_fail or self.attempts <= self.fail_publishes:
            raise OSError("publish failed")
        self.published.append((topic, json.loads(payload.decode("utf-8")), qos))

    def disconnect(self) -> None:
        self.disconnects += 1


def _sink(client: FakeIotClient, **kwargs: Any) -> IotCoreAlertSink:
    kwargs.setdefault("sleep", lambda _s: None)
    return IotCoreAlertSink(_SETTINGS, client_factory=lambda settings: client, **kwargs)


def test_iot_core_publishes_alerts_and_health_on_fleet_topics() -> None:
    client = FakeIotClient()
    sink = _sink(client)
    assert sink.alerts_topic == "edge-security/thor-01/alerts"
    assert sink.health_topic == "edge-security/thor-01/health"

    with sink:
        sink.publish(_alert(1))
        sink.publish(_alert(2))
        sink.publish_health({"events_seen": 42})
        sink.flush(timeout=5)

    assert client.connects == 1 and client.disconnects == 1
    topics = [topic for topic, _, _ in client.published]
    assert topics == [sink.alerts_topic, sink.alerts_topic, sink.health_topic]
    assert all(qos == 1 for _, _, qos in client.published)
    assert client.published[0][1] == _alert(1).model_dump(mode="json")
    health = client.published[2][1]
    assert health["thing"] == "thor-01"
    assert health["events_seen"] == 42
    # Stats are captured when the health message is enqueued (a backlog snapshot).
    assert set(health["sink"]) >= {"published", "dropped", "failed", "retries", "pending", "connected"}
    assert health["sink"]["published"] + health["sink"]["pending"] >= 2
    assert sink.published == 3 and sink.failed == 0 and sink.dropped == 0


def test_iot_core_bounded_queue_drops_newest_and_counts() -> None:
    gate = threading.Event()
    client = FakeIotClient(hold=gate)
    sink = _sink(client, queue_size=3)
    sink.open()
    try:
        # The worker takes the first item and blocks on the gate; three more fit in the queue.
        sink.publish(_alert(0))
        deadline = time.monotonic() + 2
        while client.attempts < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        for i in range(1, 8):
            sink.publish(_alert(i))
        assert sink.dropped == 4
        assert sink.stats()["pending"] == 3
        gate.set()
        sink.flush(timeout=5)
    finally:
        sink.close()

    assert [body["title"] for _, body, _ in client.published] == [f"Test anomaly {i}" for i in range(4)]
    assert sink.published == 4
    assert sink.dropped == 4


def test_iot_core_retries_with_exponential_backoff_then_succeeds() -> None:
    delays: list[float] = []
    client = FakeIotClient(fail_publishes=3)
    sink = _sink(client, max_retries=5, backoff_base=0.5, backoff_max=30.0, sleep=delays.append)

    with sink:
        sink.publish(_alert(1))
        sink.flush(timeout=5)

    assert delays == [0.5, 1.0, 2.0]
    assert sink.retries == 3
    assert sink.published == 1 and sink.failed == 0
    assert len(client.published) == 1


def test_iot_core_backoff_is_capped_and_reconnects_after_failure() -> None:
    delays: list[float] = []
    client = FakeIotClient(fail_connects=2)
    sink = _sink(client, max_retries=5, backoff_base=1.0, backoff_max=1.5, sleep=delays.append)

    with sink:
        sink.publish(_alert(1))
        sink.flush(timeout=5)

    assert client.connects == 3  # two refused connects, then success
    assert delays == [1.0, 1.5]
    assert sink.published == 1


def test_iot_core_never_raises_into_the_caller() -> None:
    client = FakeIotClient(always_fail=True)
    sink = _sink(client, max_retries=2)

    with sink:
        for i in range(3):
            sink.publish(_alert(i))
        sink.publish_health({})
        sink.flush(timeout=5)
    sink.close()  # idempotent

    assert sink.failed == 4
    assert sink.published == 0
    assert sink.retries == 8
    assert sink.last_error is not None
    assert sink.stats()["connected"] is False


def test_iot_core_open_surfaces_factory_errors() -> None:
    def broken(settings: IotCoreSettings) -> Any:
        raise ImportError("no sdk")

    sink = IotCoreAlertSink(_SETTINGS, client_factory=broken)
    with pytest.raises(ImportError):
        sink.open()
    with pytest.raises(ValueError):
        IotCoreAlertSink(_SETTINGS, queue_size=0)


def test_iot_core_default_factory_requires_sdk_lazily() -> None:
    import sys

    from jetson_edge_ai_security.sinks.iot_core import aws_iot_client_factory

    if "awsiot" in sys.modules:  # pragma: no cover - only when the extra is installed
        pytest.skip("awsiotsdk installed; lazy-import failure path not applicable")
    with pytest.raises(ImportError, match="cloud"):
        aws_iot_client_factory(_SETTINGS)


# ----------------------------------------------------------------------------
# Config-driven construction
# ----------------------------------------------------------------------------


def test_default_config_has_all_sinks_disabled() -> None:
    config = load_config(Path(__file__).parent.parent / "configs" / "default.yaml")
    assert config.sinks.jsonl.enabled is False
    assert config.sinks.sqlite.enabled is False
    assert config.sinks.iot_core.enabled is False
    assert config.sinks.iot_core.qos == 1
    assert build_sinks(config.sinks) == []


def test_build_sinks_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ENDPOINT", "THING", "CERT", "KEY", "CA"):
        monkeypatch.delenv(f"EDGE_SECURITY_IOT_{name}", raising=False)
    config = AppConfig.model_validate(
        {
            "sinks": {
                "jsonl": {"enabled": True, "path": str(tmp_path / "a.jsonl")},
                "sqlite": {"enabled": True, "db_path": str(tmp_path / "a.db")},
                "iot_core": {
                    "enabled": True,
                    "endpoint": "x-ats.iot.eu-west-1.amazonaws.com",
                    "thing_name": "thor-02",
                    "cert_path": str(tmp_path / "c.pem"),
                    "key_path": str(tmp_path / "k.pem"),
                    "topic_root": "fleet",
                    "queue_size": 7,
                    "max_retries": 2,
                },
            }
        }
    )
    client = FakeIotClient()
    sinks = build_sinks(config.sinks, iot_client_factory=lambda settings: client)

    assert [type(s) for s in sinks] == [JsonlAlertSink, SqliteAlertSink, IotCoreAlertSink]
    iot = sinks[2]
    assert isinstance(iot, IotCoreAlertSink)
    assert iot.alerts_topic == "fleet/thor-02/alerts"
    assert iot.settings.ca_path is None
    assert iot.max_retries == 2
    assert iot._queue.maxsize == 7


def test_iot_core_settings_fall_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGE_SECURITY_IOT_ENDPOINT", "env-ats.iot.us-west-2.amazonaws.com")
    monkeypatch.setenv("EDGE_SECURITY_IOT_THING", "env-thing")
    monkeypatch.setenv("EDGE_SECURITY_IOT_CERT", "/etc/edge/cert.pem")
    monkeypatch.setenv("EDGE_SECURITY_IOT_KEY", "/etc/edge/key.pem")
    monkeypatch.setenv("EDGE_SECURITY_IOT_CA", "/etc/edge/ca.pem")
    config = AppConfig.model_validate({"sinks": {"iot_core": {"enabled": True, "thing_name": "config-wins"}}})

    settings = resolve_iot_core_settings(config.sinks.iot_core)
    assert settings.endpoint == "env-ats.iot.us-west-2.amazonaws.com"
    assert settings.thing_name == "config-wins"
    assert settings.ca_path == "/etc/edge/ca.pem"
    assert settings.effective_client_id == "config-wins"

    monkeypatch.delenv("EDGE_SECURITY_IOT_KEY")
    with pytest.raises(ValueError, match="EDGE_SECURITY_IOT_KEY"):
        resolve_iot_core_settings(config.sinks.iot_core)


# ----------------------------------------------------------------------------
# Pipeline integration
# ----------------------------------------------------------------------------


def _labelled_csv(tmp_path: Path, rows: int = 20) -> Path:
    path = tmp_path / "events.csv"
    lines = ["timestamp,source_ip,dest_ip,source_port,dest_port,protocol,packet_size,attack_label"]
    for i in range(rows):
        lines.append(f"2026-01-01 00:00:{i:02d},10.0.0.{i + 1},10.0.1.1,{1000 + i},443,TCP,100,1")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_pipeline_delivers_alerts_to_sinks_and_survives_sink_failures(tmp_path: Path) -> None:
    good = RecordingSink()
    bad = RecordingSink(fail_on_publish=True)
    jsonl_path = tmp_path / "out" / "alerts.jsonl"
    source = CsvReplaySource(_labelled_csv(tmp_path))
    detector = BaselineDetector(BaselineThresholds(packet_count_threshold=5, attack_count_threshold=1))

    with source:
        runner = PipelineRunner(
            source,
            window_size=5,
            step=5,
            detector=detector,
            sinks=[good, bad, JsonlAlertSink(jsonl_path)],
            health_interval_windows=2,
        )
        alerts = runner.run()

    assert len(alerts) == 4
    assert good.alerts == alerts
    assert good.opened == 1 and good.closed == 1
    assert bad.opened == 1 and bad.closed == 1
    assert runner.sink_errors == 4
    assert len(jsonl_path.read_text(encoding="utf-8").splitlines()) == 4
    # Health every 2 windows (4 windows -> 2) plus the final snapshot.
    assert len(good.health) == 3
    assert good.health[-1]["final"] is True
    assert good.health[-1]["alerts_emitted"] == 4
    assert good.health[-1]["source"] == "csv-replay"


def test_pipeline_closes_sinks_when_stream_stops_early(tmp_path: Path) -> None:
    sink = RecordingSink()
    source = CsvReplaySource(_labelled_csv(tmp_path))
    detector = BaselineDetector(BaselineThresholds(packet_count_threshold=5, attack_count_threshold=1))
    with source:
        runner = PipelineRunner(source, window_size=5, step=1, detector=detector, sinks=[sink])
        alerts = list(runner.stream_alerts(max_alerts=1))
    assert len(alerts) == 1 and sink.alerts == alerts
    assert sink.closed == 1
    assert sink.health[-1]["final"] is True


def test_pipeline_with_iot_core_fake_client_end_to_end(tmp_path: Path) -> None:
    client = FakeIotClient()
    sink = _sink(client)
    source = CsvReplaySource(_labelled_csv(tmp_path))
    detector = BaselineDetector(BaselineThresholds(packet_count_threshold=5, attack_count_threshold=1))
    with source:
        runner = PipelineRunner(source, window_size=5, step=5, detector=detector, sinks=[sink])
        alerts = runner.run()

    assert len(alerts) == 4
    alert_msgs = [body for topic, body, _ in client.published if topic.endswith("/alerts")]
    health_msgs = [body for topic, body, _ in client.published if topic.endswith("/health")]
    assert [Alert.model_validate(body) for body in alert_msgs] == alerts
    assert len(health_msgs) == 1 and health_msgs[0]["final"] is True
    assert client.disconnects == 1


def test_cli_replay_csv_uses_configured_jsonl_sink(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jetson_edge_ai_security.cli import app

    sink_path = tmp_path / "sink" / "alerts.jsonl"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "runtime:\n  window_size: 5\n  step: 5\n"
        "detector:\n  packet_count_threshold: 5\n  attack_count_threshold: 1\n"
        f"sinks:\n  jsonl:\n    enabled: true\n    path: {sink_path}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["replay-csv", "--path", str(_labelled_csv(tmp_path)), "--config", str(config_path), "--json-output"]
    )
    assert result.exit_code == 0, result.output
    assert len(sink_path.read_text(encoding="utf-8").splitlines()) == 4
