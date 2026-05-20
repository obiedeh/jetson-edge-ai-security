from pathlib import Path

from jetson_edge_ai_security.detection import BaselineDetector, BaselineThresholds
from jetson_edge_ai_security.runtime import PipelineRunner
from jetson_edge_ai_security.sources import CsvReplaySource


def test_pipeline_smoke_emits_alert_from_labeled_replay(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "timestamp,source_ip,dest_ip,source_port,dest_port,protocol,packet_size,attack_label\n"
        "2026-01-01 00:00:00,10.0.0.1,10.0.0.2,1000,443,TCP,100,0\n"
        "2026-01-01 00:00:01,10.0.0.2,10.0.0.2,1001,443,TCP,120,1\n"
        "2026-01-01 00:00:02,10.0.0.3,10.0.0.2,1002,443,TCP,140,0\n",
        encoding="utf-8",
    )
    source = CsvReplaySource(path)
    detector = BaselineDetector(BaselineThresholds(packet_count_threshold=10, attack_count_threshold=1))

    with source:
        runner = PipelineRunner(source, window_size=3, step=1, detector=detector)
        alerts = runner.run()

    assert len(alerts) == 1
    assert alerts[0].severity == "medium"
    assert runner.metrics.events_seen == 3
    assert runner.metrics.windows_seen == 1


def test_pipeline_stream_alerts_respects_max_alerts(tmp_path: Path) -> None:
    """stream_alerts(max_alerts=1) must stop after emitting the first alert."""
    path = tmp_path / "events.csv"
    rows = ["timestamp,source_ip,dest_ip,source_port,dest_port,protocol,packet_size,attack_label"]
    for i in range(20):
        rows.append(
            f"2026-01-01 00:00:{i:02d},10.0.0.{i + 1},10.0.1.1,{1000 + i},443,TCP,100,1"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    source = CsvReplaySource(path)
    detector = BaselineDetector(BaselineThresholds(packet_count_threshold=5, attack_count_threshold=1))

    with source:
        runner = PipelineRunner(source, window_size=5, step=1, detector=detector)
        alerts = list(runner.stream_alerts(max_alerts=1))

    assert len(alerts) == 1
    assert runner.metrics.alerts_emitted == 1


def test_pipeline_metrics_finished_after_run(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "timestamp,source_ip,dest_ip,protocol,packet_size\n"
        "2026-01-01 00:00:00,10.0.0.1,10.0.0.2,TCP,100\n",
        encoding="utf-8",
    )
    source = CsvReplaySource(path)
    with source:
        runner = PipelineRunner(source, window_size=5, step=1)
        runner.run()

    assert runner.metrics.finished_at is not None
    assert runner.metrics.duration_seconds >= 0.0

