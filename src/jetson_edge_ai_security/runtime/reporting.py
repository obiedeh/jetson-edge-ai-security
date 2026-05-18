"""Evidence artifact generation for runtime replays."""

from __future__ import annotations

import json
from pathlib import Path

from jetson_edge_ai_security.runtime.metrics import RuntimeMetrics
from jetson_edge_ai_security.schemas import Alert


def write_replay_artifacts(
    *,
    output_dir: Path,
    alerts: list[Alert],
    metrics: RuntimeMetrics,
    source_name: str,
    rows_skipped: int,
) -> list[Path]:
    """Write replay metrics, alert JSONL, and a concise Markdown report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "runtime_metrics.json"
    alerts_path = output_dir / "alerts.jsonl"
    report_path = output_dir / "replay_report.md"

    metrics_payload = {
        **metrics.model_dump(mode="json"),
        "source": source_name,
        "rows_skipped": rows_skipped,
        "alert_severity_counts": _severity_counts(alerts),
        "safety_boundary": (
            "defensive replay evidence only; no offensive tooling or autonomous response"
        ),
    }
    metrics_path.write_text(
        json.dumps(metrics_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    alerts_path.write_text(
        "".join(json.dumps(alert.model_dump(mode="json"), sort_keys=True) + "\n" for alert in alerts),
        encoding="utf-8",
    )
    report_path.write_text(
        _render_replay_report(
            alerts=alerts,
            metrics=metrics,
            source_name=source_name,
            rows_skipped=rows_skipped,
        ),
        encoding="utf-8",
    )
    return [metrics_path, alerts_path, report_path]


def _severity_counts(alerts: list[Alert]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for alert in alerts:
        counts[alert.severity] = counts.get(alert.severity, 0) + 1
    return counts


def _render_replay_report(
    *,
    alerts: list[Alert],
    metrics: RuntimeMetrics,
    source_name: str,
    rows_skipped: int,
) -> str:
    severity_counts = _severity_counts(alerts)
    severity_lines = "\n".join(
        f"- {severity}: {count}" for severity, count in sorted(severity_counts.items())
    )
    if not severity_lines:
        severity_lines = "- none: 0"

    return f"""# Edge Security Replay Report

This report summarizes a defensive telemetry replay through the edge security runtime.

## Runtime Metrics

- Source: `{source_name}`
- Events seen: {metrics.events_seen}
- Feature windows: {metrics.windows_seen}
- Detections: {metrics.detections_seen}
- Alerts emitted: {metrics.alerts_emitted}
- Rows skipped: {rows_skipped}
- Duration seconds: {metrics.duration_seconds:.6f}

## Alert Severity Counts

{severity_lines}

## Safety Boundary

This is defensive replay evidence only. It does not generate malware, perform exploitation,
or execute autonomous response actions.
"""
