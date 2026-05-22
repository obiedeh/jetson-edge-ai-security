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
import onnx.helper as oh
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

# ──────────────────────────────────────────────────────────────────────────────
# Reference model ONNX export (skl2onnx-based)
# ──────────────────────────────────────────────────────────────────────────────


def export_reference_detector(
    model_dir: str | Path,
    *,
    feature_dim: int = 57,
    validate: bool = True,
) -> Path:
    """Export the trained GBM Detector to ONNX using skl2onnx.

    The ONNX model wraps the GBC binary probability and the softmax of the
    first ``num_classes`` input features to produce the same output interface
    as the mock detector::

        probability : (batch,)             — P(attack) from GBC
        logits      : (batch, num_classes) — softmax(X[:, :num_classes])

    Parameters
    ----------
    model_dir:
        Directory containing ``gbm_detector.pkl``.
    feature_dim:
        Input feature dimension (default 57).
    validate:
        If True, run an onnxruntime forward pass to confirm the export is
        loadable before writing.

    Returns
    -------
    Path to the written ``.onnx`` file.
    """
    import pickle

    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "skl2onnx is required for reference model export: pip install skl2onnx"
        ) from exc

    model_dir = Path(model_dir)
    pkl_path = model_dir / "gbm_detector.pkl"
    if not pkl_path.exists():
        raise FileNotFoundError(f"GBM model not found: {pkl_path}")

    with pkl_path.open("rb") as fh:
        clf = pickle.load(fh)  # noqa: S301

    # ── Base GBC ONNX (zipmap=False → clean ndarray probabilities)
    options = {type(clf): {"zipmap": False, "nocl": True}}
    gbc_onnx = convert_sklearn(
        clf,
        initial_types=[("X", FloatTensorType([None, feature_dim]))],
        target_opset=_OPSET,
        options=options,
    )

    # ── Wrap to produce probability (batch,) and logits (batch, num_classes)
    # GBC ONNX outputs: output_label (batch,), output_probability (batch, 2)
    # We want:
    #   probability  = output_probability[:, 1]         (P(attack))
    #   logits       = softmax(X[:, :num_classes])

    wrapped = _wrap_gbc_onnx(gbc_onnx, feature_dim=feature_dim, num_classes=_NUM_CLASSES)

    if validate:
        sess = ort.InferenceSession(wrapped.SerializeToString())
        x = np.zeros((1, feature_dim), dtype=np.float32)
        ort_out = sess.run(None, {"X": x})
        assert ort_out[0].shape == (1,), f"probability shape mismatch: {ort_out[0].shape}"
        assert ort_out[1].shape == (1, _NUM_CLASSES), f"logits shape: {ort_out[1].shape}"

    out_path = model_dir / "gbm_detector.onnx"
    with out_path.open("wb") as fh:
        fh.write(wrapped.SerializeToString())
    return out_path


