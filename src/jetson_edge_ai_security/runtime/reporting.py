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
    """Write portfolio-style static HTML landing and dashboard pages."""

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
    tech_brief_path.write_text(_render_tech_brief_page(), encoding="utf-8")
    business_case_path.write_text(_render_business_case_page(), encoding="utf-8")
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
    <div class="eyebrow">Jetson Edge Intrusion Detection</div>
    <h1>{escape(title)}</h1>
    <p>{escape(subtitle)}</p>
    <p>
      <a href="dashboard.html">Open dashboard</a> |
      <a href="../README.md">README</a> |
      <a href="../docs/architecture.md">Architecture</a> |
      <a href="../deploy/thor/operator-runbook.md">Thor runbook</a>
    </p>
  </header>
  {body}
  <p class="footer">Generated from committed defensive replay, model, and benchmark artifacts. No offensive tooling, autonomous response, or production IDS deployment is claimed.</p>
</main>
</body>
</html>
"""


def _status_table(rows: list[tuple[str, str, str]]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{escape(layer)}</td>"
        f"<td>{escape(current)}</td>"
        f"<td>{escape(planned)}</td>"
        "</tr>"
        for layer, current, planned in rows
    )
    return (
        "<table>"
        "<tr><th>Layer</th><th>Current working system</th><th>Planned Jetson ingestion upgrade</th></tr>"
        f"{body}</table>"
    )


def _current_vs_planned_table() -> str:
    return _status_table(
        [
            ("Input source", "Fixed CSV fixture", "Jetson-generated flow CSV"),
            ("Capture mode", "Deterministic replay", "SPAN, TAP, or local interface capture"),
            ("Packet stage", "Not required for current evidence", "Rotating PCAP files"),
            (
                "Flow extraction",
                "CSV columns normalized into TelemetryEvent",
                "Zeek conn.log, Suricata eve.json, CICFlow-style records",
            ),
            (
                "Analytics path",
                "Lookback analytics, forecasting, alerts, reports",
                "Same existing analytics path",
            ),
            ("Dashboard impact", "Implemented", "No detector/dashboard rewrite intended"),
            ("Thor benchmark", "Template committed", "Pending measured Thor-class run"),
        ]
    )


def _planned_upgrade_table() -> str:
    rows = [
        ("Current input", "fixed CSV fixture", "implemented"),
        ("Next input", "Jetson-generated flow CSV", "planned"),
        ("Capture modes", "SPAN / TAP / local interface", "planned"),
        (
            "Flow extraction",
            "Zeek conn.log, Suricata eve.json, CICFlow-style records",
            "planned",
        ),
        ("Pipeline impact", "No detector/dashboard rewrite required", "design boundary"),
        ("Thor benchmark", "pending measured run", "not claimed"),
    ]
    body = "".join(
        "<tr>"
        f"<td>{escape(item)}</td><td>{escape(value)}</td><td>{escape(status)}</td>"
        "</tr>"
        for item, value, status in rows
    )
    return f"<table><tr><th>Item</th><th>Detail</th><th>Status</th></tr>{body}</table>"


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
            _card("Detector AUC", _metric(training_run, "detector", "evaluation", "gbc_auc"), "GBM detector on 5k fixture", "good"),
            _card("Thor validation", _metric(thor_benchmark, "source_badge", default="pending-thor-run"), "Hardware benchmark pending until measured", "warn"),
        ]
    )
    body = f"""
<section>
  <h2>Evidence Summary</h2>
  <div class="grid">{cards}</div>
</section>

<section>
  <h2>Current Working Analytics System</h2>
  <p>The current implementation uses fixed CSV telemetry as a deterministic fixture for lookback analytics, forecasting, operator-reviewed alerts, reports, and dashboard evidence.</p>
  <div class="grid">
    {_card("Input source", "fixed_csv", "Deterministic fixture for repeatable evidence", "neutral")}
    {_card("Lookback analysis", "implemented", "Feature windows and runtime metrics are generated", "good")}
    {_card("Forecasting", "implemented", "Training evidence records the forecaster gate", "good")}
    {_card("Alerts", "implemented", "Alerts are emitted for operator review", "warn")}
  </div>
</section>

<section>
  <h2>Planned Jetson Telemetry-Ingestion Upgrade</h2>
  <p>Fixed CSV is the deterministic test fixture, not the product ceiling. The planned upgrade adds Jetson-generated flow CSVs from packet capture and defensive telemetry sources such as Zeek logs, Suricata eve.json, and CICFlow-style records.</p>
  {_planned_upgrade_table()}
</section>

<section>
  <h2>Why This Exists</h2>
  <p>Edge nodes, robotics cells, private-network sites, and AI-enabled systems need local defensive telemetry review. This project does not replace a SIEM or claim a production IDS. It shows how local flow-style signals can become observable, forecastable, reviewable, and benchmarkable near the edge.</p>
