"""Command-line interface for the edge security runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from jetson_edge_ai_security.alerts import AlertBuilder
from jetson_edge_ai_security.config import AppConfig, load_config
from jetson_edge_ai_security.datasets import (
    DatasetDownloadError,
    list_datasets,
    prepare_dataset,
)
from jetson_edge_ai_security.detection import BaselineDetector, BaselineThresholds
from jetson_edge_ai_security.models.train import bench_app, export_app, train_app
from jetson_edge_ai_security.runtime import PipelineRunner, write_replay_artifacts
from jetson_edge_ai_security.schemas import Alert
from jetson_edge_ai_security.sources import CsvReplaySource
from jetson_edge_ai_security.utils import configure_logging

app = typer.Typer(help="Defensive edge security telemetry runtime")
app.add_typer(train_app, name="train")
app.add_typer(export_app, name="export")
app.add_typer(bench_app, name="bench")
console = Console()


@app.command("validate-config")
def validate_config(
    config: Annotated[Path, typer.Option(help="Path to YAML config file.")] = Path("configs/default.yaml"),
) -> None:
    """Validate runtime configuration."""

    loaded = load_config(config)
    console.print(json.dumps(loaded.model_dump(mode="json"), indent=2))


@app.command("list-datasets")
def list_public_datasets() -> None:
    """List known public defensive datasets and download support status."""

    table = Table(title="Known Public Defensive Telemetry Datasets")
    table.add_column("Key")
    table.add_column("Dataset")
    table.add_column("Auto")
    table.add_column("Homepage")
    table.add_column("Notes")

    for dataset in list_datasets():
        table.add_row(
            dataset.key,
            dataset.name,
            "yes" if dataset.direct_download_url else "manual",
            dataset.homepage_url,
            dataset.notes,
        )
    console.print(table)


@app.command("fetch-dataset")
def fetch_dataset(
    dataset: Annotated[str, typer.Argument(help="Dataset key from list-datasets.")],
    cache_dir: Annotated[Path, typer.Option(help="Directory for downloaded datasets.")] = Path("data/datasets"),
    force: Annotated[bool, typer.Option(help="Re-download and re-extract the dataset.")] = False,
    csv_glob: Annotated[str | None, typer.Option(help="Optional CSV glob to select a specific file.")] = None,
) -> None:
    """Download, extract, and locate a CSV from an allowlisted public dataset."""

    try:
        prepared = prepare_dataset(dataset, cache_dir=cache_dir, force=force, csv_glob=csv_glob)
    except (DatasetDownloadError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(f"Dataset: {prepared.spec.name}", markup=False)
    console.print(f"Archive: {prepared.archive_path}", markup=False)
    console.print(f"Extracted: {prepared.extract_dir}", markup=False)
    console.print(f"CSV: {prepared.csv_path}", markup=False)


@app.command("replay-csv")
def replay_csv(
    path: Annotated[Path, typer.Option(help="CSV telemetry file to replay.")],
    limit: Annotated[int | None, typer.Option(help="Maximum rows to replay.")] = None,
    config: Annotated[Path, typer.Option(help="Path to YAML config file.")] = Path("configs/default.yaml"),
    strict: Annotated[bool | None, typer.Option(help="Fail on malformed rows.")] = None,
    json_output: Annotated[bool, typer.Option(help="Print alerts as JSON lines.")] = False,
    output_dir: Annotated[Path | None, typer.Option(help="Optional directory for replay evidence artifacts.")] = None,
) -> None:
    """Replay a CSV telemetry file through the detection pipeline."""

    configure_logging()
    alerts, runner, source = _run_csv_pipeline(
        path=path,
        limit=limit,
        config=config,
        strict=strict,
    )

    if json_output:
        for alert in alerts:
            console.print(json.dumps(alert.model_dump(mode="json"), sort_keys=True))
    else:
        _print_alert_table(alerts)
        console.print(
            f"events={runner.metrics.events_seen} windows={runner.metrics.windows_seen} "
            f"alerts={runner.metrics.alerts_emitted} skipped_rows={source.rows_skipped}",
            markup=False,
        )

    if output_dir is not None:
        paths = write_replay_artifacts(
            output_dir=output_dir,
            alerts=alerts,
            metrics=runner.metrics,
            source_name=str(path),
            rows_skipped=source.rows_skipped,
        )
        for artifact in paths:
            console.print(f"Wrote artifact: {artifact}", markup=False)


@app.command("replay-dataset")
def replay_dataset(
    dataset: Annotated[str, typer.Argument(help="Dataset key from list-datasets.")],
    limit: Annotated[int | None, typer.Option(help="Maximum rows to replay.")] = 1000,
    cache_dir: Annotated[Path, typer.Option(help="Directory for downloaded datasets.")] = Path("data/datasets"),
    config: Annotated[Path, typer.Option(help="Path to YAML config file.")] = Path("configs/default.yaml"),
    strict: Annotated[bool | None, typer.Option(help="Fail on malformed rows.")] = None,
    force: Annotated[bool, typer.Option(help="Re-download and re-extract the dataset.")] = False,
    csv_glob: Annotated[str | None, typer.Option(help="Optional CSV glob to select a specific file.")] = None,
    json_output: Annotated[bool, typer.Option(help="Print alerts as JSON lines.")] = False,
    output_dir: Annotated[Path | None, typer.Option(help="Optional directory for replay evidence artifacts.")] = None,
) -> None:
    """Download a known dataset, find a CSV, and replay it through the pipeline."""

    configure_logging()
    try:
        prepared = prepare_dataset(dataset, cache_dir=cache_dir, force=force, csv_glob=csv_glob)
    except (DatasetDownloadError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(f"Using dataset CSV: {prepared.csv_path}", markup=False)
    alerts, runner, source = _run_csv_pipeline(
        path=prepared.csv_path,
        limit=limit,
        config=config,
        strict=strict,
    )

    if json_output:
        for alert in alerts:
            console.print(json.dumps(alert.model_dump(mode="json"), sort_keys=True))
    else:
        _print_alert_table(alerts)
        console.print(
            f"dataset={prepared.spec.key} events={runner.metrics.events_seen} "
            f"windows={runner.metrics.windows_seen} alerts={runner.metrics.alerts_emitted} "
            f"skipped_rows={source.rows_skipped}",
            markup=False,
        )

    if output_dir is not None:
        paths = write_replay_artifacts(
            output_dir=output_dir,
            alerts=alerts,
            metrics=runner.metrics,
            source_name=prepared.spec.key,
            rows_skipped=source.rows_skipped,
        )
        for artifact in paths:
            console.print(f"Wrote artifact: {artifact}", markup=False)


def _run_csv_pipeline(
    *,
    path: Path,
    limit: int | None,
    config: Path,
    strict: bool | None,
) -> tuple[list[Alert], PipelineRunner, CsvReplaySource]:
    loaded = load_config(config)
    detector = _detector_from_config(loaded)
    alert_builder = AlertBuilder(
        source=loaded.alerts.source,
        recommended_action=loaded.alerts.default_recommended_action,
    )
    source = CsvReplaySource(
        path,
        limit=limit,
        replay_delay_seconds=loaded.runtime.replay_delay_seconds,
        strict=loaded.runtime.strict_csv if strict is None else strict,
    )

    with source:
        runner = PipelineRunner(
            source,
            window_size=loaded.runtime.window_size,
            step=loaded.runtime.step,
            detector=detector,
            alert_builder=alert_builder,
        )
        alerts = runner.run()

    return alerts, runner, source


@app.command("run-demo")
def run_demo() -> None:
    """Run the pipeline against a tiny built-in defensive replay sample."""

    with NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as handle:
        handle.write(
            "timestamp,ip.src_host,ip.dst_host,tcp.srcport,tcp.dstport,_ws.col.Protocol,"
            "frame.len,tcp.flags,Attack_label,Attack_type\n"
        )
        for index in range(12):
            label = 1 if index >= 8 else 0
            attack_type = "lab-replay" if label else "normal"
            handle.write(
                f"2026-01-01 00:00:{index:02d},10.0.0.{index + 1},10.0.1.10,"
                f"{5000 + index},443,TCP,{100 + index},S,{label},{attack_type}\n"
            )
        demo_path = Path(handle.name)

    try:
        source = CsvReplaySource(demo_path, limit=12)
        detector = BaselineDetector(BaselineThresholds(packet_count_threshold=100, attack_count_threshold=1))
        with source:
            runner = PipelineRunner(source, window_size=5, step=1, detector=detector)
            alerts = runner.run()
        _print_alert_table(alerts)
        console.print(f"Demo complete: {len(alerts)} alerts from {runner.metrics.windows_seen} windows")
    finally:
        demo_path.unlink(missing_ok=True)


@app.command("generate-demo-report")
def generate_demo_report(
    output_dir: Annotated[Path, typer.Option(help="Directory for generated demo artifacts.")] = Path("reports/demo"),
) -> None:
    """Generate committed proof artifacts from a tiny built-in defensive replay sample."""

    with NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as handle:
        handle.write(
            "timestamp,ip.src_host,ip.dst_host,tcp.srcport,tcp.dstport,_ws.col.Protocol,"
            "frame.len,tcp.flags,Attack_label,Attack_type\n"
        )
        for index in range(12):
            label = 1 if index >= 8 else 0
            attack_type = "lab-replay" if label else "normal"
            handle.write(
                f"2026-01-01 00:00:{index:02d},10.0.0.{index + 1},10.0.1.10,"
                f"{5000 + index},443,TCP,{100 + index},S,{label},{attack_type}\n"
            )
        demo_path = Path(handle.name)

    try:
        source = CsvReplaySource(demo_path, limit=12)
        detector = BaselineDetector(BaselineThresholds(packet_count_threshold=100, attack_count_threshold=1))
        with source:
            runner = PipelineRunner(source, window_size=5, step=1, detector=detector)
            alerts = runner.run()
        fixed_start = datetime(2026, 1, 1, tzinfo=UTC)
        fixed_finished = datetime(2026, 1, 1, 0, 0, 4, tzinfo=UTC)
        runner.metrics.started_at = fixed_start
        runner.metrics.finished_at = fixed_finished
        alerts = [alert.model_copy(update={"timestamp": fixed_finished}) for alert in alerts]
        paths = write_replay_artifacts(
            output_dir=output_dir,
            alerts=alerts,
            metrics=runner.metrics,
            source_name="built-in-defensive-demo",
            rows_skipped=source.rows_skipped,
        )
        for artifact in paths:
            console.print(f"Wrote artifact: {artifact}", markup=False)
    finally:
        demo_path.unlink(missing_ok=True)


def _detector_from_config(config: AppConfig) -> BaselineDetector:
    detector_config = config.detector
    thresholds = BaselineThresholds(
        packet_count_threshold=detector_config.packet_count_threshold,
        event_rate_threshold=detector_config.event_rate_threshold,
        unique_source_ip_threshold=detector_config.unique_source_ip_threshold,
        attack_count_threshold=detector_config.attack_count_threshold,
    )
    return BaselineDetector(
        thresholds=thresholds,
        use_isolation_forest=detector_config.use_isolation_forest,
    )


def _print_alert_table(alerts: list[Alert]) -> None:
    table = Table(title="Edge Security Alerts")
    table.add_column("Severity")
    table.add_column("Title")
    table.add_column("Description")

    for alert in alerts:
        table.add_row(alert.severity, alert.title, alert.description)
    console.print(table)


if __name__ == "__main__":
    app()
