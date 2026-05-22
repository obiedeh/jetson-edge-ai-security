"""Tests for temporal binning — 5-second bins + 20-bin sequences → (n, 20, 57)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jetson_edge_ai_security.datasets.edge_iiotset import load_edge_iiotset
from jetson_edge_ai_security.features.temporal_binning import (
    BINNED_FEATURE_DIM,
    bin_dataframe,
    bin_events,
    make_sequences,
    sequences_from_events,
)
from jetson_edge_ai_security.schemas import TelemetryEvent

FIXTURE = Path(__file__).parent / "fixtures" / "edge_iiotset_sample_5k.csv"


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return load_edge_iiotset(FIXTURE)


@pytest.fixture(scope="module")
def binned(df: pd.DataFrame) -> pd.DataFrame:
    return bin_dataframe(df)


# ──────────────────────────────────────────────────────────────────────────────
# BINNED_FEATURE_DIM
# ──────────────────────────────────────────────────────────────────────────────


def test_binned_feature_dim_is_57() -> None:
    """56 numeric features + event_count = 57."""
    assert BINNED_FEATURE_DIM == 57


# ──────────────────────────────────────────────────────────────────────────────
# bin_dataframe
# ──────────────────────────────────────────────────────────────────────────────


def test_bin_dataframe_returns_dataframe(binned: pd.DataFrame) -> None:
    assert isinstance(binned, pd.DataFrame)
    assert len(binned) > 0


def test_bin_dataframe_has_event_count(binned: pd.DataFrame) -> None:
    assert "event_count" in binned.columns
    assert (binned["event_count"] > 0).all()


def test_bin_dataframe_has_bin_start(binned: pd.DataFrame) -> None:
    assert "bin_start" in binned.columns


def test_bin_dataframe_sorted_by_bin_start(binned: pd.DataFrame) -> None:
    assert (binned["bin_start"].diff().iloc[1:] >= 0).all()


def test_bin_dataframe_attack_label_binary(binned: pd.DataFrame) -> None:
    assert set(binned["attack_label"].unique()).issubset({0, 1})


def test_bin_dataframe_all_feature_cols_present(binned: pd.DataFrame) -> None:
    from jetson_edge_ai_security.datasets.edge_iiotset import NUMERIC_FEATURE_COLS
    missing = [c for c in NUMERIC_FEATURE_COLS if c not in binned.columns]
    assert missing == []


def test_bin_dataframe_empty_input() -> None:
    empty = pd.DataFrame(columns=["timestamp", "attack_label", "attack_type"])
    result = bin_dataframe(empty)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0


def test_bin_dataframe_invalid_bin_seconds(df: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        bin_dataframe(df, bin_seconds=-1.0)


def test_bin_dataframe_5s_bins_count(df: pd.DataFrame) -> None:
    """5000 rows over 250 s → ~50 bins of 5 s."""
    binned_5s = bin_dataframe(df, bin_seconds=5.0)
    # Fixture spans 250 s → expect 50 bins (within a small margin for rounding)
    assert 45 <= len(binned_5s) <= 55


def test_bin_dataframe_10s_bins_fewer(df: pd.DataFrame) -> None:
    """10-second bins should produce fewer rows than 5-second bins."""
    b5 = bin_dataframe(df, bin_seconds=5.0)
    b10 = bin_dataframe(df, bin_seconds=10.0)
    assert len(b10) < len(b5)


# ──────────────────────────────────────────────────────────────────────────────
# make_sequences — the critical acceptance criterion
# ──────────────────────────────────────────────────────────────────────────────


def test_sequence_shape_is_20_57(binned: pd.DataFrame) -> None:
    """Core acceptance: 5-second bins + 20-bin sequences → (n, 20, 57)."""
    X, y_label, y_type = make_sequences(binned, seq_len=20, stride=1)
    assert X.shape[1] == 20, f"Expected seq_len=20, got {X.shape[1]}"
    assert X.shape[2] == BINNED_FEATURE_DIM == 57, f"Expected feature_dim=57, got {X.shape[2]}"


def test_sequence_shape_from_fixture(df: pd.DataFrame) -> None:
    """End-to-end: fixture → 5-second bins → 20-bin sequences → (n, 20, 57)."""
    binned = bin_dataframe(df, bin_seconds=5.0)
    X, y_label, y_type = make_sequences(binned, seq_len=20, stride=1)
    assert X.ndim == 3
    assert X.shape[1] == 20
    assert X.shape[2] == 57


def test_sequence_dtype_float32(binned: pd.DataFrame) -> None:
    X, _, _ = make_sequences(binned)
    assert X.dtype == np.float32


def test_sequence_y_label_shape(binned: pd.DataFrame) -> None:
    X, y_label, y_type = make_sequences(binned)
    assert y_label.shape == (X.shape[0],)


def test_sequence_y_type_length(binned: pd.DataFrame) -> None:
    X, _, y_type = make_sequences(binned)
    assert len(y_type) == X.shape[0]


def test_sequence_deterministic(df: pd.DataFrame) -> None:
    """Same input always produces same output."""
    b = bin_dataframe(df, bin_seconds=5.0)
    X1, y1, t1 = make_sequences(b, seq_len=20, stride=1)
    X2, y2, t2 = make_sequences(b, seq_len=20, stride=1)
    assert np.array_equal(X1, X2)
    assert np.array_equal(y1, y2)
    assert t1 == t2


def test_sequence_stride_reduces_count(binned: pd.DataFrame) -> None:
    X_stride1, _, _ = make_sequences(binned, seq_len=20, stride=1)
    X_stride5, _, _ = make_sequences(binned, seq_len=20, stride=5)
    assert X_stride5.shape[0] < X_stride1.shape[0]


def test_sequence_empty_when_not_enough_bins() -> None:
    """Fewer bins than seq_len → empty output."""
    tiny = pd.DataFrame({
        "bin_start": [0.0, 5.0],
        **{col: [0.0, 0.0] for col in ["event_count", "attack_label", "attack_type"]},
    })
    from jetson_edge_ai_security.datasets.edge_iiotset import NUMERIC_FEATURE_COLS
    for col in NUMERIC_FEATURE_COLS:
        tiny[col] = 0.0
    X, y, t = make_sequences(tiny, seq_len=20, stride=1)
    assert X.shape[0] == 0


def test_sequence_n_count_formula(df: pd.DataFrame) -> None:
    """n_sequences = (n_bins - seq_len) // stride + 1."""
    binned = bin_dataframe(df, bin_seconds=5.0)
    n_bins = len(binned)
    seq_len, stride = 20, 1
    expected_n = (n_bins - seq_len) // stride + 1
    X, _, _ = make_sequences(binned, seq_len=seq_len, stride=stride)
    assert X.shape[0] == expected_n