def _wrap_gbc_onnx(
    gbc_model: onnx.ModelProto,
    feature_dim: int,
    num_classes: int,
) -> onnx.ModelProto:
    """Wrap a GBC ONNX graph to produce `probability` and `logits` outputs.

    Takes the sub-graph that produces ``output_probability (batch, 2)`` and
    extracts column 1 (P(attack)).  Computes ``logits = softmax(X[:, :num_classes])``.
    """
    import onnx.compose

    # --- Gather GBC probability sub-graph
    # We need to extract output_probability[:,1] from the GBC model.
    # Strategy: build a tiny wrapper graph that:
    #   1. Feeds X into the GBC model
    #   2. Gathers column 1 from output_probability
    #   3. Slices X[:, :num_classes] and applies Softmax

    # Include both standard and ML opsets required by GBC
    opset = [
        oh.make_opsetid("", _OPSET),
        oh.make_opsetid("ai.onnx.ml", 3),
    ]

    # Create initializers
    gather_idx = numpy_helper.from_array(
        np.array(1, dtype=np.int64), name="gather_idx"
    )
    slice_start = numpy_helper.from_array(
        np.array([0], dtype=np.int64), name="slice_start"
    )
    slice_end = numpy_helper.from_array(
        np.array([num_classes], dtype=np.int64), name="slice_end"
    )
    slice_axis = numpy_helper.from_array(
        np.array([1], dtype=np.int64), name="slice_axis"
    )

    # Inline the GBC nodes into our graph
    gbc_nodes = list(gbc_model.graph.node)
    gbc_inits = list(gbc_model.graph.initializer)

    # Identify the GBC's probability output (the (batch, 2) tensor)
    # When converted with zipmap=False the last graph output is named 'probabilities'
    gbc_prob_name = gbc_model.graph.output[-1].name  # typically 'probabilities'

    # Nodes for our wrapper:
    # 1. Gather column 1 from GBC probability output
    gather_node = oh.make_node(
        "Gather", inputs=[gbc_prob_name, "gather_idx"], outputs=["probability"], axis=1
    )
    # 2. Slice X[:, :num_classes]
    slice_node = oh.make_node(
        "Slice",
        inputs=["X", "slice_start", "slice_end", "slice_axis"],
        outputs=["x_sliced"],
    )
    # 3. Softmax on sliced features
    softmax_node = oh.make_node("Softmax", inputs=["x_sliced"], outputs=["logits"], axis=1)

    all_nodes = gbc_nodes + [gather_node, slice_node, softmax_node]
    all_inits = gbc_inits + [gather_idx, slice_start, slice_end, slice_axis]

    graph = oh.make_graph(
        nodes=all_nodes,
        name="gbm_detector",
        inputs=[
            oh.make_tensor_value_info("X", TensorProto.FLOAT, [None, feature_dim])
        ],
        outputs=[
            oh.make_tensor_value_info("probability", TensorProto.FLOAT, [None]),
            oh.make_tensor_value_info("logits", TensorProto.FLOAT, [None, num_classes]),
        ],
        initializer=all_inits,
    )

    model = oh.make_model(graph, opset_imports=opset)
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def export_reference_forecaster(
    model_dir: str | Path,
    *,
    lookback_bins: int = 20,
    forecast_bins: int = 6,
    feature_dim: int = 57,
    validate: bool = True,
) -> Path:
    """Export the trained AR Forecaster to ONNX.

    The ONNX model replicates the 64-dim feature extraction from the lookback
    window and feeds it through the Ridge pipeline (StandardScaler + Ridge),
    producing::

        intensity   : (batch, forecast_bins) — clipped scalar prediction tiled
        type_logits : (batch, forecast_bins, num_classes) — softmax on last-step features

    Parameters
    ----------
    model_dir:
        Directory containing ``ar_forecaster.pkl``.
    validate:
        If True, run a smoke forward pass before writing.
    """
    import pickle

    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "skl2onnx is required for reference model export: pip install skl2onnx"
        ) from exc

    model_dir = Path(model_dir)
    pkl_path = model_dir / "ar_forecaster.pkl"
    if not pkl_path.exists():
        raise FileNotFoundError(f"AR Forecaster model not found: {pkl_path}")

    with pkl_path.open("rb") as fh:
        pipeline = pickle.load(fh)  # noqa: S301

    # The pipeline takes a 64-dim feature vector (no multi-output; single target)
    _FEATURE_DIM_64 = 64
    pipeline_onnx = convert_sklearn(
        pipeline,
        initial_types=[("lag_feat", FloatTensorType([None, _FEATURE_DIM_64]))],
        target_opset=_OPSET,
    )

    # Build full graph: H (batch, 20, 57) → extract 64-dim features → ridge → tile
    wrapped = _wrap_ar_onnx(
        pipeline_onnx,
        lookback_bins=lookback_bins,
        forecast_bins=forecast_bins,
        feature_dim=feature_dim,
        num_classes=_NUM_CLASSES,
    )

    if validate:
        sess = ort.InferenceSession(wrapped.SerializeToString())
        h = np.zeros((1, lookback_bins, feature_dim), dtype=np.float32)
        ort_out = sess.run(None, {"H": h})
        assert ort_out[0].shape == (1, forecast_bins), f"intensity shape: {ort_out[0].shape}"
        assert ort_out[1].shape == (1, forecast_bins, _NUM_CLASSES), f"type_logits shape: {ort_out[1].shape}"

    out_path = model_dir / "ar_forecaster.onnx"
    with out_path.open("wb") as fh:
        fh.write(wrapped.SerializeToString())
    return out_path


