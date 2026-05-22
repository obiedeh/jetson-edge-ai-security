"""Tests for the GBM reference Detector.

Acceptance criteria (§5 of implementation brief):
- GBC cross-val AUC > IsolationForest AUC by >= 0.05 on the 5k fixture
- GBMDetector output matches ONNX output within fp32 tolerance (atol=1e-4)
- Both exports pass onnxruntime round-trip
"""

from __future__ import annotations

import pickle
import tempfile
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "edge_iiotset_sample_5k.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_fixture():
    from jetson_edge_ai_security.datasets.edge_iiotset import (
        NUMERIC_FEATURE_COLS,
        load_edge_iiotset,
    )

    df = load_edge_iiotset(FIXTURE)
    X56 = df[NUMERIC_FEATURE_COLS].values.astype(np.float32)
    X = np.concatenate([X56, np.ones((len(df), 1), dtype=np.float32)], axis=1)
    y = df["attack_label"].values.astype(int)
    return X, y


# ──────────────────────────────────────────────────────────────────────────────
# Training gate — AUC delta >= 0.05
# ──────────────────────────────────────────────────────────────────────────────


def test_gbm_auc_beats_isolation_forest_by_gate_threshold():
    """GBC delta_AUC >= 0.05 — the Commit 2 performance gate."""
    from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    X, y = _load_fixture()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    if_scores = np.zeros(len(y))
    gbc_probs = np.zeros(len(y))

    for train_idx, val_idx in skf.split(X, y):
        contamination = float(min(0.49, max(0.01, y[train_idx].mean())))
        if_m = IsolationForest(contamination=contamination, n_estimators=100, random_state=42)
        if_m.fit(X[train_idx])
        if_scores[val_idx] = if_m.score_samples(X[val_idx])

        gbc = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, subsample=0.8, random_state=42
        )
        gbc.fit(X[train_idx], y[train_idx])
        gbc_probs[val_idx] = gbc.predict_proba(X[val_idx])[:, 1]

    if_auc = roc_auc_score(y, -if_scores)
    gbc_auc = roc_auc_score(y, gbc_probs)
    delta = gbc_auc - if_auc

    assert delta >= 0.05, (
        f"Gate FAIL: GBC AUC={gbc_auc:.4f} - IF AUC={if_auc:.4f} = {delta:.4f} < 0.05"
    )


def test_train_detector_script_gate_passes():
    """End-to-end: train_detector produces gate=PASS JSON."""
    from jetson_edge_ai_security.models.training.train_detector import train_detector

    with tempfile.TemporaryDirectory() as tmpdir:
        metrics = train_detector(
            dataset=FIXTURE,
            output_dir=Path(tmpdir),
            seed=42,
        )
    assert metrics["gate"]["result"] == "PASS", (
        f"train_detector gate FAIL: delta_auc={metrics['metrics']['delta_auc']}"
    )
    assert metrics["metrics"]["delta_auc"] >= 0.05


# ──────────────────────────────────────────────────────────────────────────────
# GBMDetector class
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def trained_model_dir(tmp_path_factory):
    """Train GBM detector and export ONNX to a temp dir."""
    tmpdir = tmp_path_factory.mktemp("gbm_model")
    from jetson_edge_ai_security.models.export_onnx import export_reference_detector
    from jetson_edge_ai_security.models.training.train_detector import train_detector

    train_detector(dataset=FIXTURE, output_dir=tmpdir, seed=42)
    export_reference_detector(tmpdir, validate=True)
    return tmpdir


def test_gbm_detector_loads(trained_model_dir):
    from jetson_edge_ai_security.models.detectors.gbm_detector import GBMDetector

    det = GBMDetector(
        model_path=trained_model_dir / "gbm_detector.pkl",
        onnx_path=trained_model_dir / "gbm_detector.onnx",
    )
    assert det.metadata.name == "gbm-detector"
    assert det.metadata.feature_dim == 57
    assert len(det.metadata.output_classes) == 15


