"""ONNX export and validation for Detector and Forecaster implementations.

Builds minimal ONNX graphs from scratch using the ``onnx`` library (no torch/
tensorflow required). Validates each exported model by running inference with
``onnxruntime`` and comparing against the Python mock to confirm output equality
within fp32 tolerance.

Opset target: 17.

Detector ONNX graph (input X: (batch, feature_dim)):
  probability = tanh(reduce_mean(X, axis=1) / 10) * 0.5 + 0.5   → (batch,)
  logits      = softmax(X[:, :num_classes], axis=1)               → (batch, num_classes)

Forecaster ONNX graph (input H: (batch, lookback_bins, feature_dim)):
  last_step     = H[:, -1:, :]                             → (batch, 1, feature_dim)
  mean_last     = reduce_mean(last_step, axis=2)            → (batch, 1)
  intensity     = clip(mean_last, min=0) tiled             → (batch, forecast_bins)
  type_logits   = zeros tiled + class0_bias                → (batch, forecast_bins, num_classes)
  type_probs    = softmax(type_logits, axis=2)             → (batch, forecast_bins, num_classes)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.mock_detector import _mock_compute
from jetson_edge_ai_security.models.mock_forecaster import _mock_forecast_compute

_OPSET: int = 17
_NUM_CLASSES: int = len(ATTACK_TYPES)  # 15
_INT64_MAX: int = 2**62  # safe large integer for slice ends


# ──────────────────────────────────────────────────────────────────────────────
# Detector ONNX export
# ──────────────────────────────────────────────────────────────────────────────


def build_mock_detector_onnx(
    *,
    feature_dim: int = 57,
    num_classes: int = _NUM_CLASSES,
) -> onnx.ModelProto:
    """Construct the mock detector ONNX graph.

    The computation exactly mirrors :func:`mock_detector._mock_compute`:
      prob = tanh(mean(X, axis=1) / 10) * 0.5 + 0.5
      logits = softmax(X[:, :num_classes], axis=1)

    Args:
        feature_dim: Input feature dimension (columns in X).
        num_classes: Number of output classes.

    Returns:
        Validated ONNX ModelProto (opset 17).
    """
    # ── inputs / outputs ──────────────────────────────────────────────
    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [None, feature_dim])
    probability = helper.make_tensor_value_info("probability", TensorProto.FLOAT, [None])
    logits = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [None, num_classes])

    # ── initializers (constants) ──────────────────────────────────────
    c10 = numpy_helper.from_array(np.array(10.0, dtype=np.float32), name="c10")
    c05 = numpy_helper.from_array(np.array(0.5, dtype=np.float32), name="c05")

    # Slice: axes=[1], starts=[0], ends=[num_classes]
    slice_starts = numpy_helper.from_array(np.array([0], dtype=np.int64), name="slice_starts")
    slice_ends = numpy_helper.from_array(np.array([num_classes], dtype=np.int64), name="slice_ends")
    slice_axes = numpy_helper.from_array(np.array([1], dtype=np.int64), name="slice_axes")

    # ── nodes for probability ─────────────────────────────────────────
    # reduce_mean(X, axes=[1]) → (batch,)
    reduce_mean = helper.make_node(
        "ReduceMean", inputs=["X"], outputs=["mean_x"], axes=[1], keepdims=0
    )
    # mean_x / 10.0 → scaled
    div_node = helper.make_node("Div", inputs=["mean_x", "c10"], outputs=["scaled"])
    # tanh(scaled) → tanh_val
    tanh_node = helper.make_node("Tanh", inputs=["scaled"], outputs=["tanh_val"])
    # tanh_val * 0.5 → half
    mul_node = helper.make_node("Mul", inputs=["tanh_val", "c05"], outputs=["half"])
    # half + 0.5 → probability
    add_node = helper.make_node("Add", inputs=["half", "c05"], outputs=["probability"])

    # ── nodes for logits ──────────────────────────────────────────────
    # slice X[:, :num_classes] → sliced  (batch, num_classes)
    slice_node = helper.make_node(
        "Slice",
        inputs=["X", "slice_starts", "slice_ends", "slice_axes"],
        outputs=["sliced"],
    )
    # softmax(sliced, axis=1) → logits
    softmax_node = helper.make_node("Softmax", inputs=["sliced"], outputs=["logits"], axis=1)

    # ── assemble graph ────────────────────────────────────────────────
    graph = helper.make_graph(
        [reduce_mean, div_node, tanh_node, mul_node, add_node, slice_node, softmax_node],
        "mock_detector",
        [X],
        [probability, logits],
        initializer=[c10, c05, slice_starts, slice_ends, slice_axes],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", _OPSET)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def export_mock_detector(
    path: str | Path,
    *,
    feature_dim: int = 57,
    num_classes: int = _NUM_CLASSES,
    validate: bool = True,
) -> Path:
    """Build, validate, and write the mock detector ONNX model.

    Args:
        path: Output file path (``*.onnx``).
        feature_dim: Input feature dimension.
        num_classes: Number of output classes.
        validate: If True, run round-trip validation before writing.

    Returns:
        Absolute path of the written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    model = build_mock_detector_onnx(feature_dim=feature_dim, num_classes=num_classes)

    if validate:
        _validate_detector_onnx(model, feature_dim=feature_dim, num_classes=num_classes)

    onnx.save(model, str(path))
    return path.resolve()