def _wrap_ar_onnx(
    pipeline_onnx: onnx.ModelProto,
    lookback_bins: int,
    forecast_bins: int,
    feature_dim: int,
    num_classes: int,
) -> onnx.ModelProto:
    """Wrap the Ridge pipeline ONNX to accept (batch, lookback, feature_dim).

    Feature extraction (must match train_forecaster._build_lag_features):
      - last_step = H[:, -1, :]                    (batch, 57)
      - ec_series = H[:, :, 56]                    (batch, 20)
      - ec_mean   = mean(ec_series, axis=1)         (batch, 1)
      - ec_std    = std(ec_series, axis=1)           (batch, 1)
      - ec_last5  = H[:, -5:, 56]                  (batch, 5)
      - lag_feat  = concat([last_step, ec_mean, ec_std, ec_last5], axis=1)  (batch, 64)
    """
    opset = [
        oh.make_opsetid("", _OPSET),
        oh.make_opsetid("ai.onnx.ml", 1),
    ]

    # ── Initializers
    # Indices for gathering / slicing
    minus1 = numpy_helper.from_array(np.array([-1], dtype=np.int64), name="minus1")
    axis1 = numpy_helper.from_array(np.array([1], dtype=np.int64), name="axis1")
    axis2 = numpy_helper.from_array(np.array([2], dtype=np.int64), name="axis2")

    ec_col = numpy_helper.from_array(np.array(56, dtype=np.int64), name="ec_col")
    # Slice for last step: H[:, -1:, :]
    last_step_start = numpy_helper.from_array(np.array([-1], dtype=np.int64), name="last_step_start")
    last_step_end   = numpy_helper.from_array(np.array([_INT64_MAX], dtype=np.int64), name="last_step_end")

    # Slice for last 5 event counts: H[:, -5:, 56]
    ec5_start = numpy_helper.from_array(np.array([-5], dtype=np.int64), name="ec5_start")
    ec5_end   = numpy_helper.from_array(np.array([_INT64_MAX], dtype=np.int64), name="ec5_end")
    ec5_axis  = numpy_helper.from_array(np.array([1], dtype=np.int64), name="ec5_axis")

    # Slice for num_classes features (logits)
    nc_start = numpy_helper.from_array(np.array([0], dtype=np.int64), name="nc_start")
    nc_end   = numpy_helper.from_array(np.array([num_classes], dtype=np.int64), name="nc_end")
    nc_axis  = numpy_helper.from_array(np.array([1], dtype=np.int64), name="nc_axis")

    # Forecast bins reshape (for Tile)
    tile_reps_intensity = numpy_helper.from_array(
        np.array([1, forecast_bins], dtype=np.int64), name="tile_reps_intensity"
    )
    tile_reps_type = numpy_helper.from_array(
        np.array([1, forecast_bins, 1], dtype=np.int64), name="tile_reps_type"
    )
    clip_zero = numpy_helper.from_array(np.array(0.0, dtype=np.float32), name="clip_zero")
    clip_max  = numpy_helper.from_array(np.array(1e9, dtype=np.float32), name="clip_max")
    unsqueeze_axes = numpy_helper.from_array(np.array([1], dtype=np.int64), name="unsqueeze_axes")
    # For type_logits: unsqueeze at axis=1 → (batch, 1, num_classes), then tile axis=1 forecast_bins times
    unsqueeze_axes2 = numpy_helper.from_array(np.array([1], dtype=np.int64), name="unsqueeze_axes2")

    extra_inits = [
        minus1, axis1, axis2, ec_col,
        last_step_start, last_step_end,
        ec5_start, ec5_end, ec5_axis,
        nc_start, nc_end, nc_axis,
        tile_reps_intensity, tile_reps_type,
        clip_zero, clip_max, unsqueeze_axes, unsqueeze_axes2,
    ]

    # ── Feature extraction nodes
    nodes = []

    # 1. last_step = H[:, -1:, :] → squeeze axis 1 → (batch, 57)
    nodes.append(oh.make_node("Slice",
        inputs=["H", "last_step_start", "last_step_end", "axis1"],
        outputs=["last_step_3d"]))
    nodes.append(oh.make_node("Squeeze",
        inputs=["last_step_3d", "axis1"],
        outputs=["last_step"]))  # (batch, 57)

    # 2. ec_series = H[:, :, 56] → Gather on axis 2 → (batch, lookback)
    nodes.append(oh.make_node("Gather",
        inputs=["H", "ec_col"],
        outputs=["ec_series"], axis=2))  # (batch, lookback)

    # 3. ec_mean = mean(ec_series, axes=[1]) → (batch, 1)
    nodes.append(oh.make_node("ReduceMean",
        inputs=["ec_series"], outputs=["ec_mean"],
        axes=[1], keepdims=1))

    # 4. ec_std = std(ec_series) = sqrt(mean((x - mean)^2))
    nodes.append(oh.make_node("Sub",
        inputs=["ec_series", "ec_mean"], outputs=["ec_centered"]))
    nodes.append(oh.make_node("Mul",
        inputs=["ec_centered", "ec_centered"], outputs=["ec_sq"]))
    nodes.append(oh.make_node("ReduceMean",
        inputs=["ec_sq"], outputs=["ec_var"],
        axes=[1], keepdims=1))
    nodes.append(oh.make_node("Sqrt",
        inputs=["ec_var"], outputs=["ec_std"]))  # (batch, 1)

    # 5. ec_last5 = H[:, -5:, 56] → (batch, 5)
    nodes.append(oh.make_node("Slice",
        inputs=["H", "ec5_start", "ec5_end", "ec5_axis"],
        outputs=["ec_last5_3d"]))
    nodes.append(oh.make_node("Gather",
        inputs=["ec_last5_3d", "ec_col"],
        outputs=["ec_last5"], axis=2))  # (batch, 5)

    # 6. lag_feat = concat([last_step, ec_mean, ec_std, ec_last5], axis=1) → (batch, 64)
    nodes.append(oh.make_node("Concat",
        inputs=["last_step", "ec_mean", "ec_std", "ec_last5"],
        outputs=["lag_feat"], axis=1))

    # 7. Feed through the Ridge pipeline (inline pipeline nodes)
    # Rename pipeline input from 'lag_feat' (already that)
    pipeline_nodes = list(pipeline_onnx.graph.node)
    pipeline_inits = list(pipeline_onnx.graph.initializer)

    # Pipeline outputs 'variable' (scalar prediction per batch item, shape (batch, 1) or (batch,))
    # Get the actual output name from the pipeline ONNX
    pipeline_out_name = pipeline_onnx.graph.output[0].name
    nodes.extend(pipeline_nodes)

    # 8. Flatten to (batch,) if needed, then clip to [0, inf)
    # Some Ridge pipelines output (batch, 1); squeeze if so
    nodes.append(oh.make_node("Flatten",
        inputs=[pipeline_out_name], outputs=["ridge_flat"], axis=0))
    # ridge_flat is (1, batch) from Flatten axis=0 — wrong!
    # Use Reshape to (batch,) instead
    nodes.pop()  # remove Flatten

    nodes.append(oh.make_node("Reshape",
        inputs=[pipeline_out_name, "batch_shape_1d"],
        outputs=["ridge_1d"]))
    batch_shape_1d = numpy_helper.from_array(np.array([-1], dtype=np.int64), name="batch_shape_1d")
    extra_inits.append(batch_shape_1d)

    nodes.append(oh.make_node("Clip",
        inputs=["ridge_1d", "clip_zero", "clip_max"],
        outputs=["scalar_clipped"]))  # (batch,)

    # 9. Unsqueeze → (batch, 1) then Tile → (batch, forecast_bins) = intensity
    nodes.append(oh.make_node("Unsqueeze",
        inputs=["scalar_clipped", "unsqueeze_axes"],
        outputs=["scalar_2d"]))  # (batch, 1)
    nodes.append(oh.make_node("Tile",
        inputs=["scalar_2d", "tile_reps_intensity"],
        outputs=["intensity"]))  # (batch, forecast_bins)

    # 10. Type logits: softmax(last_step[:, :num_classes]) → (batch, num_classes)
    nodes.append(oh.make_node("Slice",
        inputs=["last_step", "nc_start", "nc_end", "nc_axis"],
        outputs=["feat_nc"]))  # (batch, num_classes)
    nodes.append(oh.make_node("Softmax",
        inputs=["feat_nc"], outputs=["type_logits_1step"],
        axis=1))  # (batch, num_classes)

    # 11. Unsqueeze → (batch, 1, num_classes) then Tile → (batch, forecast_bins, num_classes)
    nodes.append(oh.make_node("Unsqueeze",
        inputs=["type_logits_1step", "unsqueeze_axes2"],
        outputs=["type_logits_3d"]))  # (batch, 1, num_classes)
    nodes.append(oh.make_node("Tile",
        inputs=["type_logits_3d", "tile_reps_type"],
        outputs=["type_logits"]))  # (batch, forecast_bins, num_classes)

    all_inits = extra_inits + pipeline_inits

    graph = oh.make_graph(
        nodes=nodes,
        name="ar_forecaster",
        inputs=[
            oh.make_tensor_value_info("H", TensorProto.FLOAT, [None, lookback_bins, feature_dim])
        ],
        outputs=[
            oh.make_tensor_value_info("intensity", TensorProto.FLOAT, [None, forecast_bins]),
            oh.make_tensor_value_info("type_logits", TensorProto.FLOAT, [None, forecast_bins, num_classes]),
        ],
        initializer=all_inits,
    )

    model = oh.make_model(graph, opset_imports=opset)
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model
