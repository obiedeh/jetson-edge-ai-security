"""MockDetector — deterministic, numpy-only, no ML framework required.

Used in CI and in environments where the [ml] extras are not installed.
Given the same input, always produces the same output (deterministic per input).

ONNX round-trip: the exported graph implements the identical computation, so
``MockDetector.predict(x)`` and the ONNX runtime on the same ``x`` agree
within fp32 tolerance.

Computation (documented for ONNX parity):
  Given features x of shape (feature_dim,) or (seq_len, feature_dim):
    1. If 2D, average over seq_len → x1d of shape (feature_dim,)
    2. prob = tanh(mean(x1d) / 10.0) * 0.5 + 0.5
    3. logits_raw = x1d[:num_classes]  (first num_classes features)
    4. per_class = softmax(logits_raw)
    5. attack_type = ATTACK_TYPES[argmax(per_class)]
"""

from __future__ import annotations

import time

import numpy as np

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import (
    DetectionResult,
    DetectorMetadata,
    _softmax,
)

_NUM_CLASSES: int = len(ATTACK_TYPES)  # 15


class MockDetector:
    """Deterministic mock detector — no GPU, no training required.

    Args:
        seed: Ignored (computation is fully deterministic per input, no RNG used
              at inference time). Present for API symmetry with real detectors.
        feature_dim: Expected input feature dimension (default 57, the binned
                     feature size including event_count).
    """

    def __init__(self, *, seed: int = 42, feature_dim: int = 57) -> None:
        self._feature_dim = feature_dim
        self.metadata = DetectorMetadata(
            name="mock-detector",
            version="1.0.0",
            architecture="mock",
            feature_dim=feature_dim,
            input_shape=(feature_dim,),
            output_classes=ATTACK_TYPES,
            onnx_path=None,
        )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, features: np.ndarray) -> DetectionResult:
        """Run mock inference.

        Args:
            features: float32 array of shape ``(feature_dim,)`` or
                ``(seq_len, feature_dim)``.

        Returns:
            :class:`DetectionResult` with latency measured.
        """
        t0 = time.perf_counter()
        x = features.astype(np.float32)

        # If 2D (seq_len, feature_dim), average over time axis
        if x.ndim == 2:
            x = x.mean(axis=0)

        prob, logits_raw, per_class = _mock_compute(x, _NUM_CLASSES)

        attack_idx = int(np.argmax(per_class))
        attack_type = ATTACK_TYPES[attack_idx]
        per_class_dict = {cls: float(p) for cls, p in zip(ATTACK_TYPES, per_class, strict=True)}

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return DetectionResult(
            probability=float(prob),
            attack_type=attack_type,
            per_class_probabilities=per_class_dict,
            latency_ms=latency_ms,
            model_metadata=self.metadata,
            raw_logits=per_class,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Shared computation (also used by export_onnx.py for parity verification)
# ──────────────────────────────────────────────────────────────────────────────


def _mock_compute(
    x1d: np.ndarray, num_classes: int = _NUM_CLASSES
) -> tuple[float, np.ndarray, np.ndarray]:
    """Core mock computation over a 1D feature vector.

    Args:
        x1d: 1D float32 array of shape (feature_dim,).
        num_classes: Number of output classes.

    Returns:
        ``(prob, logits_raw, per_class_probs)``
    """
    x1d = x1d.astype(np.float32)
    prob = float(np.tanh(x1d.mean() / np.float32(10.0)) * np.float32(0.5) + np.float32(0.5))
    logits_raw = x1d[:num_classes].astype(np.float32)
    per_class = _softmax(logits_raw)
    return prob, logits_raw, per_class