def _validate_detector_onnx(
    model: onnx.ModelProto,
    *,
    feature_dim: int,
    num_classes: int,
) -> None:
    """Assert that ONNX output matches the Python mock within fp32 tolerance."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal(feature_dim).astype(np.float32)

    # Python mock reference
    prob_py, _, per_class_py = _mock_compute(x, num_classes)

    # ONNX inference
    sess = ort.InferenceSession(model.SerializeToString())
    x_batch = x[np.newaxis, :]  # (1, feature_dim)
    ort_outputs = sess.run(None, {"X": x_batch})
    prob_ort = float(ort_outputs[0][0])
    per_class_ort = ort_outputs[1][0]  # (num_classes,)

    if abs(prob_ort - prob_py) > 1e-4:
        raise ValueError(
            f"Detector ONNX probability mismatch: python={prob_py:.6f}, onnx={prob_ort:.6f}"
        )
    if not np.allclose(per_class_ort, per_class_py, atol=1e-4):
        raise ValueError(
            f"Detector ONNX logits mismatch: max_diff={np.abs(per_class_ort - per_class_py).max():.6f}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Forecaster ONNX export
# ──────────────────────────────────────────────────────────────────────────────


def build_mock_forecaster_onnx(
    *,
    lookback_bins: int = 20,
    feature_dim: int = 57,
    forecast_bins: int = 6,
    num_classes: int = _NUM_CLASSES,
) -> onnx.ModelProto:
    """Construct the mock forecaster ONNX graph.

    Computation mirrors :func:`mock_forecaster._mock_forecast_compute`:
      last_step  = H[:, -1:, :]
      intensity  = clip(reduce_mean(last_step, axis=2), min=0) tiled to (batch, forecast_bins)
      type_logits = zeros + class0_bias tiled to (batch, forecast_bins, num_classes)
      type_probs  = softmax(type_logits, axis=2)

    Args:
        lookback_bins: History length (bins).
        feature_dim: Feature dimension per bin.
        forecast_bins: Number of future bins.
        num_classes: Number of output classes.

    Returns:
        Validated ONNX ModelProto (opset 17).
    """
    # ── inputs / outputs ──────────────────────────────────────────────
    H = helper.make_tensor_value_info(
        "H", TensorProto.FLOAT, [None, lookback_bins, feature_dim]
    )
    intensity_out = helper.make_tensor_value_info(
        "intensity", TensorProto.FLOAT, [None, forecast_bins]
    )
    type_logits_out = helper.make_tensor_value_info(
        "type_logits", TensorProto.FLOAT, [None, forecast_bins, num_classes]
    )

    # ── initializers ──────────────────────────────────────────────────
    # Slice to get last timestep: starts=[-1], ends=[INT64_MAX], axes=[1]
    last_starts = numpy_helper.from_array(np.array([-1], dtype=np.int64), name="last_starts")
    last_ends = numpy_helper.from_array(np.array([_INT64_MAX], dtype=np.int64), name="last_ends")
    last_axes = numpy_helper.from_array(np.array([1], dtype=np.int64), name="last_axes")

    # Clip min value
    clip_min = numpy_helper.from_array(np.array(0.0, dtype=np.float32), name="clip_min")

    # Tile repeats for intensity: [1, forecast_bins]
    tile_intensity = numpy_helper.from_array(
        np.array([1, forecast_bins], dtype=np.int64), name="tile_intensity"
    )

    # Type logits base: shape (1, 1, num_classes), zeros + class0_bias at index 0
    type_base = np.zeros((1, 1, num_classes), dtype=np.float32)
    type_base[0, 0, 0] = 10.0  # large bias → class 0 dominates softmax
    type_logits_base = numpy_helper.from_array(type_base, name="type_logits_base")

    # Tile repeats for type_logits: [1, forecast_bins, 1]
    tile_type = numpy_helper.from_array(
        np.array([1, forecast_bins, 1], dtype=np.int64), name="tile_type"
    )

    # ── nodes for intensity ───────────────────────────────────────────
    # Slice H to get last timestep: H[:, -1:, :] → (batch, 1, feature_dim)
    slice_last = helper.make_node(
        "Slice",
        inputs=["H", "last_starts", "last_ends", "last_axes"],
        outputs=["last_step_3d"],
    )
    # ReduceMean over feature_dim (axis=2, keepdims=0): (batch, 1, feature_dim) → (batch, 1)
    reduce_feat = helper.make_node(
        "ReduceMean", inputs=["last_step_3d"], outputs=["mean_feat"], axes=[2], keepdims=0
    )
    # Clip to [0, inf)
    clip_node = helper.make_node(
        "Clip", inputs=["mean_feat", "clip_min"], outputs=["clipped_intensity"]
    )
    # Tile to (batch, forecast_bins)
    tile_intensity_node = helper.make_node(
        "Tile", inputs=["clipped_intensity", "tile_intensity"], outputs=["intensity"]
    )

    # ── nodes for type_logits ─────────────────────────────────────────
    # Tile type_logits_base (1, 1, num_classes) → (1, forecast_bins, num_classes)
    tile_type_node = helper.make_node(
        "Tile", inputs=["type_logits_base", "tile_type"], outputs=["tiled_type_logits_1"]
    )
    # We need (batch, forecast_bins, num_classes). Use Expand with dynamic shape from H.
    # Get batch size: Shape(H) → [batch, lookback, feature_dim], Gather index 0 → batch_scalar
    shape_H = helper.make_node("Shape", inputs=["H"], outputs=["H_shape"])
    batch_idx = numpy_helper.from_array(np.array(0, dtype=np.int64), name="batch_idx")
    gather_batch = helper.make_node(
        "Gather", inputs=["H_shape", "batch_idx"], outputs=["batch_scalar"], axis=0
    )
    # Unsqueeze → [batch_scalar]
    unsqueeze_axes = numpy_helper.from_array(np.array([0], dtype=np.int64), name="unsqueeze_axes")
    unsqueeze_batch = helper.make_node(
        "Unsqueeze", inputs=["batch_scalar", "unsqueeze_axes"], outputs=["batch_1d"]
    )
    # Build expand shape: concat([batch_1d, [forecast_bins, num_classes]])
    fc_shape = numpy_helper.from_array(
        np.array([forecast_bins, num_classes], dtype=np.int64), name="fc_shape"
    )
    concat_shape = helper.make_node(
        "Concat", inputs=["batch_1d", "fc_shape"], outputs=["expand_shape"], axis=0
    )
    # Expand
    expand_type = helper.make_node(
        "Expand", inputs=["tiled_type_logits_1", "expand_shape"], outputs=["type_logits"]
    )
    # Output type_logits pre-softmax (matches Python mock's raw_type_logits).
    # Callers can apply softmax on their side. The brief names this output "type_logits".

    # ── assemble graph ────────────────────────────────────────────────
    graph = helper.make_graph(
        [
            slice_last,
            reduce_feat,
            clip_node,
            tile_intensity_node,
            tile_type_node,
            shape_H,
            gather_batch,
            unsqueeze_batch,
            concat_shape,
            expand_type,
        ],
        "mock_forecaster",
        [H],
        [intensity_out, type_logits_out],
        initializer=[
            last_starts,
            last_ends,
            last_axes,
            clip_min,
            tile_intensity,
            type_logits_base,
            tile_type,
            batch_idx,
            unsqueeze_axes,
            fc_shape,
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", _OPSET)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def export_mock_forecaster(
    path: str | Path,
    *,
    lookback_bins: int = 20,
    feature_dim: int = 57,
    forecast_bins: int = 6,
    num_classes: int = _NUM_CLASSES,
    validate: bool = True,
) -> Path:
    """Build, validate, and write the mock forecaster ONNX model.

    Args:
        path: Output file path (``*.onnx``).
        lookback_bins: History length in bins.
        feature_dim: Feature dimension per bin.
        forecast_bins: Number of future bins.
        num_classes: Number of output classes.
        validate: If True, run round-trip validation before writing.

    Returns:
        Absolute path of the written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    model = build_mock_forecaster_onnx(
        lookback_bins=lookback_bins,
        feature_dim=feature_dim,
        forecast_bins=forecast_bins,
        num_classes=num_classes,
    )

    if validate:
        _validate_forecaster_onnx(
            model,
            lookback_bins=lookback_bins,
            feature_dim=feature_dim,
            forecast_bins=forecast_bins,
            num_classes=num_classes,
        )

    onnx.save(model, str(path))
    return path.resolve()


