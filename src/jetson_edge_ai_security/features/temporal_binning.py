"""Temporal binning for Edge-IIoTset flows.

Converts a raw flow DataFrame (or stream of TelemetryEvents) into fixed-length
5-second bins and then into 20-bin sliding sequences suitable for temporal models.

Output shape: ``(n_sequences, seq_len=20, feature_dim=57)``
  - 56 numeric features averaged per bin
  - 1 ``event_count`` appended as the final feature
  - Total feature_dim = 57
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from jetson_edge_ai_security.datasets.edge_iiotset import ATTACK_TYPES, NUMERIC_FEATURE_COLS
from jetson_edge_ai_security.schemas import TelemetryEvent

# Final feature dimension: 56 numeric + event_count
BINNED_FEATURE_DIM: int = 57


def bin_dataframe(
    df: pd.DataFrame,
    *,
    bin_seconds: float = 5.0,
) -> pd.DataFrame:
    """Aggregate a normalized Edge-IIoTset DataFrame into fixed-width time bins.

    Each bin contains:
      - ``bin_start``: epoch float of the bin's left edge
      - one column per numeric feature (mean across events in the bin)
      - ``event_count``: number of events that fell in the bin
      - ``attack_label``: 1 if any event in the bin is an attack (bin max)
      - ``attack_type``: modal attack type for attack-positive bins, "Normal" otherwise

    Args:
        df: Normalized DataFrame from :func:`load_edge_iiotset`.
        bin_seconds: Width of each time bin in seconds (default 5).

    Returns:
        Binned DataFrame sorted by ``bin_start``.
    """
    if bin_seconds <= 0:
        raise ValueError(f"bin_seconds must be positive, got {bin_seconds}")
    if df.empty:
        return pd.DataFrame(
            columns=["bin_start"] + NUMERIC_FEATURE_COLS + ["event_count", "attack_label", "attack_type"]
        )

    ts = df["timestamp"].to_numpy(dtype=np.float64)
    t_min = ts.min()
    bin_idx = np.floor((ts - t_min) / bin_seconds).astype(np.int64)
    df = df.copy()
    df["_bin"] = bin_idx

    # Aggregate numeric features
    agg_numeric = df.groupby("_bin")[NUMERIC_FEATURE_COLS].mean()

    # Event count per bin
    agg_count = df.groupby("_bin").size().rename("event_count")

    # Attack label: max per bin (1 if any event is an attack)
    agg_label = df.groupby("_bin")["attack_label"].max()

    # Attack type: mode for attack-positive bins, "Normal" otherwise
    def _modal_attack_type(group: pd.Series) -> str:
        types = group.to_numpy(dtype=str)
        attack_types = types[types != "Normal"]
        if len(attack_types) == 0:
            return "Normal"
        vals, counts = np.unique(attack_types, return_counts=True)
        return str(vals[counts.argmax()])

    agg_type = df.groupby("_bin")["attack_type"].apply(_modal_attack_type)

    # Bin start timestamps
    bin_groups = df.groupby("_bin")["timestamp"].min().rename("bin_start")

    result = pd.concat([bin_groups, agg_numeric, agg_count, agg_label, agg_type], axis=1)
    result = result.reset_index(drop=True).sort_values("bin_start").reset_index(drop=True)
    return result


def make_sequences(
    binned: pd.DataFrame,
    *,
    seq_len: int = 20,
    stride: int = 1,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Create sliding sequences of binned features.

    Args:
        binned: Output of :func:`bin_dataframe`.
        seq_len: Number of bins per sequence (default 20 → 100 s of history).
        stride: Step between sequence start positions (default 1 → slide by 1 bin).

    Returns:
        A 3-tuple ``(X, y_label, y_type)`` where:
          - ``X``: ``(n_sequences, seq_len, 57)`` float32 array.
                   The 57 features are the 56 numeric columns + event_count.
          - ``y_label``: ``(n_sequences,)`` int32 binary attack labels (bin max).
          - ``y_type``: list of str, length n_sequences (modal attack type).
    """
    if binned.empty or len(binned) < seq_len:
        empty_x = np.empty((0, seq_len, BINNED_FEATURE_DIM), dtype=np.float32)
        empty_y = np.empty(0, dtype=np.int32)
        empty_t: list[str] = []
        return empty_x, empty_y, empty_t

    # Feature matrix: 56 numeric + event_count = 57
    feat_cols = NUMERIC_FEATURE_COLS + ["event_count"]
    feature_matrix = binned[feat_cols].to_numpy(dtype=np.float32)
    label_arr = binned["attack_label"].to_numpy(dtype=np.int32)
    type_arr = binned["attack_type"].to_numpy(dtype=object)

    n_bins = len(binned)
    n_seq = max(0, (n_bins - seq_len) // stride + 1)

    X = np.empty((n_seq, seq_len, BINNED_FEATURE_DIM), dtype=np.float32)
    y_label = np.empty(n_seq, dtype=np.int32)
    y_type: list[str] = []

    for i in range(n_seq):
        start = i * stride
        end = start + seq_len
        X[i] = feature_matrix[start:end]
        window_labels = label_arr[start:end]
        y_label[i] = int(window_labels.max())
        # Modal type for the sequence
        window_types = type_arr[start:end]
        attack_types_in_window = window_types[window_types != "Normal"]
        if len(attack_types_in_window) == 0:
            y_type.append("Normal")
        else:
            vals, counts = np.unique(attack_types_in_window, return_counts=True)
            y_type.append(str(vals[counts.argmax()]))

    return X, y_label, y_type


def bin_events(
    events: Iterable[TelemetryEvent],
    *,
    bin_seconds: float = 5.0,
) -> pd.DataFrame:
    """Bin a stream of :class:`TelemetryEvent` objects into time bins.

    Converts each event to a row, then delegates to :func:`bin_dataframe`.

    Args:
        events: Iterable of normalized TelemetryEvent objects.
        bin_seconds: Width of each time bin in seconds.

    Returns:
        Binned DataFrame (same schema as :func:`bin_dataframe`).
    """
    rows = []
    for ev in events:
        row: dict[str, object] = {
            "timestamp": ev.timestamp.timestamp(),
            "attack_label": int(ev.attack_label) if ev.attack_label is not None else 0,
            "attack_type": ev.attack_type if ev.attack_type in ATTACK_TYPES else "Normal",
        }
        # Map TelemetryEvent fields to numeric feature columns (best-effort)
        meta = ev.metadata
        row["frame_len"] = float(ev.packet_size or 0)
        row["tcp_srcport"] = float(ev.source_port or 0)
        row["tcp_dstport"] = float(ev.dest_port or 0)
        # Fill remaining features from metadata or zero
        for col in NUMERIC_FEATURE_COLS:
            if col not in row:
                row[col] = float(meta.get(col, 0.0))
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=["bin_start"] + NUMERIC_FEATURE_COLS + ["event_count", "attack_label", "attack_type"]
        )

    df = pd.DataFrame(rows)
    return bin_dataframe(df, bin_seconds=bin_seconds)


def sequences_from_events(
    events: Iterable[TelemetryEvent],
    *,
    bin_seconds: float = 5.0,
    seq_len: int = 20,
    stride: int = 1,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """End-to-end helper: events → binned → sequences.

    Returns the same ``(X, y_label, y_type)`` tuple as :func:`make_sequences`.
    """
    binned = bin_events(events, bin_seconds=bin_seconds)
    return make_sequences(binned, seq_len=seq_len, stride=stride)