def test_gbm_detector_predict_1d(trained_model_dir):
    from jetson_edge_ai_security.models.detectors.gbm_detector import GBMDetector
    from jetson_edge_ai_security.models.interfaces import DetectionResult

    det = GBMDetector(model_path=trained_model_dir / "gbm_detector.pkl")
    x = np.zeros(57, dtype=np.float32)
    result = det.predict(x)
    assert isinstance(result, DetectionResult)
    assert 0.0 <= result.probability <= 1.0
    assert abs(sum(result.per_class_probabilities.values()) - 1.0) < 1e-4


def test_gbm_detector_predict_2d_seq(trained_model_dir):
    """2D input (seq_len, feature_dim) should be mean-pooled."""
    from jetson_edge_ai_security.models.detectors.gbm_detector import GBMDetector

    det = GBMDetector(model_path=trained_model_dir / "gbm_detector.pkl")
    h = np.random.default_rng(5).standard_normal((20, 57)).astype(np.float32)
    result = det.predict(h)
    assert 0.0 <= result.probability <= 1.0


def test_gbm_detector_attack_type_valid(trained_model_dir):
    from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
    from jetson_edge_ai_security.models.detectors.gbm_detector import GBMDetector

    det = GBMDetector(model_path=trained_model_dir / "gbm_detector.pkl")
    x = np.ones(57, dtype=np.float32)
    result = det.predict(x)
    assert result.attack_type in ATTACK_TYPES


def test_gbm_detector_latency_non_negative(trained_model_dir):
    from jetson_edge_ai_security.models.detectors.gbm_detector import GBMDetector

    det = GBMDetector(model_path=trained_model_dir / "gbm_detector.pkl")
    result = det.predict(np.zeros(57, dtype=np.float32))
    assert result.latency_ms >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# ONNX round-trip
# ──────────────────────────────────────────────────────────────────────────────


def test_gbm_onnx_output_shapes(trained_model_dir):
    """ONNX model produces probability (batch,) and logits (batch, 15)."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_model_dir / "gbm_detector.onnx"))
    x = np.zeros((3, 57), dtype=np.float32)
    ort_out = sess.run(None, {"X": x})
    assert ort_out[0].shape == (3,)
    assert ort_out[1].shape == (3, 15)


def test_gbm_onnx_probability_range(trained_model_dir):
    """ONNX probability values in [0, 1]."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_model_dir / "gbm_detector.onnx"))
    rng = np.random.default_rng(99)
    for _ in range(10):
        x = rng.standard_normal((1, 57)).astype(np.float32)
        prob = sess.run(["probability"], {"X": x})[0][0]
        assert 0.0 <= prob <= 1.0


@pytest.mark.parametrize("seed", [0, 7, 42])
def test_gbm_onnx_matches_sklearn(trained_model_dir, seed):
    """ONNX probability must match sklearn predict_proba within atol=1e-4."""
    import onnxruntime as ort

    with (trained_model_dir / "gbm_detector.pkl").open("rb") as fh:
        clf = pickle.load(fh)  # noqa: S301

    sess = ort.InferenceSession(str(trained_model_dir / "gbm_detector.onnx"))
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((1, 57)).astype(np.float32)

    sklearn_prob = float(clf.predict_proba(x)[0, 1])
    ort_prob = float(sess.run(["probability"], {"X": x})[0][0])

    assert abs(ort_prob - sklearn_prob) < 1e-4, (
        f"seed={seed}: ONNX prob={ort_prob:.6f} vs sklearn prob={sklearn_prob:.6f}"
    )


def test_gbm_onnx_batch_gt1(trained_model_dir):
    """ONNX accepts batch > 1."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(trained_model_dir / "gbm_detector.onnx"))
    x = np.zeros((4, 57), dtype=np.float32)
    ort_out = sess.run(None, {"X": x})
    assert ort_out[0].shape == (4,)
    assert ort_out[1].shape == (4, 15)
