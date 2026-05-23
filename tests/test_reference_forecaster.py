"""Tests for the AR reference Forecaster.

Acceptance criteria (§5 of implementation brief):
- Ridge MAE reduction vs Naive Lag-1 >= 20% on the 5k fixture
- ARForecaster output matches ONNX output within fp32 tolerance (atol=1e-3)
- Both exports pass onnxruntime round-trip
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "edge_iiotset_sample_5k.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Training gate — MAE reduction >= 20%
# ──────────────────────────────────────────────────────────────────────────────


def test_ar_mae_reduction_beats_lag1_by_gate_threshold():
    """Ridge MAE reduction >= 20% vs Naive Lag-1 — the Commit 2 gate."""
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import LeaveOneOut
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    from jetson_edge_ai_security.datasets.edge_iiotset import load_edge_iiotset
    from jetson_edge_ai_security.features.temporal_binning import (
        bin_dataframe,
        make_sequences,
    )
    from jetson_edge_ai_security.models.training.train_forecaster import (
        _build_lag_features,
    )

    df = load_edge_iiotset(FIXTURE)
    binned = bin_dataframe(df, bin_seconds=5.0)
    X_all, _, _ = make_sequences(binned, seq_len=26, stride=1)

    X_look = X_all[:, :20, :]
    X_fut  = X_all[:, 20:, :]
    X_feat = _build_lag_features(X_look)
    y_multi = np.clip(X_fut[:, :, 56], 0.0, None).astype(np.float32)
    y_scalar = y_multi.mean(axis=1)
    lag1_val = np.clip(X_look[:, -1, 56], 0.0, None)
    lag1_pred = np.tile(lag1_val[:, None], (1, 6)).astype(np.float32)

    loo = LeaveOneOut()
    pred_scalar = np.zeros(len(y_scalar))
    for tr, va in loo.split(X_feat):
        pipe = Pipeline([("sc", StandardScaler()), ("ridge", Ridge(alpha=0.1))])
        pipe.fit(X_feat[tr], y_scalar[tr])
        pred_scalar[va] = pipe.predict(X_feat[va])

    pred_tiled = np.tile(pred_scalar[:, None], (1, 6))
    lag1_mae = float(np.abs(lag1_pred - y_multi).mean())
    ridge_mae = float(np.abs(pred_tiled - y_multi).mean())
    reduction = (lag1_mae - ridge_mae) / (lag1_mae + 1e-9)

    assert reduction >= 0.20, (
        f"Gate FAIL: MAE reduction={reduction * 100:.1f}% < 20%  "
        f"(lag1={lag1_mae:.4f}, ridge={ridge_mae:.4f})"
    )


def test_train_forecaster_script_gate_passes():
    """End-to-end: train_forecaster produces gate=PASS JSON."""
    from jetson_edge_ai_security.models.training.train_forecaster import train_forecaster

    with tempfile.TemporaryDirectory() as tmpdir:
        metrics = train_forecaster(
            dataset=FIXTURE,
            output_dir=Path(tmpdir),
            seed=42,
        )
    assert metrics["gate"]["result"] == "PASS", (
        f"train_forecaster gate FAIL: reduction={metrics['metrics']['mae_reduction_pct']}%"
    )
    assert metrics["metrics"]["mae_reduction_pct"] >= 20.0


# ──────────────────────────────────────────────────────────────────────────────
# ARForecaster class
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def trained_forecaster_dir(tmp_path_factory):
    tmpdir = tmp_path_factory.mktemp("ar_model")
    from jetson_edge_ai_security.models.export_onnx import export_reference_forecaster
    from jetson_edge_ai_security.models.training.train_forecaster import train_forecaster

    train_forecaster(dataset=FIXTURE, output_dir=tmpdir, seed=42)
    export_reference_forecaster(tmpdir, validate=True)
    return tmpdir


def test_ar_forecaster_loads(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    assert fcast.metadata.name == "ar-forecaster"
    assert fcast.metadata.lookback_bins == 20
    assert fcast.metadata.forecast_bins == 6


def test_ar_forecaster_forecast_returns_result(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster
    from jetson_edge_ai_security.models.interfaces import ForecastResult

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    h = np.zeros((20, 57), dtype=np.float32)
    result = fcast.forecast(h)
    assert isinstance(result, ForecastResult)


def test_ar_forecaster_intensity_shape(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    h = np.zeros((20, 57), dtype=np.float32)
    result = fcast.forecast(h)
    assert np.asarray(result.predicted_attack_intensity).shape == (6,)


def test_ar_forecaster_type_per_bin_length(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    h = np.zeros((20, 57), dtype=np.float32)
    result = fcast.forecast(h)
    assert len(result.predicted_attack_type_per_bin) == 6


def test_ar_forecaster_probability_range(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    rng = np.random.default_rng(3)
    for _ in range(10):
        h = rng.standard_normal((20, 57)).astype(np.float32)
        result = fcast.forecast(h)
        assert 0.0 <= result.probability <= 1.0


def test_ar_forecaster_requires_2d_input(trained_forecaster_dir):
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    with pytest.raises(ValueError):
        fcast.forecast(np.zeros(57, dtype=np.float32))


def test_ar_forecaster_attack_type_valid(trained_forecaster_dir):
    from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    h = np.random.default_rng(9).standard_normal((20, 57)).astype(np.float32)
    result = fcast.forecast(h)
    for t in result.predicted_attack_type_per_bin:
        assert t in ATTACK_TYPES


# ──────────────────────────────────────────────────────────────────────────────
# ONNX round-trip
# ──────────────────────────────────────────────────────────────────────────────


def test_ar_onnx_output_shapes(trained_forecaster_dir):
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_forecaster_dir / "ar_forecaster.onnx"))
    h = np.zeros((2, 20, 57), dtype=np.float32)
    ort_out = sess.run(None, {"H": h})
    assert ort_out[0].shape == (2, 6), f"intensity shape: {ort_out[0].shape}"
    assert ort_out[1].shape == (2, 6, 15), f"type_logits shape: {ort_out[1].shape}"


def test_ar_onnx_intensity_non_negative(trained_forecaster_dir):
    """Positive input → non-negative intensity."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_forecaster_dir / "ar_forecaster.onnx"))
    h = np.ones((1, 20, 57), dtype=np.float32) * 5.0
    ort_out = sess.run(["intensity"], {"H": h})
    assert (ort_out[0] >= 0).all()


