"""Tests for write_replay_artifacts evidence generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jetson_edge_ai_security.runtime.metrics import RuntimeMetrics
from jetson_edge_ai_security.runtime.reporting import write_replay_artifacts
from jetson_edge_ai_security.schemas import Alert, FeatureWindow

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _fake_alert(severity: str = "medium") -> Alert:
    window = FeatureWindow(
        window_start=_TS,
        window_end=_TS,
        packet_count=10,
        mean_packet_size=100.0,
        max_packet_size=128,
    )
    return Alert(
        timestamp=_TS,
        severity=severity,  # type: ignore[arg-type]
        title="Test anomaly",
        description="Test description.",
        source="test",
        features=window.model_dump(mode="json"),
        recommended_action="Investigate.",
    )


def _metrics() -> RuntimeMetrics:
    m = RuntimeMetrics(started_at=_TS)
    m.events_seen = 12
    m.windows_seen = 8
    m.detections_seen = 4
    m.alerts_emitted = 4
    m.finished_at = _TS
    return m


def test_write_replay_artifacts_creates_all_three_files(tmp_path: Path) -> None:
    paths = write_replay_artifacts(
        output_dir=tmp_path / "out",
        alerts=[_fake_alert("high"), _fake_alert("medium")],
        metrics=_metrics(),
        source_name="test-source",
        rows_skipped=0,
    )

    names = {p.name for p in paths}
    assert names == {"runtime_metrics.json", "alerts.jsonl", "replay_report.md"}
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


def test_write_replay_artifacts_metrics_json_content(tmp_path: Path) -> None:
    write_replay_artifacts(
        output_dir=tmp_path,
        alerts=[_fake_alert("critical")],
        metrics=_metrics(),
        source_name="my-dataset",
        rows_skipped=3,
    )

    data = json.loads((tmp_path / "runtime_metrics.json").read_text(encoding="utf-8"))
    assert data["source"] == "my-dataset"
    assert data["rows_skipped"] == 3
    assert data["events_seen"] == 12
    assert data["alert_severity_counts"] == {"critical": 1}
    assert "safety_boundary" in data


def test_write_replay_artifacts_alerts_jsonl_one_line_per_alert(tmp_path: Path) -> None:
    alerts = [_fake_alert("low"), _fake_alert("high"), _fake_alert("critical")]
    write_replay_artifacts(
        output_dir=tmp_path,
        alerts=alerts,
        metrics=_metrics(),
        source_name="src",
        rows_skipped=0,
    )

    lines = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert obj["severity"] in ("low", "high", "critical")


def test_write_replay_artifacts_report_contains_metrics(tmp_path: Path) -> None:
    write_replay_artifacts(
        output_dir=tmp_path,
        alerts=[_fake_alert("medium")],
        metrics=_metrics(),
        source_name="evidence-source",
        rows_skipped=2,
    )

    report = (tmp_path / "replay_report.md").read_text(encoding="utf-8")
    assert "evidence-source" in report
    assert "Events seen: 12" in report
    assert "Rows skipped: 2" in report
    assert "Safety Boundary" in report


def test_write_replay_artifacts_no_alerts_shows_none(tmp_path: Path) -> None:
    write_replay_artifacts(
        output_dir=tmp_path,
        alerts=[],
        metrics=_metrics(),
        source_name="empty",
        rows_skipped=0,
    )

    data = json.loads((tmp_path / "runtime_metrics.json").read_text(encoding="utf-8"))
    assert data["alert_severity_counts"] == {}

    report = (tmp_path / "replay_report.md").read_text(encoding="utf-8")
    assert "none: 0" in report


def test_write_replay_artifacts_creates_output_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    assert not nested.exists()

    write_replay_artifacts(
        output_dir=nested,
        alerts=[],
        metrics=_metrics(),
        source_name="nested",
        rows_skipped=0,
    )

    assert nested.exists()
