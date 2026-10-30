"""Tests for the Suricata EVE JSON source adapter."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jetson_edge_ai_security.cli import app
from jetson_edge_ai_security.schemas import TelemetryEvent
from jetson_edge_ai_security.sources import SuricataEveSource

FIXTURE = Path(__file__).parent / "fixtures" / "eve_sample.json"


def _fixture_records() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def test_fixture_has_expected_shape() -> None:
    records = _fixture_records()
    types = [record["event_type"] for record in records]
    assert len(records) == 12
    assert types.count("flow") == 4
    assert types.count("alert") == 3
    assert types.count("stats") == 1
    assert {"dns", "http", "fileinfo"} <= set(types)


def test_replay_emits_supported_types_and_counts_skipped() -> None:
    source = SuricataEveSource(FIXTURE)
    with source:
        events = list(source.events())

    assert len(events) == 8
    assert all(isinstance(event, TelemetryEvent) for event in events)
    assert source.lines_seen == 12
    assert source.events_emitted == 8
    assert source.rows_skipped == 0
    assert source.events_skipped == {"dns": 2, "http": 1, "fileinfo": 1}
    assert [event.metadata["event_type"] for event in events] == [
        "flow", "alert", "flow", "stats", "alert", "flow", "alert", "flow",
    ]


def test_flow_record_mapping() -> None:
    events = list(SuricataEveSource(FIXTURE, event_types={"flow"}).events())
    first = events[0]

    assert first.timestamp.isoformat() == "2026-09-28T10:15:03.123456+00:00"
    assert first.source_ip == "192.168.10.24"
    assert first.dest_ip == "192.168.10.5"
    assert first.source_port == 49212
    assert first.dest_port == 1883
    assert first.protocol == "TCP"
    assert first.flow_id == "1874250984763215"
    assert first.packet_size == 1836 + 1210
    assert first.tcp_flags == "1b"
    assert first.attack_label is None
    assert first.source_type == "suricata-eve"
    assert first.metadata["raw_source"] == "suricata-eve"
    assert first.metadata["app_proto"] == "mqtt"
    assert first.metadata["flow"]["packets"] == 22
    assert first.metadata["flow"]["state"] == "closed"

    icmp = next(event for event in events if event.protocol == "ICMP")
    assert icmp.source_port == 0
    assert icmp.packet_size == 784


def test_alert_record_mapping() -> None:
    events = list(SuricataEveSource(FIXTURE, event_types={"alert"}).events())
    assert len(events) == 3
    modbus = events[0]

    assert modbus.attack_label is True
    assert modbus.attack_type == "Attempted Information Leak"
    assert modbus.dest_port == 502
    assert modbus.packet_size == 624 + 396
    assert modbus.metadata["alert"]["signature"] == "ET SCAN Modbus Function Code Scan"
    assert modbus.metadata["alert"]["signature_id"] == 2027381
    assert modbus.metadata["alert"]["severity"] == 2
    assert modbus.metadata["alert"]["action"] == "allowed"
    assert modbus.metadata["app_proto"] == "modbus"


def test_stats_record_mapping() -> None:
    events = list(SuricataEveSource(FIXTURE, event_types={"stats"}).events())
    assert len(events) == 1
    stats = events[0]

    assert stats.source_ip == ""
    assert stats.protocol == "UNKNOWN"
    assert stats.packet_size is None
    assert stats.metadata["stats"]["capture_kernel_packets"] == 1048576
    assert stats.metadata["stats"]["capture_kernel_drops"] == 0
    assert stats.metadata["stats"]["decoder_bytes"] == 734003200
    assert stats.metadata["stats"]["detect_alert"] == 37
    assert stats.metadata["stats"]["uptime"] == 3600


def test_unsupported_event_type_filter_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported EVE event types"):
        SuricataEveSource(FIXTURE, event_types={"flow", "dns"})


def test_limit_stops_after_n_events() -> None:
    source = SuricataEveSource(FIXTURE, limit=3)
    events = list(source.events())
    assert len(events) == 3
    assert source.events_emitted == 3


def test_malformed_lines_are_counted_or_raised(tmp_path: Path) -> None:
    path = tmp_path / "eve.json"
    good = FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(
        "\n".join(
            [
                "{not json",
                '["a", "list"]',
                '{"event_type": "alert", "timestamp": "2026-09-28T10:15:05+0000"}',
                '{"event_type": "flow", "timestamp": "2026-09-28T10:15:05+0000", "src_port": 70000}',
                "",
                good,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    lenient = SuricataEveSource(path)
    events = list(lenient.events())
    assert len(events) == 1
    assert lenient.rows_skipped == 4
    assert lenient.events_skipped == {}

    with pytest.raises(ValueError):
        list(SuricataEveSource(path, strict=True).events())


def test_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        SuricataEveSource("/nonexistent/eve.json").open()


def test_follow_mode_picks_up_appended_lines(tmp_path: Path) -> None:
    path = tmp_path / "eve.json"
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n", encoding="utf-8")
    stop = threading.Event()
    source = SuricataEveSource(path, follow=True, poll_interval=0.02, stop_event=stop)

    def writer() -> None:
        with path.open("a", encoding="utf-8") as handle:
            for line in lines[1:]:
                time.sleep(0.01)
                # Write the line in two pieces so the reader sees a partial line.
                cut = len(line) // 2
                handle.write(line[:cut])
                handle.flush()
                time.sleep(0.005)
                handle.write(line[cut:] + "\n")
                handle.flush()
        time.sleep(0.1)
        stop.set()

    thread = threading.Thread(target=writer, daemon=True)
    collected: list[TelemetryEvent] = []
    with source:
        thread.start()
        for event in source.events():
            collected.append(event)
    thread.join(timeout=5)

    assert len(collected) == 8
    assert source.lines_seen == 12
    assert source.rows_skipped == 0
    assert source.events_skipped == {"dns": 2, "http": 1, "fileinfo": 1}


def test_follow_mode_idle_timeout_stops(tmp_path: Path) -> None:
    path = tmp_path / "eve.json"
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    source = SuricataEveSource(path, follow=True, poll_interval=0.01, idle_timeout=0.05)

    started = time.monotonic()
    events = list(source.events())
    elapsed = time.monotonic() - started

    assert len(events) == 8
    assert elapsed < 3.0


def test_follow_mode_handles_truncation(tmp_path: Path) -> None:
    path = tmp_path / "eve.json"
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n", encoding="utf-8")
    stop = threading.Event()
    source = SuricataEveSource(path, follow=True, poll_interval=0.02, stop_event=stop)

    def writer() -> None:
        time.sleep(0.1)
        path.write_text(lines[3] + "\n", encoding="utf-8")  # truncate + rewrite (an alert)
        time.sleep(0.2)
        stop.set()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    events = list(source.events())
    thread.join(timeout=5)

    assert [event.metadata["event_type"] for event in events] == ["flow", "alert"]


def test_cli_replay_eve_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    output_dir = tmp_path / "evidence"
    result = runner.invoke(
        app,
        ["replay-eve", "--path", str(FIXTURE), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "events=8" in result.output
    assert "skipped_types=" in result.output
    metrics = json.loads((output_dir / "runtime_metrics.json").read_text(encoding="utf-8"))
    assert metrics["events_seen"] == 8
    assert metrics["rows_skipped"] == 0
    assert (output_dir / "alerts.jsonl").exists()


def test_cli_replay_eve_json_output_and_limit() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["replay-eve", "--path", str(FIXTURE), "--limit", "2", "--json-output"])

    assert result.exit_code == 0, result.output


def test_cli_replay_eve_follow_with_idle_timeout(tmp_path: Path) -> None:
    path = tmp_path / "eve.json"
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["replay-eve", "--path", str(path), "--follow", "--idle-timeout", "0.1", "--json-output"],
    )

    assert result.exit_code == 0, result.output
    assert "events=8" in result.output
