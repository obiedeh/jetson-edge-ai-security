"""Model-agnostic Detector and Forecaster Protocol contracts.

These interfaces decouple the pipeline from any specific ML framework.
Commit 2 will add concrete implementations (1D-CNN, DNN, LSTM, LightGBM, …).
Commit 1 provides MockDetector and MockForecaster for CI and framework-free runs.

Note: ``DetectionResult`` and ``ForecastResult`` defined here are distinct from
``jetson_edge_ai_security.schemas.DetectionResult`` (the baseline-pipeline result
schema). Import from the appropriate module to avoid ambiguity.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES

# ──────────────────────────────────────────────────────────────────────────────
# Metadata models
# ──────────────────────────────────────────────────────────────────────────────


class DetectorMetadata(BaseModel):
    """Static metadata attached to a Detector implementation."""

    name: str
    version: str
    architecture: str  # informational: "1D-CNN", "DNN", "LSTM", "LightGBM", "mock", …
    feature_dim: int
    input_shape: tuple[int, ...]
    output_classes: list[str]  # exactly 15 entries: Normal + 14 attack families
    onnx_path: str | None = None


class ForecasterMetadata(BaseModel):
    """Static metadata attached to a Forecaster implementation."""

    name: str
    version: str
    architecture: str  # "LSTM", "TCN", "Transformer", "mock", …
    lookback_bins: int
    forecast_bins: int
    bin_seconds: int
    onnx_path: str | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Result models
# ──────────────────────────────────────────────────────────────────────────────


class DetectionResult(BaseModel):
    """Output of a Detector.predict() call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    probability: float = Field(..., ge=0.0, le=1.0, description="Binary attack confidence [0, 1]")
    attack_type: str = Field(..., description="Predicted attack class (one of 15)")
    per_class_probabilities: dict[str, float] = Field(
        default_factory=dict, description="Probability per output class"
    )
    latency_ms: float = Field(default=0.0, ge=0.0, description="Measured inference latency (ms)")
    model_metadata: DetectorMetadata = Field(..., description="Back-pointer to the model that produced this result")
    raw_logits: Any = Field(default=None, description="Raw logit array (numpy), if available")


class ForecastResult(BaseModel):
    """Output of a Forecaster.forecast() call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    probability: float = Field(..., ge=0.0, le=1.0, description="Overall attack confidence for the horizon")
    attack_type: str = Field(..., description="Dominant predicted attack type for the horizon")
    per_class_probabilities: dict[str, float] = Field(default_factory=dict)
    forecast_horizon_bins: int = Field(..., description="Number of bins in the forecast horizon")
    predicted_attack_intensity: Any = Field(
        ..., description="np.ndarray of shape (forecast_bins,) — predicted intensity per future bin"
    )
    predicted_attack_type_per_bin: list[str] = Field(
        ..., description="Predicted attack type per future bin"
    )
    latency_ms: float = Field(default=0.0, ge=0.0)
    model_metadata: ForecasterMetadata = Field(..., description="Back-pointer to the forecaster")
    raw_type_logits: Any = Field(
        default=None, description="Raw type logit array (numpy, shape forecast_bins × num_classes), if available"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Protocol contracts
# ──────────────────────────────────────────────────────────────────────────────


class Detector(Protocol):
    """Protocol that every Detector implementation must satisfy."""

    metadata: DetectorMetadata

    def predict(self, features: np.ndarray) -> DetectionResult:
        """Run inference on a single sample.

        Args:
            features: Float32 array of shape ``(feature_dim,)`` or
                ``(seq_len, feature_dim)``.

        Returns:
            :class:`DetectionResult` with measured latency.
        """
        ...


class Forecaster(Protocol):
    """Protocol that every Forecaster implementation must satisfy."""

    metadata: ForecasterMetadata

    def forecast(self, history: np.ndarray) -> ForecastResult:
        """Produce a forecast from a lookback window.

        Args:
            history: Float32 array of shape ``(lookback_bins, feature_dim)``.

        Returns:
            :class:`ForecastResult` with measured latency.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Timing helper
# ──────────────────────────────────────────────────────────────────────────────


def measure_latency_ms(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """Call *fn* with *args/kwargs* and return ``(result, elapsed_ms)``."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return result, elapsed_ms


# ──────────────────────────────────────────────────────────────────────────────
# Shared utilities
# ──────────────────────────────────────────────────────────────────────────────


def _softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax over the last axis."""
    shifted = x - x.max(axis=-1, keepdims=True)
    exp_x = np.exp(shifted)
    return exp_x / exp_x.sum(axis=-1, keepdims=True)


def _default_per_class(
    logits: np.ndarray,
    classes: list[str] = ATTACK_TYPES,
) -> dict[str, float]:
    probs = _softmax(logits.astype(np.float64))
    return {cls: float(p) for cls, p in zip(classes, probs, strict=True)}
