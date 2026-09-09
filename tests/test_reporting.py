"""Tests for write_replay_artifacts evidence generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jetson_edge_ai_security.runtime.metrics import RuntimeMetrics
from jetson_edge_ai_security.runtime.reporting import (
    write_replay_artifacts,
    write_static_report_pages,
)
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


def test_write_static_report_pages_creates_landing_and_dashboard(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    demo_dir = reports_dir / "demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "runtime_metrics.json").write_text(
        json.dumps(
            {
                "events_seen": 12,
                "windows_seen": 8,
                "detections_seen": 4,
                "alerts_emitted": 4,
                "rows_skipped": 0,
                "alert_severity_counts": {"high": 2, "medium": 2},
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "training_run.json").write_text(
        json.dumps(
            {
                "detector": {
                    "evaluation": {"gbc_auc": 0.9796, "if_auc": 0.6433},
                    "gate": {"result": "PASS"},
                    "onnx_export": {"path": "models/exports/gbm_detector.onnx"},
                },
                "forecaster": {
                    "evaluation": {"ridge_mae": 7.49, "lag1_mae": 10.24},
                    "gate": {"result": "PASS"},
                    "onnx_export": {"path": "models/exports/ar_forecaster.onnx"},
                },
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "thor_benchmark.json").write_text(
        json.dumps(
            {
                "source_badge": "pending-thor-run",
                "gates": {
                    "detector_p95_latency_ms": {"status": "pending"},
                    "forecaster_p95_latency_ms": {"status": "pending"},
                    "throughput_at_1000_rps": {"status": "pending"},
                    "memory_footprint_gb": {"status": "pending"},
                },
            }
        ),
        encoding="utf-8",
    )

    paths = write_static_report_pages(reports_dir=reports_dir)

    assert {path.name for path in paths} == {
        "index.html",
        "dashboard.html",
        "tech-brief.html",
        "business-case.html",
    }
    index = (reports_dir / "index.html").read_text(encoding="utf-8")
    dashboard = (reports_dir / "dashboard.html").read_text(encoding="utf-8")
    tech_brief = (reports_dir / "tech-brief.html").read_text(encoding="utf-8")
    business_case = (reports_dir / "business-case.html").read_text(encoding="utf-8")
    assert "Jetson Edge Intrusion Detection" in index
    assert "Jetson Edge Intrusion Detection Dashboard" in dashboard
    assert "Operational Decision Summary" in dashboard
    assert "Current Working System" in dashboard
    assert "Planned Jetson Ingestion Upgrade" in dashboard
    assert "fixed_csv" in dashboard
    assert "Jetson-generated flow CSV" in index
    assert "Evidence vs Boundary" in dashboard
    assert "No offensive malware generation" in index
    assert "No live production IDS deployment claim" in dashboard
    assert "No line-rate capture claim" in dashboard
    assert "pending-thor-run" in dashboard
    assert "Adapters may change" in tech_brief
    assert "does not replace a SIEM" in business_case


def test_static_pages_render_measured_thor_benchmark(tmp_path: Path) -> None:
    """A measured artifact must surface values and never the pending wording."""
    reports_dir = tmp_path / "reports"
    (reports_dir / "demo").mkdir(parents=True)
    (reports_dir / "demo" / "runtime_metrics.json").write_text(
        json.dumps({"events_seen": 12, "windows_seen": 8, "alerts_emitted": 4}), encoding="utf-8"
    )
    (reports_dir / "training_run.json").write_text("{}", encoding="utf-8")
    tier = {
        "target_rps": 1000.0, "actual_rps": 1000.1, "p50_ms": 0.021, "p95_ms": 0.024,
        "p99_ms": 0.026, "provider": "CPUExecutionProvider",
        "tegrastats": {"rails_mw": {"VIN": {"p50": 53252, "peak": 54118}}, "temps_c": {"tj": {"peak": 49.4}}},
    }
    (reports_dir / "thor_benchmark.json").write_text(
        json.dumps(
            {
                "run_id": "abc123",
                "source_badge": "validated-thor-benchmark",
                "duration_per_tier_s": 300,
                "hardware": {"host": "jetsonthor", "soc": "tegra264", "l4t_release": "R38", "nvpmodel": "120W", "onnxruntime": "1.29.0", "python": "3.12.3"},
                "models": [
                    {"model": "detector", "provider": "CPUExecutionProvider", "provider_error": "Fail: CUDA no kernel image", "tiers": [tier]},
                    {"model": "forecaster", "provider": "CPUExecutionProvider", "tiers": [dict(tier, p95_ms=0.038)]},
                ],
                "memory": {"process_peak_rss_gb": 0.34},
                "idle_baseline": {"before_load": {"rails_mw": {"VIN": {"p50": 24222}}}},
                "gates": {
                    "detector_p95_latency_ms": {"threshold": 10, "unit": "ms", "measured": 0.024, "status": "pass"},
                    "forecaster_p95_latency_ms": {"threshold": 50, "unit": "ms", "measured": 0.038, "status": "pass"},
                    "throughput_at_1000_rps": {"threshold": 1000, "unit": "events/s", "measured": 1000.1, "status": "pass"},
                    "memory_footprint_gb": {"threshold": 4, "unit": "GB", "measured": 0.34, "status": "pass"},
                },
            }
        ),
        encoding="utf-8",
    )

    write_static_report_pages(reports_dir=reports_dir)
    dashboard = (reports_dir / "dashboard.html").read_text(encoding="utf-8")
    index = (reports_dir / "index.html").read_text(encoding="utf-8")
    business = (reports_dir / "business-case.html").read_text(encoding="utf-8")
    tech = (reports_dir / "tech-brief.html").read_text(encoding="utf-8")

    assert "Thor Measurement" in dashboard
    assert "0.024 ms" in dashboard and "0.34 GB" in dashboard
    assert "CUDA no kernel image" in dashboard
    assert "jetsonthor (tegra264)" in dashboard
    assert "24222 mW" in dashboard
    for page in (dashboard, index, business, tech):
        assert "pending measured" not in page.lower()
        assert "remain pending" not in page.lower()
    assert "inference only" in business
    assert "Measured run committed" in tech


def test_dashboard_renders_thread_pool_comparison_when_present(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "demo").mkdir(parents=True)
    (reports_dir / "demo" / "runtime_metrics.json").write_text("{}", encoding="utf-8")
    (reports_dir / "training_run.json").write_text("{}", encoding="utf-8")
    (reports_dir / "thor_benchmark.json").write_text(json.dumps({"source_badge": "pending-thor-run"}), encoding="utf-8")
    (reports_dir / "thor_benchmark_threads.json").write_text(
        json.dumps(
            {
                "baseline": {"run_id": "base1"},
                "variant": {"run_id": "var1"},
                "rows": [
                    {
                        "model": "detector", "target_rps": 1000.0,
                        "baseline": {"vin_p50_mw": 54102.0, "deadline_misses": 16944, "p95_ms": 0.0238, "tj_peak_c": 56.562},
                        "variant": {"vin_p50_mw": 24312.0, "deadline_misses": 0, "p95_ms": 0.0219, "tj_peak_c": 40.375},
                        "delta": {"vin_p50_mw": -29790.0, "deadline_misses": -16944},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    write_static_report_pages(reports_dir=reports_dir)
    dashboard = (reports_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "Thread Pool Comparison" in dashboard
    assert "base1" in dashboard and "var1" in dashboard
    assert "-29790" in dashboard
    assert "16944 / 0" in dashboard


def test_dashboard_omits_thread_pool_section_when_absent(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "demo").mkdir(parents=True)
    (reports_dir / "demo" / "runtime_metrics.json").write_text("{}", encoding="utf-8")
    write_static_report_pages(reports_dir=reports_dir)
    dashboard = (reports_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "Thread Pool Comparison" not in dashboard


def test_dashboard_renders_cross_device_comparison_when_host_runs_present(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "demo").mkdir(parents=True)
    (reports_dir / "demo" / "runtime_metrics.json").write_text("{}", encoding="utf-8")
    (reports_dir / "training_run.json").write_text("{}", encoding="utf-8")
    tier = {"target_rps": 1000.0, "p50_ms": 0.1, "p95_ms": 0.2, "p99_ms": 0.3, "actual_rps": 1000.0, "deadline_misses": 0, "process_rss_gb": 0.1, "provider": "CPUExecutionProvider"}
    payload = {"models": [{"model": "detector", "tiers": [tier]}]}
    for name in ("thor_benchmark.json", "bench/rtx5090_cpu.json", "bench/rtx5090_cpu_single_thread.json"):
        path = reports_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    write_static_report_pages(reports_dir=reports_dir)
    dashboard = (reports_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "Cross-device inference comparison" in dashboard
    assert "RTX 5090 host" in dashboard