</section>

<section>
  <h2>What I Built</h2>
  <p>I built a defensive edge telemetry runtime that normalizes events, extracts sliding-window features, runs conservative detection, emits alerts, stores evidence artifacts, and preserves a Jetson deployment path.</p>
  <div>
    <span class="pill">TrafficSource API</span>
    <span class="pill">TelemetryEvent schema</span>
    <span class="pill">fixed CSV fixture</span>
    <span class="pill">planned flow ingestion</span>
    <span class="pill">GBM detector artifact</span>
    <span class="pill">AR forecaster artifact</span>
    <span class="pill">FastAPI + web dashboard</span>
  </div>
</section>

<section>
  <h2>Visual Evidence Links</h2>
  <div class="grid">
    {_link_card("Operator dashboard", "dashboard.html", "Static evidence dashboard with runtime, model, and Thor-readiness summaries.")}
    {_link_card("Replay report", "demo/replay_report.md", "Defensive replay summary with events, windows, alerts, and safety boundary.")}
    {_link_card("Technical brief", "tech-brief.html", "Architecture principle, current pipeline, planned source adapters, and boundaries.")}
    {_link_card("Business case", "business-case.html", "Why local defensive telemetry matters near edge nodes and robotics cells.")}
    {_link_card("Training metrics", "training_run.json", "Committed detector and forecaster metrics, ONNX paths, gates, and CPU latency.")}
    {_link_card("Thor benchmark", "thor_benchmark.json", "Pending hardware benchmark template; values remain pending until measured on device.")}
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
        <li>Jetson AGX Thor-class deployment runbook</li>
      </ul>
    </div>
    <div>
      <h3>Boundary preserved</h3>
      <ul>
        <li>No offensive malware generation</li>
        <li>No exploit replay or offensive tooling</li>
        <li>No autonomous response action</li>
        <li>No live production IDS deployment claim</li>
        <li>No line-rate capture claim</li>
        <li>Thor latency remains pending until measured</li>
      </ul>
    </div>
  </div>
</section>
"""
    return _page_shell(
        "Jetson Edge Intrusion Detection",
        "Defensive edge telemetry, lookback analytics, forecasting, and operator-reviewed IDS alerts for Jetson-class network nodes.",
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
            _card("Current input", "fixed_csv", "Deterministic fixture for repeatable evidence", "neutral"),
            _card("Detector gate", _metric(training_run, "detector", "gate", "result"), "delta AUC threshold reported in training_run.json", "good"),
            _card("Forecaster gate", _metric(training_run, "forecaster", "gate", "result"), "MAE reduction threshold reported in training_run.json", "good"),
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
  <h2>Current Working System</h2>
  <p>The dashboard separates implemented CSV-driven analytics from planned Jetson flow ingestion. Completed metrics below come from the current fixed CSV fixture path.</p>
  <table>
    <tr><th>Capability</th><th>Status</th><th>Evidence</th></tr>
    <tr><td>Input source</td><td>fixed_csv</td><td>Deterministic fixture for replay and reporting</td></tr>
    <tr><td>Lookback analysis</td><td>implemented</td><td>{escape(_metric(demo_metrics, "windows_seen"))} feature windows</td></tr>
    <tr><td>Forecasting</td><td>implemented</td><td>Forecaster gate {_metric(training_run, "forecaster", "gate", "result")}</td></tr>
    <tr><td>Alerts</td><td>implemented</td><td>{escape(_metric(demo_metrics, "alerts_emitted"))} alerts emitted</td></tr>
    <tr><td>Dashboard / reporting</td><td>implemented</td><td>Static GitHub Pages-compatible evidence pack</td></tr>
  </table>
</section>

<section>
  <h2>Planned Jetson Ingestion Upgrade</h2>
  <p class="callout">Planned work is not counted as completed evidence. The next input is Jetson-generated flow CSV from defensive packet/flow sources, then the same analytics pipeline continues unchanged.</p>
  {_planned_upgrade_table()}
</section>

<section>
  <h2>Problem -> What I Built -> What I Found -> What I Would Validate Next</h2>
  <div class="two">
    <div><h3>Problem</h3><p>Edge IDS telemetry arrives from heterogeneous defensive sources, but operator workflows need one normalized evidence path.</p></div>
    <div><h3>What I Built</h3><p>A source-agnostic runtime that converts defensive telemetry into events, windows, detections, alerts, metrics, and evidence artifacts.</p></div>
    <div><h3>What I Found</h3><p>The committed demo emits {_metric(demo_metrics, "alerts_emitted")} alerts from {_metric(demo_metrics, "windows_seen")} feature windows, and model gates are recorded in training evidence.</p></div>
    <div><h3>What I Would Validate Next</h3><p>Generate Jetson flow CSV from defensive captures, run the Thor-class benchmark on actual hardware, and keep all response actions operator-reviewed.</p></div>
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
  <p class="callout">Thor benchmark values remain pending until `deploy/thor/run_benchmark.py` is executed on the exact target hardware. This dashboard does not fabricate edge latency, throughput, memory, power, or thermal behavior.</p>
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
        <li>Thor-class runbook and benchmark template</li>
      </ul>
    </div>
    <div>
      <h3>Boundary preserved</h3>
      <ul>
        <li>No offensive tooling</li>
        <li>No malware generation</li>
        <li>No exploit replay</li>
        <li>No autonomous response action</li>
        <li>No live production IDS deployment claim</li>
        <li>No line-rate capture claim</li>
      </ul>
    </div>
  </div>
</section>
"""
    return _page_shell(
        "Jetson Edge Intrusion Detection Dashboard",
        "Defensive edge telemetry, lookback analytics, forecasting, and operator-reviewed IDS alerts for Jetson-class network nodes.",
        body,
    )


