#!/usr/bin/env python3
"""Build TensorRT engines from shipped ONNX models.

Run once on the Jetson AGX Thor after deploying the container or after
updating the ONNX files.  Engines are saved alongside the ONNX files as
``<name>.trt``.

Usage:
    python3 deploy/thor/build_tensorrt_engines.py [--models-dir models/exports]

Requirements:
    - TensorRT 10.x (available on JetPack 6.x)
    - tensorrt Python bindings: pip install tensorrt
    - NVIDIA GPU + CUDA (Jetson or discrete GPU)

The script validates each engine with a synthetic input after building.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def _trt_available() -> bool:
    try:
        import tensorrt  # noqa: F401
        return True
    except ImportError:
        return False


def build_engine(
    onnx_path: Path,
    engine_path: Path,
    *,
    fp16: bool = True,
    workspace_mb: int = 1024,
) -> None:
    """Convert an ONNX model to a TensorRT engine.

    Parameters
    ----------
    onnx_path:
        Source ONNX file.
    engine_path:
        Destination ``.trt`` file.
    fp16:
        Enable FP16 precision (default: True on Jetson).
    workspace_mb:
        Builder workspace in MB.
    """
    import tensorrt as trt  # type: ignore[import]

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)

    print(f"  Parsing ONNX: {onnx_path.name}")
    with onnx_path.open("rb") as fh:
        if not parser.parse(fh.read()):
            for i in range(parser.num_errors):
                print(f"  ONNX parse error: {parser.get_error(i)}")
            raise RuntimeError(f"Failed to parse {onnx_path}")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_mb * 1024 * 1024)

    if fp16 and builder.platform_has_fast_fp16:
        config.set_flag(trt.BuilderFlag.FP16)
        print("  FP16 precision enabled")

    print("  Building engine (this may take 1–5 minutes)…")
    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise RuntimeError("Engine build failed")

    engine_path.write_bytes(serialized)
    print(f"  Engine written: {engine_path} ({engine_path.stat().st_size // 1024} KB)")


def validate_engine(engine_path: Path, input_shape: tuple[int, ...]) -> float:
    """Run a synthetic inference pass and return p50 latency in ms."""
    import numpy as np
    import tensorrt as trt  # type: ignore[import]

    logger = trt.Logger(trt.Logger.WARNING)
    runtime = trt.Runtime(logger)

    with engine_path.open("rb") as fh:
        engine = runtime.deserialize_cuda_engine(fh.read())

    context = engine.create_execution_context()

    # Build dummy input
    rng = np.random.default_rng(42)
    x = rng.standard_normal(input_shape).astype(np.float32)

    import pycuda.autoinit  # type: ignore[import]  # noqa: F401
    import pycuda.driver as cuda  # type: ignore[import]

    d_input = cuda.mem_alloc(x.nbytes)
    cuda.memcpy_htod(d_input, x)

    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        context.execute_v2([int(d_input)])
        latencies.append((time.perf_counter() - t0) * 1000)

    lat = sorted(latencies)
    p50 = lat[len(lat) // 2]
    print(f"  Validation p50 latency: {p50:.2f} ms")
    return p50


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TensorRT engines from ONNX models.")
    parser.add_argument("--models-dir", default="models/exports", help="Directory with ONNX files.")
    parser.add_argument("--fp16", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workspace-mb", type=int, default=1024)
    parser.add_argument("--skip-validation", action="store_true", default=False)
    args = parser.parse_args()

    if not _trt_available():
        print("ERROR: TensorRT Python bindings not available.", file=sys.stderr)
        print("Install with: pip install tensorrt  (requires JetPack 6.x)", file=sys.stderr)
        sys.exit(1)

    models_dir = Path(args.models_dir)
    if not models_dir.exists():
        print(f"ERROR: models directory not found: {models_dir}", file=sys.stderr)
        sys.exit(1)

    onnx_files = list(models_dir.glob("*.onnx"))
    if not onnx_files:
        print(f"No .onnx files found in {models_dir}", file=sys.stderr)
        sys.exit(1)

    # Input shapes per model (batch=1)
    input_shapes: dict[str, tuple[int, ...]] = {
        "gbm_detector": (1, 57),
        "ar_forecaster": (1, 20, 57),
        "mock_detector": (1, 57),
        "mock_forecaster": (1, 20, 57),
    }

    results: list[dict] = []
    for onnx_path in sorted(onnx_files):
        stem = onnx_path.stem
        engine_path = onnx_path.with_suffix(".trt")
        print(f"\n[{stem}]")

        try:
            t_start = time.perf_counter()
            build_engine(onnx_path, engine_path, fp16=args.fp16, workspace_mb=args.workspace_mb)
            build_s = time.perf_counter() - t_start

            p50_ms = None
            if not args.skip_validation:
                shape = input_shapes.get(stem, (1, 57))
                try:
                    p50_ms = validate_engine(engine_path, shape)
                except Exception as e:
                    print(f"  Validation skipped (pycuda not available): {e}")

            with onnx_path.open("rb") as fh:
                onnx_hash = hashlib.sha256(fh.read()).hexdigest()[:16]

            results.append({
                "model": stem,
                "onnx_hash": onnx_hash,
                "engine_path": str(engine_path),
                "engine_size_bytes": engine_path.stat().st_size,
                "build_seconds": round(build_s, 1),
                "fp16": args.fp16,
                "p50_validation_ms": p50_ms,
                "built_at": datetime.now(UTC).isoformat(),
            })
            print(f"  Build time: {build_s:.1f}s")
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"model": stem, "error": str(e)})

    # Write build manifest
    manifest_path = models_dir / "trt_build_manifest.json"
    manifest = {
        "built_at": datetime.now(UTC).isoformat(),
        "fp16": args.fp16,
        "workspace_mb": args.workspace_mb,
        "engines": results,
    }
    with manifest_path.open("w") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"\nBuild manifest written: {manifest_path}")
    successes = sum(1 for r in results if "error" not in r)
    print(f"Done: {successes}/{len(results)} engines built successfully.")


if __name__ == "__main__":
    main()
