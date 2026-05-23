"""Evaluation helpers for the AR reference Forecaster.

Computes MAE, RMSE, and % reduction vs Naive Lag-1 baseline.
Can be imported as a library or run as a CLI script.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def eval_forecaster(
    dataset: Path,
    model_dir: Path,
    lookback_bins: int = 20,
    forecast_bins: int = 6,
) -> dict:
    """Evaluate the AR Forecaster against the Naive Lag-1 baseline.

    Returns a metrics dict with lag1_mae, ridge_mae, reduction_pct, and gate result.
    """
    import pickle

    from jetson_edge_ai_security.datasets.edge_iiotset import load_edge_iiotset
    from jetson_edge_ai_security.features.temporal_binning import (
        bin_dataframe,
        make_sequences,
    )
    from jetson_edge_ai_security.models.training.train_forecaster import (
        _build_lag_features,
    )

    df = load_edge_iiotset(dataset)
    binned = bin_dataframe(df, bin_seconds=5.0)
    total_len = lookback_bins + forecast_bins
    X_all, _, _ = make_sequences(binned, seq_len=total_len, stride=1)

    X_look = X_all[:, :lookback_bins, :]
    X_fut  = X_all[:, lookback_bins:, :]
    X_feat = _build_lag_features(X_look)
    y_multi = np.clip(X_fut[:, :, 56], 0.0, None).astype(np.float32)
    lag1_val = np.clip(X_look[:, -1, 56], 0.0, None)
    lag1_pred = np.tile(lag1_val[:, None], (1, forecast_bins)).astype(np.float32)

    pkl = model_dir / "ar_forecaster.pkl"
    with pkl.open("rb") as fh:
        model = pickle.load(fh)  # noqa: S301

    # Evaluate on full dataset with the trained model
    scalar_pred = model.predict(X_feat)
    pred_tiled = np.tile(scalar_pred[:, None], (1, forecast_bins)).astype(np.float32)

    lag1_mae = float(np.abs(lag1_pred - y_multi).mean())
    lag1_rmse = float(np.sqrt(np.mean((lag1_pred - y_multi) ** 2)))
    ridge_mae = float(np.abs(pred_tiled - y_multi).mean())
    ridge_rmse = float(np.sqrt(np.mean((pred_tiled - y_multi) ** 2)))
    reduction = (lag1_mae - ridge_mae) / (lag1_mae + 1e-9)

    gate_pass = reduction >= 0.20
    return {
        "lag1_mae": round(lag1_mae, 6),
        "lag1_rmse": round(lag1_rmse, 6),
        "ridge_mae": round(ridge_mae, 6),
        "ridge_rmse": round(ridge_rmse, 6),
        "mae_reduction_pct": round(reduction * 100, 2),
        "gate": {
            "criterion": "mae_reduction_pct >= 20.0",
            "result": "PASS" if gate_pass else "FAIL",
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Evaluate AR Forecaster")
    parser.add_argument("--dataset", type=Path,
                        default=Path("tests/fixtures/edge_iiotset_sample_5k.csv"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/exports"))
    parser.add_argument("--lookback-bins", type=int, default=20)
    parser.add_argument("--forecast-bins", type=int, default=6)
    args = parser.parse_args()
    metrics = eval_forecaster(
        args.dataset, args.model_dir,
        lookback_bins=args.lookback_bins,
        forecast_bins=args.forecast_bins,
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
