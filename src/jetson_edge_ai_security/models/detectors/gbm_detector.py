"""GBM-based reference Detector.

Architecture: GradientBoostingClassifier (sklearn) trained on 57 binned features
(56 numeric + event_count) to produce a binary attack/normal probability.

The model is trained once from the Edge-IIoTset fixture or full dataset and persisted
as a pickle alongside its ONNX export. At inference time only onnxruntime is needed.
"""

from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES
from jetson_edge_ai_security.models.interfaces import (
    DetectionResult,
    DetectorMetadata,
    _softmax,
)

_NUM_CLASSES = len(ATTACK_TYPES)
_FEATURE_DIM = 57  # 56 numeric + event_count from temporal binning


class GBMDetector:
    """Gradient Boosting Machine binary detector.

    Wraps a trained sklearn GradientBoostingClassifier.  Accepts either a 1-D
    feature vector ``(feature_dim,)`` or a 2-D sequence
    ``(seq_len, feature_dim)`` — the latter is mean-pooled to 1-D before
    inference (matches the MockDetector convention).

    Parameters
    ----------
    model_path:
        Path to a pickled GradientBoostingClassifier (``model.pkl``).
    onnx_path:
        Optional path to the exported ONNX file for the latency badge.
    feature_dim:
        Expected number of input features (default 57).
    """

    def __init__(
        self,
        model_path: str | Path,
        onnx_path: str | Path | None = None,
        feature_dim: int = _FEATURE_DIM,
    ) -> None:
        self._feature_dim = feature_dim
        self._onnx_path = str(onnx_path) if onnx_path else None

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"GBMDetector model not found: {model_path}")

        with model_path.open("rb") as fh:
            self._clf = pickle.load(fh)  # noqa: S301

        self.metadata = DetectorMetadata(
            name="gbm-detector",
            version="1.0.0",
            architecture="GradientBoostingClassifier",
            feature_dim=feature_dim,
            input_shape=(feature_dim,),
            output_classes=ATTACK_TYPES,
            onnx_path=self._onnx_path,
        )

    # ------------------------------------------------------------------
    # Detector Protocol
    # ------------------------------------------------------------------

    def predict(self, features: np.ndarray) -> DetectionResult:
        """Run inference on a feature vector or sequence.

        Parameters
        ----------
        features:
            Shape ``(feature_dim,)`` or ``(seq_len, feature_dim)``.

        Returns
        -------
        DetectionResult
        """
        t0 = time.perf_counter()

        x = np.asarray(features, dtype=np.float32)
        if x.ndim == 2:
            x = x.mean(axis=0)
        if x.ndim != 1 or len(x) != self._feature_dim:
            raise ValueError(
                f"Expected shape ({self._feature_dim},) or (seq_len, {self._feature_dim}), "
                f"got {features.shape}"
            )

        prob: float = float(self._clf.predict_proba(x[np.newaxis, :])[0, 1])

        # Derive per-class probabilities: use softmax on the first _NUM_CLASSES
        # features, then rescale so the sum of attack-class probs equals ``prob``
        # and the Normal class gets (1 - prob).
        logits_raw = x[:_NUM_CLASSES]
        raw_softmax = _softmax(logits_raw.astype(np.float64))
        # rescale attack classes; fix Normal independently
        attack_sum = 1.0 - float(raw_softmax[0])  # sum of non-Normal in softmax
        if attack_sum > 1e-9:
            scale = prob / attack_sum
        else:
            scale = 0.0
        scaled = raw_softmax.copy()
        scaled[0] = 1.0 - prob           # Normal class
        scaled[1:] = raw_softmax[1:] * scale
        # renormalize to correct for float imprecision
        scaled = scaled / scaled.sum()
        per_class = {cls: float(p) for cls, p in zip(ATTACK_TYPES, scaled, strict=True)}

        attack_type = max(per_class, key=lambda k: per_class[k])

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return DetectionResult(
            probability=float(np.clip(prob, 0.0, 1.0)),
            attack_type=attack_type,
            per_class_probabilities=per_class,
            latency_ms=latency_ms,
            model_metadata=self.metadata,
            raw_logits=logits_raw,
        )


def load_gbm_detector(
    model_dir: str | Path,
    feature_dim: int = _FEATURE_DIM,
) -> GBMDetector:
    """Load a GBMDetector from *model_dir*.

    Expects ``model_dir/gbm_detector.pkl`` and optionally
    ``model_dir/gbm_detector.onnx``.
    """
    model_dir = Path(model_dir)
    pkl = model_dir / "gbm_detector.pkl"
    onnx = model_dir / "gbm_detector.onnx"
    return GBMDetector(
        model_path=pkl,
        onnx_path=onnx if onnx.exists() else None,
        feature_dim=feature_dim,
    )
