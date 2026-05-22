"""Tests for the Edge-IIoTset dataset loader."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jetson_edge_ai_security.datasets.edge_iiotset import (
    ATTACK_TYPES,
    FEATURE_DIM,
    NUMERIC_FEATURE_COLS,
    feature_matrix,
    labels,
    load_edge_iiotset,
    time_aware_split,
)

FIXTURE = Path(__file__).parent / "fixtures" / "edge_iiotset_sample_5k.csv"


@pytest.fixture
def df() -> pd.DataFrame:
    return load_edge_iiotset(FIXTURE)


# ──────────────────────────────────────────────────────────────────────────────
# Basic loading
# ──────────────────────────────────────────────────────────────────────────────


def test_load_returns_dataframe(df: pd.DataFrame) -> None:
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5000


def test_all_numeric_feature_cols_present(df: pd.DataFrame) -> None:
    missing = [c for c in NUMERIC_FEATURE_COLS if c not in df.columns]
    assert missing == [], f"Missing columns: {missing}"


def test_feature_count(df: pd.DataFrame) -> None:
    assert len(NUMERIC_FEATURE_COLS) == FEATURE_DIM == 56


def test_timestamp_column_present(df: pd.DataFrame) -> None:
    assert "timestamp" in df.columns


def test_attack_label_binary(df: pd.DataFrame) -> None:
    unique_vals = set(df["attack_label"].unique())
    assert unique_vals.issubset({0, 1})


def test_attack_type_valid_classes(df: pd.DataFrame) -> None:
    unknown = df.loc[~df["attack_type"].isin(ATTACK_TYPES), "attack_type"].unique()
    assert len(unknown) == 0, f"Unknown attack types: {unknown}"


def test_no_nan_in_features(df: pd.DataFrame) -> None:
    nan_cols = [c for c in NUMERIC_FEATURE_COLS if df[c].isna().any()]
    assert nan_cols == [], f"NaN in columns: {nan_cols}"


def test_dtype_float32(df: pd.DataFrame) -> None:
    for col in NUMERIC_FEATURE_COLS:
        assert df[col].dtype == np.float32, f"Column {col} dtype is {df[col].dtype}"


def test_sorted_by_timestamp(df: pd.DataFrame) -> None:
    assert (df["timestamp"].diff().iloc[1:] >= 0).all(), "DataFrame not sorted by timestamp"


# ──────────────────────────────────────────────────────────────────────────────
# Column normalization (dot-notation → underscore)
# ──────────────────────────────────────────────────────────────────────────────


def test_raw_dot_notation_columns_normalized(tmp_path: Path) -> None:
    """Loader must normalize raw Edge-IIoTset dot-notation column names."""
    # Write a tiny CSV with dot-notation columns
    p = tmp_path / "mini.csv"
    p.write_text(
        "frame.time_epoch,frame.len,Attack_label,Attack_type\n"
        "1000.0,100,0,Normal\n"
        "1001.0,200,1,DDoS_ICMP\n",
        encoding="utf-8",
    )
    mini = load_edge_iiotset(p)
    assert "timestamp" in mini.columns
    assert "frame_len" in mini.columns
    assert "attack_label" in mini.columns
    assert list(mini["attack_label"]) == [0, 1]


def test_missing_columns_filled_with_zero(tmp_path: Path) -> None:
    """Columns absent from the CSV should appear in the normalized frame as 0."""
    p = tmp_path / "sparse.csv"
    p.write_text("timestamp,frame_len\n1000.0,64\n1001.0,128\n", encoding="utf-8")
    sparse = load_edge_iiotset(p)
    assert "ip_len" in sparse.columns
    assert (sparse["ip_len"] == 0).all()


def test_unknown_attack_type_defaults_to_normal(tmp_path: Path) -> None:
    p = tmp_path / "unknown.csv"
    p.write_text(
        "timestamp,frame_len,Attack_label,Attack_type\n"
        "1000.0,100,1,WeirdAttack\n",
        encoding="utf-8",
    )
    df = load_edge_iiotset(p)
    assert df.loc[0, "attack_type"] == "Normal"


# ──────────────────────────────────────────────────────────────────────────────
# Time-aware split
# ──────────────────────────────────────────────────────────────────────────────


def test_time_aware_split_sizes(df: pd.DataFrame) -> None:
    train, test = time_aware_split(df, train_ratio=0.8)
    assert len(train) + len(test) == len(df)
    assert abs(len(train) / len(df) - 0.8) < 0.01


def test_time_aware_split_no_overlap(df: pd.DataFrame) -> None:
    train, test = time_aware_split(df, train_ratio=0.8)
    # No shuffling: train timestamps must all be before test timestamps
    assert train["timestamp"].max() <= test["timestamp"].min()


def test_time_aware_split_invalid_ratio(df: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        time_aware_split(df, train_ratio=1.5)


# ──────────────────────────────────────────────────────────────────────────────
# feature_matrix and labels helpers
# ──────────────────────────────────────────────────────────────────────────────


def test_feature_matrix_shape(df: pd.DataFrame) -> None:
    X = feature_matrix(df)
    assert X.shape == (5000, FEATURE_DIM)
    assert X.dtype == np.float32


def test_labels_dict_keys(df: pd.DataFrame) -> None:
    lbl = labels(df)
    assert "attack_label" in lbl
    assert "attack_type" in lbl
    assert lbl["attack_label"].shape == (5000,)
    assert lbl["attack_type"].shape == (5000,)


def test_chunksize_loading() -> None:
    df_chunked = load_edge_iiotset(FIXTURE, chunksize=1000)
    assert len(df_chunked) == 5000
