"""Evaluation helpers for the GBM reference Detector.

Computes AUC, F1, per-class FPR, and delta vs IsolationForest baseline.
Can be imported as a library or run as a CLI script.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold

log = logging.getLogger(__name__)


def eval_detector(
    dataset: Path,
    model_dir: Path,
    n_cv_splits: int = 5,
    seed: int = 42,
) -> dict:
    """Evaluate the GBM detector against the IsolationForest baseline.

    Returns a metrics dict with AUC, F1, delta_AUC, and gate result.
    """
    import pickle

    from jetson_edge_ai_security.datasets.edge_iiotset import (
        NUMERIC_FEATURE_COLS,
        load_edge_iiotset,
    )

    df = load_edge_iiotset(dataset)
    X56 = df[NUMERIC_FEATURE_COLS].values.astype(np.float32)
    X = np.concatenate(
        [X56, np.ones((len(df), 1), dtype=np.float32)],
        axis=1,
    )
    y = df["attack_label"].values.astype(int)

    pkl = model_dir / "gbm_detector.pkl"
    with pkl.open("rb") as fh:
        clf = pickle.load(fh)  # noqa: S301

    skf = StratifiedKFold(n_splits=n_cv_splits, shuffle=True, random_state=seed)
    if_scores = np.zeros(len(y))
    gbc_probs = np.zeros(len(y))

    for train_idx, val_idx in skf.split(X, y):
        contamination = float(min(0.49, max(0.01, y[train_idx].mean())))
        if_m = IsolationForest(contamination=contamination, n_estimators=100, random_state=seed)
        if_m.fit(X[train_idx])
        if_scores[val_idx] = if_m.score_samples(X[val_idx])
        gbc_probs[val_idx] = clf.predict_proba(X[val_idx])[:, 1]

    if_auc = roc_auc_score(y, -if_scores)
    gbc_auc = roc_auc_score(y, gbc_probs)
    delta_auc = gbc_auc - if_auc

    y_pred = (gbc_probs >= 0.5).astype(int)
    gbc_f1 = f1_score(y, y_pred, zero_division=0)

    # Per-class FPR (false positive rate per attack type)
    from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
    attack_types = df["attack_type"].values
    per_class_fpr: dict[str, float] = {}
    for cls in ATTACK_TYPES:
        mask = attack_types == cls
        if not mask.any():
            continue
        if cls == "Normal":
            # FPR = FP / (FP + TN) for Normal class
            tn = int(((y_pred == 0) & (y == 0)).sum())
            fp = int(((y_pred == 1) & (y == 0)).sum())
            fpr = fp / (fp + tn + 1e-9)
        else:
            # For attack classes: compute recall (not FPR — FPR is wrt negatives)
            # Use FPR as False Positive on this class's samples treated as positive
            tp = int(((y_pred == 1) & mask).sum())
            fn = int(((y_pred == 0) & mask).sum())
            fpr = fn / (tp + fn + 1e-9)  # miss-rate for this class
        per_class_fpr[cls] = round(float(fpr), 4)

    gate_pass = delta_auc >= 0.05
    return {
        "if_auc": round(if_auc, 4),
        "gbc_auc": round(gbc_auc, 4),
        "delta_auc": round(delta_auc, 4),
        "f1": round(gbc_f1, 4),
        "per_class_fpr": per_class_fpr,
        "gate": {
            "criterion": "delta_auc >= 0.05",
            "result": "PASS" if gate_pass else "FAIL",
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Evaluate GBM Detector")
    parser.add_argument("--dataset", type=Path,
                        default=Path("tests/fixtures/edge_iiotset_sample_5k.csv"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/exports"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    metrics = eval_detector(args.dataset, args.model_dir, seed=args.seed)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
