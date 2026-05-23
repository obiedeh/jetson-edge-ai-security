"""Evidence artifact generation for runtime replays."""

from __future__ import annotations

import json
from html import escape
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


def write_static_report_pages(
    *,
    reports_dir: Path = Path("reports"),
) -> list[Path]:
    """Write portfolio-style static landing, dashboard, tech brief, and business case pages."""

    reports_dir.mkdir(parents=True, exist_ok=True)
    demo_metrics = _read_json(reports_dir / "demo" / "runtime_metrics.json")
    training_run = _read_json(reports_dir / "training_run.json")
    thor_benchmark = _read_json(reports_dir / "thor_benchmark.json")

    index_path = reports_dir / "index.html"
    dashboard_path = reports_dir / "dashboard.html"
    tech_brief_path = reports_dir / "tech-brief.html"
    business_case_path = reports_dir / "business-case.html"

    index_path.write_text(
        _render_index_page(
            demo_metrics=demo_metrics,
            training_run=training_run,
            thor_benchmark=thor_benchmark,
        ),
        encoding="utf-8",
    )
    dashboard_path.write_text(
        _render_dashboard_page(
            demo_metrics=demo_metrics,
            training_run=training_run,
            thor_benchmark=thor_benchmark,
        ),
        encoding="utf-8",
    )
    tech_brief_path.write_text(
        _render_tech_brief_page(
            demo_metrics=demo_metrics,
            training_run=training_run,
            thor_benchmark=thor_benchmark,
        ),
        encoding="utf-8",
    )
    business_case_path.write_text(
        _render_business_case_page(
            demo_metrics=demo_metrics,
            training_run=training_run,
            thor_benchmark=thor_benchmark,
        ),
        encoding="utf-8",
    )
    return [index_path, dashboard_path, tech_brief_path, business_case_path]


