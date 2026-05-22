"""MockForecaster — deterministic, numpy-only, no ML framework required.

Used in CI and framework-free environments.

ONNX round-trip computation (documented for parity):
  Given history of shape (lookback_bins, feature_dim):
    1. last_step = history[-1]                        → (feature_dim,)
    2. base_intensity = clip(mean(last_step), 0, inf)  → scalar
    3. intensity = full(forecast_bins, base_intensity)  → (forecast_bins,)
    4. type_logits = zeros(forecast_bins, num_classes) + class0_bias
                   where class0_bias[0] = 10.0 (makes "Normal" dominant)
    5. per_class = softmax(type_logits, axis=-1)       → (forecast_bins, num_classes)
    6. predicted_attack_type_per_bin = ATTACK_TYPES[argmax(per_class, axis=-1)]
    7. probability = mean(intensity) (clipped to [0, 1] via tanh rescaling)
"""

from __future__ import annotations

import time

import numpy as np

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import (
    ForecasterMetadata,
    ForecastResult,
    _softmax,
)

_NUM_CLASSES: int = len(ATTACK_TYPES)  # 15


class MockForecaster:
    """Deterministic mock forecaster — no GPU, no training required.

    Args:
        seed: Ignored at inference time (fully deterministic per input).
        lookback_bins: Expected number of history bins (default 20).
        forecast_bins: Number of future bins to predict (default 6 → 30 s).
        bin_seconds: Seconds per bin (default 5).
        feature_dim: Feature dimension per bin (default 57).
    """

    def __init__(
        self,
        *,
        seed: int = 42,
        lookback_bins: int = 20,
        forecast_bins: int = 6,
        bin_seconds: int = 5,
        feature_dim: int = 57,
    ) -> None:
        self._forecast_bins = forecast_bins
        self._feature_dim = feature_dim
        self.metadata = ForecasterMetadata(
            name="mock-forecaster",
            version="1.0.0",
            architecture="mock",
            lookback_bins=lookback_bins,
            forecast_bins=forecast_bins,
            bin_seconds=bin_seconds,
            onnx_path=None,
        )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def forecast(self, history: np.ndarray) -> ForecastResult:
        """Produce a mock forecast.

        Args:
            history: Float32 array of shape ``(lookback_bins, feature_dim)``.

        Returns:
            :class:`ForecastResult` with latency measured.
        """
        t0 = time.perf_counter()
        h = history.astype(np.float32)
        if h.ndim != 2:
            raise ValueError(f"history must be 2D (lookback_bins, feature_dim), got shape {h.shape}")

        intensity, type_logits, per_class, type_per_bin = _mock_forecast_compute(
            h, self._forecast_bins, _NUM_CLASSES
        )

        # Overall probability: mean intensity rescaled to [0, 1]
        mean_intensity = float(intensity.mean())
        probability = float(np.tanh(mean_intensity / 10.0) * 0.5 + 0.5)

        # Dominant attack type across forecast horizon
        all_type_indices = np.array([ATTACK_TYPES.index(t) for t in type_per_bin])
        dominant_idx = int(np.bincount(all_type_indices).argmax())
        dominant_type = ATTACK_TYPES[dominant_idx]

        # Overall per_class: mean across forecast horizon
        mean_per_class_probs: dict[str, float] = {
            cls: float(per_class[:, i].mean())
            for i, cls in enumerate(ATTACK_TYPES)
        }

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return ForecastResult(
            probability=probability,
            attack_type=dominant_type,
            per_class_probabilities=mean_per_class_probs,
            forecast_horizon_bins=self._forecast_bins,
            predicted_attack_intensity=intensity,
            predicted_attack_type_per_bin=type_per_bin,
            latency_ms=latency_ms,
            model_metadata=self.metadata,
            raw_type_logits=type_logits,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Shared computation (also used by export_onnx.py for parity verification)
# ──────────────────────────────────────────────────────────────────────────────


# Bias added to class 0 in type_logits to make "Normal" the dominant prediction.
# Large enough that softmax assigns ~1.0 to class 0 after exp.
_CLASS0_BIAS: np.float32 = np.float32(10.0)


def _mock_forecast_compute(
    h: np.ndarray,
    forecast_bins: int,
    num_classes: int = _NUM_CLASSES,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Core mock forecast computation.

    Args:
        h: 2D float32 array (lookback_bins, feature_dim).
        forecast_bins: Number of future bins to predict.
        num_classes: Number of output classes.

    Returns:
        ``(intensity, type_logits, per_class, type_per_bin)`` where:
          - ``intensity``: (forecast_bins,) float32
          - ``type_logits``: (forecast_bins, num_classes) float32
          - ``per_class``: (forecast_bins, num_classes) float32 softmax probs
          - ``type_per_bin``: list[str] of length forecast_bins
    """
    h = h.astype(np.float32)
    last_step = h[-1]  # (feature_dim,)
    base_intensity = float(np.clip(last_step.mean(), 0.0, None))

    intensity = np.full(forecast_bins, base_intensity, dtype=np.float32)

    # Type logits: all zeros + large bias at class 0 → softmax ≈ [1, 0, 0, …]
    type_logits = np.zeros((forecast_bins, num_classes), dtype=np.float32)
    type_logits[:, 0] = _CLASS0_BIAS

    per_class = _softmax(type_logits)  # (forecast_bins, num_classes)

    type_indices = np.argmax(per_class, axis=-1)  # (forecast_bins,)
    type_per_bin = [ATTACK_TYPES[int(i)] for i in type_indices]

    return intensity, type_logits, per_class, type_per_bin
