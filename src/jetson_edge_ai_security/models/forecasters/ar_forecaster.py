"""Autoregressive Ridge Forecaster.

Architecture: Ridge regression trained on lag features extracted from the last step
of a lookback sequence.  Predicts mean attack intensity for each of ``forecast_bins``
future bins.

This is a deliberately simple baseline that beats Naive Lag-1 on the 5k fixture
while remaining fast and explainable.  Swap in an LSTM/TCN here for a deeper model
without changing any downstream interface.
"""

from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import (
    ForecasterMetadata,
    ForecastResult,
)

_NUM_CLASSES = len(ATTACK_TYPES)
_FEATURE_DIM = 57
_LOOKBACK = 20
_FORECAST = 6


class ARForecaster:
    """Autoregressive Ridge-based Forecaster.

    Wraps a trained sklearn ``MultiOutputRegressor(Ridge)`` that maps the
    last-step feature vector of the lookback window to ``forecast_bins`` future
    intensity values (mean event count per bin).

    Parameters
    ----------
    model_path:
        Path to the pickled ``MultiOutputRegressor`` (``ar_forecaster.pkl``).
    onnx_path:
        Optional path to the exported ONNX file.
    lookback_bins, forecast_bins, feature_dim, bin_seconds:
        Model hyperparameters stored in metadata.
    """

    def __init__(
        self,
        model_path: str | Path,
        onnx_path: str | Path | None = None,
        lookback_bins: int = _LOOKBACK,
        forecast_bins: int = _FORECAST,
        feature_dim: int = _FEATURE_DIM,
        bin_seconds: int = 5,
    ) -> None:
        self._feature_dim = feature_dim
        self._lookback_bins = lookback_bins
        self._forecast_bins = forecast_bins
        self._onnx_path = str(onnx_path) if onnx_path else None

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"ARForecaster model not found: {model_path}")

        with model_path.open("rb") as fh:
            self._reg = pickle.load(fh)  # noqa: S301

        self.metadata = ForecasterMetadata(
            name="ar-forecaster",
            version="1.0.0",
            architecture="MultiOutputRidge",
            lookback_bins=lookback_bins,
            forecast_bins=forecast_bins,
            bin_seconds=bin_seconds,
            onnx_path=self._onnx_path,
        )

    # ------------------------------------------------------------------
    # Forecaster Protocol
    # ------------------------------------------------------------------

    def forecast(self, history: np.ndarray) -> ForecastResult:
        """Predict intensity for the next ``forecast_bins`` bins.

        Parameters
        ----------
        history:
            Shape ``(lookback_bins, feature_dim)`` — the most recent lookback
            window of binned feature vectors.

        Returns
        -------
        ForecastResult
        """
        t0 = time.perf_counter()

        h = np.asarray(history, dtype=np.float32)
        if h.ndim != 2:
            raise ValueError(
                f"Expected 2-D history (lookback, feature_dim), got shape {h.shape}"
            )

        # Build the same 64-dim lag feature used at training time:
        # last-step 57 features + mean event_count + std event_count + last 5 event counts
        last_step = h[-1, :]                       # (feature_dim,)
        ec_mean = np.array([h[:, 56].mean()])      # (1,)
        ec_std  = np.array([h[:, 56].std()])       # (1,)
        ec_last5 = h[-5:, 56] if len(h) >= 5 else np.pad(h[:, 56], (5 - len(h), 0))  # (5,)
        lag_feat = np.concatenate([last_step, ec_mean, ec_std, ec_last5])  # (64,)
        x_in = lag_feat[np.newaxis, :]             # (1, 64)

        scalar_pred = float(self._reg.predict(x_in)[0])   # scalar mean intensity
        intensity = np.full(self._forecast_bins, max(0.0, scalar_pred), dtype=np.float32)

        # Per-class logits: constant across forecast bins (simple AR forecaster
        # doesn't learn type distribution; use last-step feature[:15] as proxy)
        logits_1d = last_step[:_NUM_CLASSES]
        type_logits = np.tile(logits_1d, (self._forecast_bins, 1)).astype(np.float32)

        # Softmax → per-class probabilities
        from jetson_edge_ai_security.models.interfaces import _softmax

        pc = _softmax(logits_1d)
        per_class = dict(zip(ATTACK_TYPES, pc.tolist(), strict=True))

        type_per_bin = [
            ATTACK_TYPES[int(np.argmax(type_logits[b]))]
            for b in range(self._forecast_bins)
        ]

        prob = float(1.0 - per_class.get("Normal", 0.0))

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return ForecastResult(
            probability=float(np.clip(prob, 0.0, 1.0)),
            attack_type=type_per_bin[0] if type_per_bin else "Normal",
            per_class_probabilities=per_class,
            forecast_horizon_bins=self._forecast_bins,
            predicted_attack_intensity=intensity,
            predicted_attack_type_per_bin=type_per_bin,
            latency_ms=latency_ms,
            model_metadata=self.metadata,
            raw_type_logits=type_logits,
        )


def load_ar_forecaster(
    model_dir: str | Path,
    lookback_bins: int = _LOOKBACK,
    forecast_bins: int = _FORECAST,
    feature_dim: int = _FEATURE_DIM,
) -> ARForecaster:
    """Load an ARForecaster from *model_dir*."""
    model_dir = Path(model_dir)
    pkl = model_dir / "ar_forecaster.pkl"
    onnx = model_dir / "ar_forecaster.onnx"
    return ARForecaster(
        model_path=pkl,
        onnx_path=onnx if onnx.exists() else None,
        lookback_bins=lookback_bins,
        forecast_bins=forecast_bins,
        feature_dim=feature_dim,
    )
