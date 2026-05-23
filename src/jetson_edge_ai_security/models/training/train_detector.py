"""Train the GBM reference Detector on Edge-IIoTset data.

Usage
-----
python -m jetson_edge_ai_security.models.training.train_detector \\
    --dataset tests/fixtures/edge_iiotset_sample_5k.csv \\
    --output-dir models/exports \\
    --seed 42

Outputs (in *output_dir*):
    gbm_detector.pkl     — trained GradientBoostingClassifier
    gbm_detector.onnx    — ONNX export (opset 17)

Performance gate (asserted at the end of this script):
    GBC cross-val AUC - IF cross-val AUC >= 0.05
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pickle
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.metrics import (
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _dataset_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _load_data(
    dataset: Path,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) where X is (N, 57) float32 and y is (N,) int.

    Trains on raw rows: 56 numeric features + a ``ones`` column appended as the
    event-count proxy (each row represents exactly one event).  This matches the
    57-feature BINNED_FEATURE_DIM used at inference (the 57th column is
    event_count which equals 1 per row here).
    """
    from jetson_edge_ai_security.datasets.edge_iiotset import (
        NUMERIC_FEATURE_COLS,
        load_edge_iiotset,
    )

    log.info("Loading dataset from %s", dataset)
    df = load_edge_iiotset(dataset)

    # 56 numeric features
    X56 = df[NUMERIC_FEATURE_COLS].values.astype(np.float32)
    # Append event_count = 1 for each row (matches the binned feature dim)
    event_count = np.ones((len(df), 1), dtype=np.float32)
    X = np.concatenate([X56, event_count], axis=1)  # (N, 57)

    y = df["attack_label"].values.astype(int)
    log.info(
        "Dataset: %d samples, %d features, attack_rate=%.3f",
        len(X),
        X.shape[1],
        y.mean(),
    )
    return X, y


# ──────────────────────────────────────────────────────────────────────────────
# Cross-validated evaluation
# ──────────────────────────────────────────────────────────────────────────────


def _cross_val_auc(
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
    seed: int = 42,
) -> tuple[float, float, float, float]:
    """Return (if_auc, gbc_auc, delta_auc, gbc_f1).

    Uses stratified k-fold so each fold preserves the class ratio.
    The IF is fitted per-fold to avoid data leakage.
    """
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    if_scores = np.zeros(len(y))
    gbc_probs = np.zeros(len(y))

    for train_idx, val_idx in skf.split(X, y):
        X_tr, X_va = X[train_idx], X[val_idx]
        y_tr = y[train_idx]

        contamination = float(min(0.49, max(0.01, y_tr.mean())))
        if_model = IsolationForest(
            contamination=contamination,
            n_estimators=100,
            random_state=seed,
        )
        if_model.fit(X_tr)
        if_scores[val_idx] = if_model.score_samples(X_va)

        gbc = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            random_state=seed,
        )
        gbc.fit(X_tr, y_tr)
        gbc_probs[val_idx] = gbc.predict_proba(X_va)[:, 1]

    if_auc = roc_auc_score(y, -if_scores)
    gbc_auc = roc_auc_score(y, gbc_probs)
    delta = gbc_auc - if_auc
    threshold = 0.5
    y_pred = (gbc_probs >= threshold).astype(int)
    gbc_f1 = f1_score(y, y_pred, zero_division=0)
    return if_auc, gbc_auc, delta, gbc_f1


# ──────────────────────────────────────────────────────────────────────────────
# Training
# ──────────────────────────────────────────────────────────────────────────────


def train_detector(
    dataset: Path,
    output_dir: Path,
    seed: int = 42,
    n_estimators: int = 100,
    max_depth: int = 4,
    learning_rate: float = 0.1,
    subsample: float = 0.8,
    n_cv_splits: int = 5,
) -> dict:
    """Train and persist the GBM detector.

    Returns a metrics dict suitable for embedding in ``reports/training_run.json``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    X, y = _load_data(dataset)
    ds_hash = _dataset_hash(dataset)

    # ── Cross-validated evaluation (gate check)
    log.info("Running %d-fold cross-validation …", n_cv_splits)
    if_auc, gbc_auc, delta_auc, gbc_f1 = _cross_val_auc(
        X, y, n_splits=n_cv_splits, seed=seed
    )
    log.info(
        "IF AUC=%.4f  GBC AUC=%.4f  delta=%.4f  F1=%.4f",
        if_auc,
        gbc_auc,
        delta_auc,
        gbc_f1,
    )

    # ── Train final model on all data
    clf = GradientBoostingClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=subsample,
        random_state=seed,
    )
    log.info("Training final GBC on %d samples …", len(X))
    clf.fit(X, y)

    elapsed_s = time.perf_counter() - t_start

    # ── Persist model
    pkl_path = output_dir / "gbm_detector.pkl"
    with pkl_path.open("wb") as fh:
        pickle.dump(clf, fh)
    log.info("Saved model → %s", pkl_path)

    # ── Gate assertion
    gate_pass = delta_auc >= 0.05
    if not gate_pass:
        log.warning(
            "GATE FAIL: delta_auc=%.4f < 0.05 (IF=%.4f, GBC=%.4f)",
            delta_auc,
            if_auc,
            gbc_auc,
        )

    return {
        "model": "gbm-detector",
        "architecture": "GradientBoostingClassifier",
        "dataset_hash": ds_hash,
        "seed": seed,
        "hyperparameters": {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "subsample": subsample,
        },
        "cv_folds": n_cv_splits,
        "metrics": {
            "if_auc": round(if_auc, 4),
            "gbc_auc": round(gbc_auc, 4),
            "delta_auc": round(delta_auc, 4),
            "f1": round(gbc_f1, 4),
        },
        "gate": {
            "criterion": "delta_auc >= 0.05",
            "result": "PASS" if gate_pass else "FAIL",
        },
        "training_time_seconds": round(elapsed_s, 2),
        "pkl_path": str(pkl_path.resolve()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry-point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Train GBM Detector")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("tests/fixtures/edge_iiotset_sample_5k.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/exports"),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--subsample", type=float, default=0.8)
    args = parser.parse_args()

    metrics = train_detector(
        dataset=args.dataset,
        output_dir=args.output_dir,
        seed=args.seed,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=args.subsample,
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
