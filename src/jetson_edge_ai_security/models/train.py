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

train_app = typer.Typer(help="Model training commands (real impl ships in Commit 2)")
export_app = typer.Typer(help="ONNX export commands")
bench_app = typer.Typer(help="Inference benchmark commands")


# ──────────────────────────────────────────────────────────────────────────────
# train subcommands
# ──────────────────────────────────────────────────────────────────────────────


@train_app.command("detector")
def train_detector(
    dataset: Annotated[Path, typer.Option(help="Path to Edge-IIoTset CSV.")] = Path(
        "data/edge-iiotset.csv"
    ),
    output_dir: Annotated[Path, typer.Option(help="Directory to write trained model.")] = Path(
        "models/exports"
    ),
    epochs: Annotated[int, typer.Option(help="Training epochs.")] = 10,
    seed: Annotated[int, typer.Option(help="Random seed.")] = 42,
) -> None:
    """[Stub] Train a reference Detector on Edge-IIoTset data.

    Real implementation ships in Commit 2.
    """
    console.print(
        "[yellow]train detector: not yet implemented (Commit 2). "
        f"Would train on {dataset}, epochs={epochs}, seed={seed}, output={output_dir}[/yellow]"
    )
    raise typer.Exit(code=0)


@train_app.command("forecaster")
def train_forecaster(
    dataset: Annotated[Path, typer.Option(help="Path to Edge-IIoTset CSV.")] = Path(
        "data/edge-iiotset.csv"
    ),
    output_dir: Annotated[Path, typer.Option(help="Directory to write trained model.")] = Path(
        "models/exports"
    ),
    epochs: Annotated[int, typer.Option(help="Training epochs.")] = 10,
    seed: Annotated[int, typer.Option(help="Random seed.")] = 42,
) -> None:
    """[Stub] Train a reference Forecaster on Edge-IIoTset data.

    Real implementation ships in Commit 2.
    """
    console.print(
        "[yellow]train forecaster: not yet implemented (Commit 2). "
        f"Would train on {dataset}, epochs={epochs}, seed={seed}, output={output_dir}[/yellow]"
    )
    raise typer.Exit(code=0)


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