# ──────────────────────────────────────────────────────────────────────────────
# bin_events (TelemetryEvent stream)
# ──────────────────────────────────────────────────────────────────────────────


def test_bin_events_from_telemetry_events() -> None:
    from datetime import UTC, datetime

    events = [
        TelemetryEvent(
            timestamp=datetime(2026, 1, 1, 0, 0, i, tzinfo=UTC),
            packet_size=100 + i,
            attack_label=(i >= 8),
            attack_type="DDoS_ICMP" if i >= 8 else "Normal",
        )
        for i in range(12)
    ]
    binned = bin_events(events, bin_seconds=5.0)
    assert isinstance(binned, pd.DataFrame)
    assert len(binned) >= 1
    assert "event_count" in binned.columns


def test_bin_events_empty() -> None:
    binned = bin_events([], bin_seconds=5.0)
    assert isinstance(binned, pd.DataFrame)
    assert len(binned) == 0


def test_sequences_from_events_shape() -> None:
    from datetime import UTC, datetime

    events = [
        TelemetryEvent(
            timestamp=datetime(2026, 1, 1, 0, i // 10, i % 10, tzinfo=UTC),
            packet_size=50,
            attack_label=False,
        )
        for i in range(300)  # 5 minutes of 1-per-second events → 60 bins → 41 sequences
    ]
    X, _, _ = sequences_from_events(events, bin_seconds=5.0, seq_len=20, stride=1)
    assert X.ndim == 3
    assert X.shape[1] == 20
    assert X.shape[2] == 57