def test_ar_onnx_batch_gt1(trained_forecaster_dir):
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_forecaster_dir / "ar_forecaster.onnx"))
    h = np.zeros((4, 20, 57), dtype=np.float32)
    ort_out = sess.run(None, {"H": h})
    assert ort_out[0].shape == (4, 6)
    assert ort_out[1].shape == (4, 6, 15)


@pytest.mark.parametrize("seed", [0, 7, 42])
def test_ar_onnx_matches_python(trained_forecaster_dir, seed):
    """ONNX intensity must match ARForecaster.forecast within atol=1e-3."""
    import onnxruntime as ort

    from jetson_edge_ai_security.models.forecasters.ar_forecaster import ARForecaster

    fcast = ARForecaster(model_path=trained_forecaster_dir / "ar_forecaster.pkl")
    sess = ort.InferenceSession(str(trained_forecaster_dir / "ar_forecaster.onnx"))

    rng = np.random.default_rng(seed)
    h = rng.standard_normal((20, 57)).astype(np.float32)

    py_result = fcast.forecast(h)
    ort_out = sess.run(None, {"H": h[np.newaxis, :, :]})
    intensity_ort = ort_out[0][0]

    np.testing.assert_allclose(
        intensity_ort,
        np.asarray(py_result.predicted_attack_intensity),
        atol=1e-3,
        err_msg=f"seed={seed}: ONNX intensity mismatch",
    )
