"""Training CLI subcommands — Commit 1 stubs.

These are no-op placeholders wired into the ``edge-security`` CLI.
Real training implementations ship in Commit 2 under
``models/training/train_detector.py`` and ``models/training/train_forecaster.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()

train_app = typer.Typer(help="Model training commands")
export_app = typer.Typer(help="ONNX export commands")
bench_app = typer.Typer(help="Inference benchmark commands")
models_app = typer.Typer(help="Model registry commands")


# ──────────────────────────────────────────────────────────────────────────────
# train subcommands
# ──────────────────────────────────────────────────────────────────────────────


@train_app.command("detector")
def train_detector_cmd(
    dataset: Annotated[Path, typer.Option(help="Path to Edge-IIoTset CSV.")] = Path(
        "tests/fixtures/edge_iiotset_sample_5k.csv"
    ),
    output_dir: Annotated[Path, typer.Option(help="Directory to write trained model.")] = Path(
        "models/exports"
    ),
    seed: Annotated[int, typer.Option(help="Random seed.")] = 42,
    n_estimators: Annotated[int, typer.Option(help="GBM n_estimators.")] = 100,
    max_depth: Annotated[int, typer.Option(help="GBM max_depth.")] = 4,
) -> None:
    """Train the GBM reference Detector on Edge-IIoTset data."""
    import json

    from jetson_edge_ai_security.models.training.train_detector import train_detector

    metrics = train_detector(
        dataset=dataset,
        output_dir=output_dir,
        seed=seed,
        n_estimators=n_estimators,
        max_depth=max_depth,
    )
    console.print(json.dumps(metrics, indent=2))
    gate = metrics["gate"]["result"]
    if gate != "PASS":
        console.print(f"[red]Gate {gate}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Gate PASS — delta_auc={metrics['metrics']['delta_auc']}[/green]")


@train_app.command("forecaster")
def train_forecaster_cmd(
    dataset: Annotated[Path, typer.Option(help="Path to Edge-IIoTset CSV.")] = Path(
        "tests/fixtures/edge_iiotset_sample_5k.csv"
    ),
    output_dir: Annotated[Path, typer.Option(help="Directory to write trained model.")] = Path(
        "models/exports"
    ),
    seed: Annotated[int, typer.Option(help="Random seed.")] = 42,
    lookback_bins: Annotated[int, typer.Option(help="Lookback bins.")] = 20,
    forecast_bins: Annotated[int, typer.Option(help="Forecast bins.")] = 6,
) -> None:
    """Train the AR reference Forecaster on Edge-IIoTset data."""
    import json

    from jetson_edge_ai_security.models.training.train_forecaster import train_forecaster

    metrics = train_forecaster(
        dataset=dataset,
        output_dir=output_dir,
        seed=seed,
        lookback_bins=lookback_bins,
        forecast_bins=forecast_bins,
    )
    console.print(json.dumps(metrics, indent=2))
    gate = metrics["gate"]["result"]
    if gate != "PASS":
        console.print(f"[red]Gate {gate}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Gate PASS — mae_reduction={metrics['metrics']['mae_reduction_pct']}%[/green]")


# ──────────────────────────────────────────────────────────────────────────────
# export subcommands
# ──────────────────────────────────────────────────────────────────────────────


@export_app.command("onnx")
def export_onnx(
    model_type: Annotated[
        str, typer.Argument(help="Model type to export: 'mock-detector' or 'mock-forecaster'.")
    ] = "mock-detector",
    output_dir: Annotated[Path, typer.Option(help="Directory to write ONNX file.")] = Path(
        "models/exports"
    ),
    feature_dim: Annotated[int, typer.Option(help="Input feature dimension.")] = 57,
    forecast_bins: Annotated[int, typer.Option(help="Forecast bins (forecaster only).")] = 6,
) -> None:
    """Export a Detector or Forecaster to ONNX format."""
    from jetson_edge_ai_security.models.export_onnx import (
        export_mock_detector,
        export_mock_forecaster,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    if model_type == "mock-detector":
        out = export_mock_detector(
            output_dir / "mock_detector.onnx", feature_dim=feature_dim, validate=True
        )
        console.print(f"Exported mock detector: {out}")
    elif model_type == "mock-forecaster":
        out = export_mock_forecaster(
            output_dir / "mock_forecaster.onnx",
            feature_dim=feature_dim,
            forecast_bins=forecast_bins,
            validate=True,
        )
        console.print(f"Exported mock forecaster: {out}")
    else:
        console.print(f"[red]Unknown model type: {model_type}[/red]")
        raise typer.Exit(code=1)


# ──────────────────────────────────────────────────────────────────────────────
# bench subcommands
# ──────────────────────────────────────────────────────────────────────────────


@bench_app.command("cpu")
def bench_cpu(
    model_type: Annotated[
        str, typer.Argument(help="Model type: 'mock-detector' or 'mock-forecaster'.")
    ] = "mock-detector",
    n_runs: Annotated[int, typer.Option(help="Number of inference runs.")] = 100,
    feature_dim: Annotated[int, typer.Option(help="Feature dimension.")] = 57,
    forecast_bins: Annotated[int, typer.Option(help="Forecast bins (forecaster only).")] = 6,
) -> None:
    """Benchmark CPU inference latency for a mock model.

    Exports to a temporary ONNX file, then times onnxruntime inference.
    """
    import tempfile
    import time

    import numpy as np
    import onnxruntime as ort

    from jetson_edge_ai_security.models.export_onnx import (
        export_mock_detector,
        export_mock_forecaster,
    )

    rng = np.random.default_rng(0)

    with tempfile.TemporaryDirectory() as tmpdir:
        if model_type == "mock-detector":
            path = export_mock_detector(
                f"{tmpdir}/mock_detector.onnx", feature_dim=feature_dim, validate=False
            )
            sess = ort.InferenceSession(str(path))
            x = rng.standard_normal((1, feature_dim)).astype(np.float32)
            inputs = {"X": x}
        elif model_type == "mock-forecaster":
            path = export_mock_forecaster(
                f"{tmpdir}/mock_forecaster.onnx",
                feature_dim=feature_dim,
                forecast_bins=forecast_bins,
                validate=False,
            )
            sess = ort.InferenceSession(str(path))
            h = rng.standard_normal((1, 20, feature_dim)).astype(np.float32)
            inputs = {"H": h}
        else:
            console.print(f"[red]Unknown model type: {model_type}[/red]")
            raise typer.Exit(code=1)

        # Warm-up
        for _ in range(5):
            sess.run(None, inputs)

        # Timed runs
        latencies = []
        for _ in range(n_runs):
            t0 = time.perf_counter()
            sess.run(None, inputs)
            latencies.append((time.perf_counter() - t0) * 1000.0)

        lat = sorted(latencies)
        p50 = lat[len(lat) // 2]
        p95 = lat[int(len(lat) * 0.95)]
        console.print(
            f"[bold]{model_type}[/bold] CPU ({n_runs} runs) — "
            f"p50={p50:.2f}ms  p95={p95:.2f}ms  badge=measured-cpu"
        )


@bench_app.command("cuda")
def bench_cuda(
    model_type: Annotated[
        str, typer.Argument(help="Model type: 'mock-detector' or 'mock-forecaster'.")
    ] = "mock-detector",
    n_runs: Annotated[int, typer.Option(help="Number of inference runs.")] = 100,
    feature_dim: Annotated[int, typer.Option(help="Feature dimension.")] = 57,
) -> None:
    """[Stub] Benchmark CUDA inference latency (requires CUDA provider).

    Real implementation ships in Commit 2 with reference model.
    """
    console.print(
        "[yellow]bench cuda: full CUDA benchmark ships in Commit 2 with reference model. "
        f"Would bench {model_type} on CUDA, {n_runs} runs.[/yellow]"
    )
    raise typer.Exit(code=0)


# ──────────────────────────────────────────────────────────────────────────────
# models subcommands
# ──────────────────────────────────────────────────────────────────────────────


@models_app.command("list")
def models_list(
    model_dir: Annotated[Path, typer.Option(help="Directory containing trained models.")] = Path(
        "models/exports"
    ),
    reports_dir: Annotated[Path, typer.Option(help="Directory containing training_run.json.")] = Path(
        "reports"
    ),
) -> None:
    """List available Detector and Forecaster models with their metrics."""
    import json

    from rich.table import Table

    table = Table(title="Available Models")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Architecture")
    table.add_column("File")
    table.add_column("AUC / MAE-red%")

    # Load training_run.json if present
    metrics_path = reports_dir / "training_run.json"
    run_info: dict = {}
    if metrics_path.exists():
        with metrics_path.open() as fh:
            run_info = json.load(fh)

    det_info = run_info.get("detector", {})
    fcast_info = run_info.get("forecaster", {})

    # Detector
    det_pkl = model_dir / "gbm_detector.pkl"
    if det_pkl.exists():
        auc = det_info.get("evaluation", {}).get("gbc_auc", "—")
        table.add_row(
            "Detector",
            det_info.get("model", "gbm-detector"),
            det_info.get("architecture", "GradientBoostingClassifier"),
            str(det_pkl.name),
            f"AUC={auc}",
        )

    # Mock detector (always available)
    table.add_row("Detector", "mock-detector", "mock", "(in-memory)", "—")

    # Forecaster
    fcast_pkl = model_dir / "ar_forecaster.pkl"
    if fcast_pkl.exists():
        red = fcast_info.get("evaluation", {}).get("mae_reduction_pct", "—")
        table.add_row(
            "Forecaster",
            fcast_info.get("model", "ar-forecaster"),
            fcast_info.get("architecture", "Pipeline(StandardScaler, Ridge)"),
            str(fcast_pkl.name),
            f"MAE-red={red}%",
        )

    # Mock forecaster
    table.add_row("Forecaster", "mock-forecaster", "mock", "(in-memory)", "—")

    console.print(table)


@models_app.command("set-active")
def models_set_active(
    model_type: Annotated[str, typer.Argument(help="'detector' or 'forecaster'")],
    model_name: Annotated[str, typer.Argument(help="Model name (e.g. 'gbm-detector', 'mock-detector')")],
    config_path: Annotated[Path, typer.Option(help="Path to YAML config.")] = Path(
        "configs/default.yaml"
    ),
) -> None:
    """Set the active Detector or Forecaster in the runtime config."""
    import yaml

    if model_type not in ("detector", "forecaster"):
        console.print(f"[red]model_type must be 'detector' or 'forecaster', got: {model_type}[/red]")
        raise typer.Exit(code=1)

    if not config_path.exists():
        console.print(f"[red]Config not found: {config_path}[/red]")
        raise typer.Exit(code=1)

    with config_path.open() as fh:
        cfg = yaml.safe_load(fh) or {}

    cfg.setdefault("models", {})
    key = "detector_active" if model_type == "detector" else "forecaster_active"
    cfg["models"][key] = model_name

    with config_path.open("w") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)

    console.print(f"[green]Set {model_type} active model → {model_name}[/green]")
    console.print(f"Updated: {config_path}")