def _render_tech_brief_page() -> str:
    body = f"""
<section>
  <h2>Technical Brief</h2>
  <p>Jetson Edge Intrusion Detection is built around one architecture rule: adapters may change, but the analytics pipeline should not. The current implementation validates the lookback, forecasting, alert, and reporting layers with fixed CSV telemetry as a deterministic fixture.</p>
</section>

<section>
  <h2>Current vs Planned Pipeline</h2>
  {_current_vs_planned_table()}
</section>

<section>
  <h2>Architecture Principle</h2>
  <p class="callout">Adapters may change. The analytics pipeline should not.</p>
  <p>The planned upgrade adds a Jetson packet/flow ingestion stage before the existing CSV contract. New sources should normalize into the same event/schema boundary so the detector, lookback, forecasting, alerting, and dashboard layers remain stable.</p>
</section>

<section>
  <h2>Adapter Status</h2>
  <table>
    <tr><th>Adapter</th><th>Status</th><th>Purpose</th></tr>
    <tr><td>CsvTrafficSource</td><td>Implemented / current fixture</td><td>Reads fixed CSV telemetry and emits normalized events.</td></tr>
    <tr><td>ZeekConnLogSource</td><td>Planned</td><td>Normalize Zeek conn.log records into the event contract.</td></tr>
    <tr><td>SuricataEveJsonSource</td><td>Planned</td><td>Normalize Suricata eve.json flow and alert records.</td></tr>
    <tr><td>CicFlowCsvSource</td><td>Planned</td><td>Normalize CICFlow-style records.</td></tr>
    <tr><td>PcapFlowSource / PcapCaptureStage</td><td>Planned</td><td>Capture or replay packets, rotate PCAP files, and feed defensive flow extraction.</td></tr>
  </table>
</section>

<section>
  <h2>Boundary</h2>
  <ul>
    <li>Defensive telemetry only.</li>
    <li>No malware generation, exploit replay, or offensive tooling.</li>
    <li>No autonomous response.</li>
    <li>No production IDS deployment claim.</li>
    <li>No line-rate capture claim until packet drops, throughput, storage write rate, and flow extraction performance are measured.</li>
  </ul>
</section>
"""
    return _page_shell(
        "Technical Brief",
        "Current CSV-driven analytics, planned Jetson flow ingestion, stable event contracts, and defensive boundaries.",
        body,
    )


def _render_business_case_page() -> str:
    body = """
<section>
  <h2>Business Case</h2>
  <p>Edge nodes, robotics cells, private-network sites, and AI-enabled edge systems need local defensive telemetry review. The useful question is not whether this replaces a SIEM. It does not. The useful question is whether local flow records can become observable, forecastable, reviewable, and benchmarkable near the edge.</p>
</section>

<section>
  <h2>What This Demonstrates</h2>
  <ul>
    <li>Fixed CSV telemetry can drive deterministic lookback analytics, forecasting, alerts, and static reports.</li>
    <li>Operator-reviewed alerts create a review path without autonomous response.</li>
    <li>The same analytics pipeline can accept future Jetson-generated flow CSVs when the source adapters are measured.</li>
    <li>Thor-class benchmark artifacts remain pending until real hardware measurements exist.</li>
  </ul>
</section>

<section>
  <h2>What This Does Not Claim</h2>
  <ul>
    <li>It does not replace a SIEM or production IDS.</li>
    <li>It does not claim line-rate capture.</li>
    <li>It does not claim measured Thor performance yet.</li>
    <li>It does not perform offensive security actions or autonomous response.</li>
  </ul>
</section>
"""
    return _page_shell(
        "Business Case",
        "Local defensive telemetry evidence for Jetson-class edge nodes, without production IDS or autonomous response claims.",
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