def _validate_forecaster_onnx(
    model: onnx.ModelProto,
    *,
    lookback_bins: int,
    feature_dim: int,
    forecast_bins: int,
    num_classes: int,
) -> None:
    """Assert that ONNX output matches the Python mock within fp32 tolerance."""
    rng = np.random.default_rng(1)
    h = rng.standard_normal((lookback_bins, feature_dim)).astype(np.float32)

    # Python mock reference
    intensity_py, type_logits_py, _, _ = _mock_forecast_compute(h, forecast_bins, num_classes)

    # ONNX inference (batch=1)
    sess = ort.InferenceSession(model.SerializeToString())
    h_batch = h[np.newaxis, :, :]  # (1, lookback_bins, feature_dim)
    ort_outputs = sess.run(None, {"H": h_batch})
    intensity_ort = ort_outputs[0][0]       # (forecast_bins,)
    type_logits_ort = ort_outputs[1][0]     # (forecast_bins, num_classes)

    if not np.allclose(intensity_ort, intensity_py, atol=1e-4):
        raise ValueError(
            f"Forecaster ONNX intensity mismatch: max_diff={np.abs(intensity_ort - intensity_py).max():.6f}"
        )
    if not np.allclose(type_logits_ort, type_logits_py, atol=1e-4):
        raise ValueError(
            f"Forecaster ONNX type_logits mismatch: max_diff={np.abs(type_logits_ort - type_logits_py).max():.6f}"
        )