def _severity_counts(alerts: list[Alert]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for alert in alerts:
        counts[alert.severity] = counts.get(alert.severity, 0) + 1
    return counts


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _value(data: dict[str, object], *keys: str, default: object = "not measured") -> object:
    current: object = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _metric(data: dict[str, object], *keys: str, default: str = "not measured") -> str:
    value = _value(data, *keys, default=default)
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _card(title: str, value: str, note: str = "", status: str = "neutral") -> str:
    note_html = f"<p>{escape(note)}</p>" if note else ""
    return (
        f'<article class="card {status}">'
        f"<span>{escape(title)}</span>"
        f"<strong>{escape(value)}</strong>"
        f"{note_html}</article>"
    )


def _link_card(title: str, href: str, text: str) -> str:
    return (
        '<article class="link-card">'
        f'<h3><a href="{escape(href)}">{escape(title)}</a></h3>'
        f"<p>{escape(text)}</p>"
        "</article>"
    )


def _page_shell(title: str, subtitle: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #121a2c;
      --panel-2: #17223a;
      --line: #293653;
      --text: #eef4ff;
      --muted: #9fb0ca;
      --accent: #38bdf8;
      --good: #22c55e;
      --warn: #f59e0b;
      --risk: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #13223d 0, var(--bg) 34rem);
      color: var(--text);
      font: 16px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 64px; }}
    header.hero {{ padding: 28px 0 18px; }}
    .eyebrow {{ color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 0.78rem; letter-spacing: 0.08em; }}
    h1 {{ margin: 8px 0 10px; font-size: clamp(2.1rem, 5vw, 4.5rem); line-height: 1.02; letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; font-size: 1.45rem; }}
    h3 {{ margin: 0 0 8px; }}
    p {{ color: var(--muted); margin: 0 0 12px; }}
    a {{ color: #7dd3fc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    section {{ margin-top: 28px; padding: 24px; background: rgba(18, 26, 44, 0.9); border: 1px solid var(--line); border-radius: 8px; }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
    .two {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
    .card, .link-card {{ background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-height: 120px; }}
    .card span {{ display: block; color: var(--muted); font-size: 0.9rem; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 1.55rem; line-height: 1.15; }}
    .card.good {{ border-color: rgba(34, 197, 94, 0.55); }}
    .card.warn {{ border-color: rgba(245, 158, 11, 0.65); }}
    .card.risk {{ border-color: rgba(239, 68, 68, 0.65); }}
    .pill {{ display: inline-block; padding: 4px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); font-size: 0.85rem; margin: 0 6px 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 8px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ color: var(--text); background: #0f1729; }}
    td {{ color: var(--muted); }}
    ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
    .callout {{ border-left: 4px solid var(--warn); padding-left: 14px; }}
    .footer {{ margin-top: 24px; color: var(--muted); font-size: 0.92rem; }}
  </style>
</head>
<body>
<main>
  <header class="hero">
    <div class="eyebrow">Jetson Edge AI Security</div>
    <h1>{escape(title)}</h1>
    <p>{escape(subtitle)}</p>
    <p>
      <a href="index.html">Landing</a> |
      <a href="dashboard.html">Dashboard</a> |
      <a href="tech-brief.html">Technical brief</a> |
      <a href="business-case.html">Business case</a> |
      <a href="../docs/architecture.md">Architecture</a> |
      <a href="../deploy/thor/operator-runbook.md">Thor runbook</a>
    </p>
  </header>
  {body}
  <p class="footer">Generated from committed defensive replay, model, and benchmark artifacts. No offensive tooling or autonomous response is claimed.</p>
</main>
</body>
</html>
"""


def _render_index_page(
    *,
    demo_metrics: dict[str, object],
    training_run: dict[str, object],
    thor_benchmark: dict[str, object],
) -> str:
    cards = "".join(
        [
            _card("Demo events replayed", _metric(demo_metrics, "events_seen"), "Built-in defensive replay", "good"),
            _card("Alerts emitted", _metric(demo_metrics, "alerts_emitted"), "Operator-review evidence", "warn"),
            _card("Detector AUC", _metric(training_run, "detector", "evaluation", "gbc_auc"), "GBM detector on fixture data", "good"),
            _card("Thor validation", _metric(thor_benchmark, "source_badge", default="pending-thor-run"), "Hardware benchmark pending until measured", "warn"),
        ]
    )
    body = f"""
<section>
  <h2>Executive Evidence Summary</h2>
  <div class="grid">{cards}</div>
</section>

<section>
  <h2>Problem</h2>
  <p>Edge security telemetry can arrive from CSV replay, packet captures, IDS logs, or future live sources. The engineering problem is normalizing those sources into one defensive runtime path without rewriting feature extraction, detection, alerting, or reporting.</p>
</section>

<section>
  <h2>What I Built</h2>
  <p>A pluggable edge-security telemetry runtime that normalizes defensive events, extracts sliding-window features, runs conservative detection, emits alerts, stores evidence artifacts, and provides a Jetson deployment path.</p>
  <div>
    <span class="pill">TrafficSource API</span>
    <span class="pill">TelemetryEvent schema</span>
    <span class="pill">CSV replay</span>
    <span class="pill">PCAP replay path</span>
    <span class="pill">GBM detector artifact</span>
    <span class="pill">AR forecaster artifact</span>
    <span class="pill">FastAPI + web dashboard</span>
  </div>
</section>

<section>
  <h2>Reviewer Path</h2>
  <div class="grid">
    {_link_card("Operator dashboard", "dashboard.html", "Runtime, model, alert, and Thor-readiness evidence in one reviewer-facing dashboard.")}
    {_link_card("Technical brief", "tech-brief.html", "Architecture, runtime pipeline, data contracts, model path, and deployment boundary.")}
    {_link_card("Business case", "business-case.html", "Why the project matters for edge AI operations, security review, and Jetson-class deployments.")}
    {_link_card("Replay report", "demo/replay_report.md", "Defensive replay summary with events, windows, alerts, and safety boundary.")}
  </div>
</section>

<section>
  <h2>Evidence vs Boundary</h2>
  <div class="two">
    <div>
      <h3>Evidence demonstrated</h3>
      <ul>
        <li>Defensive replay path</li>
        <li>Normalized telemetry events</li>
        <li>Sliding-window feature extraction</li>
        <li>Alert JSONL and runtime metrics</li>
        <li>Reference detector and forecaster artifacts</li>
        <li>Jetson AGX Thor deployment runbook</li>
      </ul>
    </div>
    <div>
      <h3>Boundary preserved</h3>
      <ul>
        <li>No offensive malware generation</li>
        <li>No autonomous attack execution</li>
        <li>No autonomous response action</li>
        <li>No live production IDS claim</li>
        <li>Thor latency remains pending until measured</li>
      </ul>
    </div>
  </div>
</section>
"""
    return _page_shell(
        "Edge Security Telemetry Evidence Pack",
        "Defensive replay, normalized telemetry, model evidence, alert artifacts, and Jetson deployment readiness.",
        body,
    )


def _render_dashboard_page(
    *,
    demo_metrics: dict[str, object],
    training_run: dict[str, object],
    thor_benchmark: dict[str, object],
) -> str:
    decision_cards = "".join(
        [
            _card("Primary runtime", "defensive telemetry replay", "CSV now; PCAP/IDS adapters remain integration paths", "neutral"),
            _card("Detector gate", _metric(training_run, "detector", "gate", "result"), "Threshold reported in training_run.json", "good"),
            _card("Forecaster gate", _metric(training_run, "forecaster", "gate", "result"), "MAE threshold reported in training_run.json", "good"),
            _card("Thor benchmark", _metric(thor_benchmark, "source_badge", default="pending-thor-run"), "No fabricated hardware latency", "warn"),
        ]
    )
    severity = _value(demo_metrics, "alert_severity_counts", default={})
    severity_rows = ""
    if isinstance(severity, dict) and severity:
        for key, value in sorted(severity.items()):
            severity_rows += f"<tr><td>{escape(str(key))}</td><td>{escape(str(value))}</td></tr>"
    else:
        severity_rows = "<tr><td>none</td><td>0</td></tr>"

    body = f"""
<section>
  <h2>Operational Decision Summary</h2>
  <div class="grid">{decision_cards}</div>
</section>

<section>
  <h2>Problem → Build → Evidence → Next Validation</h2>
  <div class="two">
    <div><h3>Problem</h3><p>Edge IDS telemetry arrives from heterogeneous defensive sources, but operator workflows need one normalized evidence path.</p></div>
    <div><h3>What I Built</h3><p>A source-agnostic runtime that converts telemetry into events, windows, detections, alerts, metrics, and reviewer artifacts.</p></div>
    <div><h3>What I Found</h3><p>The committed demo emits {_metric(demo_metrics, "alerts_emitted")} alerts from {_metric(demo_metrics, "windows_seen")} feature windows, and model gates are recorded in training evidence.</p></div>
    <div><h3>What I Would Validate Next</h3><p>Run the Thor benchmark on actual hardware, connect measured IDS logs, and keep all response actions human-reviewed.</p></div>
  </div>
</section>

<section>
  <h2>Runtime Evidence</h2>
  <table>
    <tr><th>Metric</th><th>Value</th><th>Source</th></tr>
    <tr><td>Events seen</td><td>{escape(_metric(demo_metrics, "events_seen"))}</td><td>reports/demo/runtime_metrics.json</td></tr>
    <tr><td>Feature windows</td><td>{escape(_metric(demo_metrics, "windows_seen"))}</td><td>reports/demo/runtime_metrics.json</td></tr>
    <tr><td>Detections seen</td><td>{escape(_metric(demo_metrics, "detections_seen"))}</td><td>reports/demo/runtime_metrics.json</td></tr>
    <tr><td>Alerts emitted</td><td>{escape(_metric(demo_metrics, "alerts_emitted"))}</td><td>reports/demo/runtime_metrics.json</td></tr>
    <tr><td>Rows skipped</td><td>{escape(_metric(demo_metrics, "rows_skipped"))}</td><td>reports/demo/runtime_metrics.json</td></tr>
  </table>
</section>

<section>
  <h2>Alert Severity Distribution</h2>
  <table>
    <tr><th>Severity</th><th>Count</th></tr>
    {severity_rows}
  </table>
</section>

<section>
  <h2>Model Evidence</h2>
  <table>
    <tr><th>Layer</th><th>Evidence</th><th>Status</th></tr>
    <tr><td>Detector</td><td>GBM AUC {_metric(training_run, "detector", "evaluation", "gbc_auc")} vs IsolationForest AUC {_metric(training_run, "detector", "evaluation", "if_auc")}</td><td>{_metric(training_run, "detector", "gate", "result")}</td></tr>
    <tr><td>Forecaster</td><td>Ridge MAE {_metric(training_run, "forecaster", "evaluation", "ridge_mae")} vs lag baseline {_metric(training_run, "forecaster", "evaluation", "lag1_mae")}</td><td>{_metric(training_run, "forecaster", "gate", "result")}</td></tr>
    <tr><td>ONNX exports</td><td>{_metric(training_run, "detector", "onnx_export", "path")} and {_metric(training_run, "forecaster", "onnx_export", "path")}</td><td>exported</td></tr>
  </table>
</section>

<section>
  <h2>Jetson / Thor Readiness</h2>
  <p class="callout">Thor benchmark values remain pending until `deploy/thor/run_benchmark.py` is executed on real hardware. This dashboard does not fabricate edge latency.</p>
  <table>
    <tr><th>Gate</th><th>Threshold</th><th>Status</th></tr>
    <tr><td>Detector p95 latency</td><td>10 ms</td><td>{_metric(thor_benchmark, "gates", "detector_p95_latency_ms", "status")}</td></tr>
    <tr><td>Forecaster p95 latency</td><td>50 ms</td><td>{_metric(thor_benchmark, "gates", "forecaster_p95_latency_ms", "status")}</td></tr>
    <tr><td>Throughput at 1000 RPS</td><td>1000 ev/s</td><td>{_metric(thor_benchmark, "gates", "throughput_at_1000_rps", "status")}</td></tr>
    <tr><td>Memory footprint</td><td>4 GB</td><td>{_metric(thor_benchmark, "gates", "memory_footprint_gb", "status")}</td></tr>
  </table>
</section>

<section>
  <h2>Evidence vs Boundary</h2>
  <div class="two">
    <div>
      <h3>Evidence demonstrated</h3>
      <ul>
        <li>TrafficSource abstraction and normalized telemetry events</li>
        <li>Defensive replay metrics and alert artifacts</li>
        <li>Reference detector and forecaster training evidence</li>
        <li>FastAPI/web dashboard integration path</li>
        <li>Thor runbook and benchmark template</li>
      </ul>
    </div>
    <div>
      <h3>Boundary preserved</h3>
      <ul>
        <li>No offensive tooling</li>
        <li>No malware generation</li>
        <li>No autonomous attack execution</li>
        <li>No autonomous response action</li>
        <li>No live production IDS deployment claim</li>
      </ul>
    </div>
  </div>
</section>
"""
    return _page_shell(
        "Jetson Edge AI Security Dashboard",
        "Operator-facing defensive telemetry runtime evidence for replay, detection, alerts, and Jetson readiness.",
        body,
    )


def _render_tech_brief_page(
    *,
    demo_metrics: dict[str, object],
    training_run: dict[str, object],
    thor_benchmark: dict[str, object],
) -> str:
    body = f"""
<section>
  <h2>Technical Brief</h2>
  <p>This project implements a defensive edge-security telemetry runtime for Jetson-class deployment paths. The system is intentionally source-agnostic: every source adapter normalizes telemetry into a shared event contract before feature extraction, detection, alerting, storage, and reporting.</p>
</section>

<section>
  <h2>Architecture</h2>
  <table>
    <tr><th>Layer</th><th>Role</th><th>Current state</th></tr>
    <tr><td>Source adapters</td><td>Convert CSV, PCAP, or future IDS logs into defensive telemetry streams.</td><td>CSV replay implemented; PCAP path tested; Zeek/Suricata/MQTT planned.</td></tr>
    <tr><td>Schema layer</td><td>Normalize raw fields into TelemetryEvent and Alert contracts.</td><td>Pydantic schemas implemented and tested.</td></tr>
    <tr><td>Feature pipeline</td><td>Build sliding-window features for baseline detection and future ML models.</td><td>Window extraction implemented and tested.</td></tr>
    <tr><td>Detection layer</td><td>Emit conservative alerts from baseline rules and optional model paths.</td><td>Baseline detector implemented; reference model evidence committed.</td></tr>
    <tr><td>Reporting layer</td><td>Write metrics, alerts JSONL, Markdown reports, and static dashboards.</td><td>Generated through CLI and Makefile targets.</td></tr>
    <tr><td>Jetson deployment layer</td><td>Package service, dashboard, TensorRT engines, and benchmark path for Thor.</td><td>Runbook and benchmark template present; measured hardware run pending.</td></tr>
  </table>
</section>

<section>
  <h2>Evidence Snapshot</h2>
  <div class="grid">
    {_card("Events replayed", _metric(demo_metrics, "events_seen"), "reports/demo/runtime_metrics.json", "good")}
    {_card("Alerts emitted", _metric(demo_metrics, "alerts_emitted"), "alerts.jsonl evidence", "warn")}
    {_card("Detector gate", _metric(training_run, "detector", "gate", "result"), "training_run.json", "good")}
    {_card("Thor benchmark", _metric(thor_benchmark, "source_badge", default="pending-thor-run"), "hardware values pending", "warn")}
  </div>
</section>

<section>
  <h2>Reproducibility</h2>
  <table>
    <tr><th>Task</th><th>Command</th></tr>
    <tr><td>Install development environment</td><td><code>make install-dev</code></td></tr>
    <tr><td>Run tests</td><td><code>make test</code></td></tr>
    <tr><td>Generate demo report</td><td><code>make demo-report</code></td></tr>
    <tr><td>Build static reports</td><td><code>make static-reports</code></td></tr>
    <tr><td>Verify full artifact path</td><td><code>make verify</code></td></tr>
  </table>
</section>

<section>
  <h2>Scope Boundary</h2>
  <p class="callout">This is defensive replay and edge-runtime evidence. It does not generate malware, execute exploitation, perform autonomous response, or claim measured Jetson AGX Thor latency until hardware benchmark artifacts are committed.</p>
</section>
"""
    return _page_shell(
        "Technical Brief",
        "Architecture, runtime flow, evidence path, reproducibility, and Jetson deployment boundary.",
        body,
    )


def _render_business_case_page(
    *,
    demo_metrics: dict[str, object],
    training_run: dict[str, object],
    thor_benchmark: dict[str, object],
) -> str:
    body = f"""
<section>
  <h2>Business Case</h2>
  <p>Industrial edge systems, robotics cells, and private-network sites increasingly generate security telemetry close to the physical environment. Sending every signal to a central platform can add latency, bandwidth cost, and operational blind spots. This project shows how defensive telemetry can be normalized and reviewed at the edge before heavier model runners or central security systems are introduced.</p>
</section>

<section>
  <h2>Who This Helps</h2>
  <div class="grid">
    {_card("Edge AI teams", "runtime proof", "Reproducible CLI, reports, and dashboard artifacts", "good")}
    {_card("Security operators", "reviewable alerts", "Alert JSONL, replay reports, and safety boundary", "warn")}
    {_card("Robotics / OT teams", "local telemetry", "Designed for constrained edge nodes and human review", "neutral")}
    {_card("AI infrastructure teams", "deployment path", "FastAPI, systemd, SQLite, TensorRT plan, Thor runbook", "neutral")}
  </div>
</section>

<section>
  <h2>Operational Value</h2>
  <table>
    <tr><th>Operational problem</th><th>Project response</th><th>Evidence</th></tr>
    <tr><td>Telemetry formats vary across sources.</td><td>Normalize every source into a shared event schema.</td><td>TrafficSource API and Pydantic schemas.</td></tr>
    <tr><td>Operators need evidence, not black-box claims.</td><td>Generate runtime metrics, alert JSONL, reports, and dashboards.</td><td>{_metric(demo_metrics, "events_seen")} events and {_metric(demo_metrics, "alerts_emitted")} alerts in committed demo evidence.</td></tr>
    <tr><td>Edge deployments need small, inspectable runtimes.</td><td>Use conservative baseline detection first, with model paths introduced behind evidence gates.</td><td>Detector gate: {_metric(training_run, "detector", "gate", "result")}.</td></tr>
    <tr><td>Hardware claims must be measured.</td><td>Keep Thor latency pending until real benchmark output exists.</td><td>{_metric(thor_benchmark, "source_badge", default="pending-thor-run")}.</td></tr>
  </table>
</section>

<section>
  <h2>Why It Matters for the Portfolio</h2>
  <p>This repo supports the Physical AI and Edge AI portfolio by showing runtime security, telemetry normalization, operational evidence, and Jetson deployment thinking. It is not a malware project and not an offensive security toolkit. It is a defensive edge observability and evidence-generation system.</p>
</section>

<section>
  <h2>Next Validation Milestones</h2>
  <ul>
    <li>Run the Thor benchmark on actual Jetson AGX Thor hardware.</li>
    <li>Replay a documented public defensive dataset and commit the artifact bundle.</li>
    <li>Add dashboard screenshot or short GIF for recruiter-fast comprehension.</li>
    <li>Connect measured IDS logs while keeping response actions human-reviewed.</li>
  </ul>
</section>
"""
    return _page_shell(
        "Business Case",
        "Why defensive edge telemetry, alert evidence, and Jetson readiness matter for operational AI systems.",
        body,
    )


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
