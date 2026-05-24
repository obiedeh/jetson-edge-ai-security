"""Edge-IIoTset dataset loader with column normalization and time-aware split.

The Edge-IIoTset dataset (https://ieee-dataport.org/open-access/edge-iiotset-...)
contains network telemetry captured in an IIoT testbed. This module handles the
DNN-EdgeIIoT partition and compatible subsets.

Manual download required — see docs/datasets.md for instructions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# 15 traffic classes: Normal + 14 attack families from Edge-IIoTset
ATTACK_TYPES: list[str] = [
    "Normal",
    "DDoS_ICMP",
    "DDoS_UDP",
    "DDoS_TCP",
    "DDoS_HTTP",
    "Uploading",
    "Downloading",
    "SQL_Injection",
    "Password",
    "Vulnerability_scanner",
    "Backdoor",
    "Port_Scanning",
    "XSS",
    "Ransomware",
    "MITM",
]

FEATURE_DIM: int = 56  # numeric features before event_count is appended

# 56 numeric feature columns — internal (underscore) names
NUMERIC_FEATURE_COLS: list[str] = [
    "frame_len",
    "ip_hdr_len",
    "ip_len",
    "ip_ttl",
    "ip_proto",
    "ip_flags_df",
    "ip_flags_mf",
    "tcp_srcport",
    "tcp_dstport",
    "tcp_seq",
    "tcp_ack",
    "tcp_hdr_len",
    "tcp_window_size",
    "tcp_flags_ack",
    "tcp_flags_push",
    "tcp_flags_reset",
    "tcp_flags_syn",
    "tcp_flags_fin",
    "tcp_flags_urg",
    "tcp_time_delta",
    "tcp_bytes_in_flight",
    "udp_srcport",
    "udp_dstport",
    "udp_length",
    "udp_time_delta",
    "icmp_type",
    "icmp_code",
    "arp_opcode",
    "arp_hw_size",
    "arp_proto_size",
    "dns_qry_type",
    "dns_count_queries",
    "dns_count_answers",
    "http_method",
    "http_content_length",
    "http_request_uri_length",
    "mqtt_msgtype",
    "mqtt_len",
    "mqtt_topic_len",
    "mqtt_payload_len",
    "mqtt_qos",
    "mqtt_retain",
    "flow_duration",
    "flow_bytes_per_second",
    "flow_packets_per_second",
    "flow_bytes_per_packet",
    "flow_iat_mean",
    "flow_iat_std",
    "flow_iat_max",
    "flow_iat_min",
    "fwd_packet_length_mean",
    "fwd_packet_length_std",
    "bwd_packet_length_mean",
    "bwd_packet_length_std",
    "active_mean",
    "idle_mean",
]

assert len(NUMERIC_FEATURE_COLS) == FEATURE_DIM

# Mapping: raw Edge-IIoTset CSV column names → internal underscore names
_COL_MAP: dict[str, str] = {
    # frame
    "frame.len": "frame_len",
    "frame_len": "frame_len",
    # ip
    "ip.hdr_len": "ip_hdr_len",
    "ip_hdr_len": "ip_hdr_len",
    "ip.len": "ip_len",
    "ip_len": "ip_len",
    "ip.ttl": "ip_ttl",
    "ip_ttl": "ip_ttl",
    "ip.proto": "ip_proto",
    "ip_proto": "ip_proto",
    "ip.flags.df": "ip_flags_df",
    "ip_flags_df": "ip_flags_df",
    "ip.flags.mf": "ip_flags_mf",
    "ip_flags_mf": "ip_flags_mf",
    # tcp
    "tcp.srcport": "tcp_srcport",
    "tcp_srcport": "tcp_srcport",
    "tcp.dstport": "tcp_dstport",
    "tcp_dstport": "tcp_dstport",
    "tcp.seq": "tcp_seq",
    "tcp_seq": "tcp_seq",
    "tcp.ack": "tcp_ack",
    "tcp_ack": "tcp_ack",
    "tcp.hdr_len": "tcp_hdr_len",
    "tcp_hdr_len": "tcp_hdr_len",
    "tcp.window_size_value": "tcp_window_size",
    "tcp_window_size": "tcp_window_size",
    "tcp.flags.ack": "tcp_flags_ack",
    "tcp_flags_ack": "tcp_flags_ack",
    "tcp.flags.push": "tcp_flags_push",
    "tcp_flags_push": "tcp_flags_push",
    "tcp.flags.reset": "tcp_flags_reset",
    "tcp_flags_reset": "tcp_flags_reset",
    "tcp.flags.syn": "tcp_flags_syn",
    "tcp_flags_syn": "tcp_flags_syn",
    "tcp.flags.fin": "tcp_flags_fin",
    "tcp_flags_fin": "tcp_flags_fin",
    "tcp.flags.urg": "tcp_flags_urg",
    "tcp_flags_urg": "tcp_flags_urg",
    "tcp.time_delta": "tcp_time_delta",
    "tcp_time_delta": "tcp_time_delta",
    "tcp.bytes_in_flight": "tcp_bytes_in_flight",
    "tcp_bytes_in_flight": "tcp_bytes_in_flight",
    # udp
    "udp.srcport": "udp_srcport",
    "udp_srcport": "udp_srcport",
    "udp.dstport": "udp_dstport",
    "udp_dstport": "udp_dstport",
    "udp.length": "udp_length",
    "udp_length": "udp_length",
    "udp.time_delta": "udp_time_delta",
    "udp_time_delta": "udp_time_delta",
    # icmp
    "icmp.type": "icmp_type",
    "icmp_type": "icmp_type",
    "icmp.code": "icmp_code",
    "icmp_code": "icmp_code",
    # arp
    "arp.opcode": "arp_opcode",
    "arp_opcode": "arp_opcode",
    "arp.hw.size": "arp_hw_size",
    "arp_hw_size": "arp_hw_size",
    "arp.proto.size": "arp_proto_size",
    "arp_proto_size": "arp_proto_size",
    # dns
    "dns.qry.type": "dns_qry_type",
    "dns_qry_type": "dns_qry_type",
    "dns.count.queries": "dns_count_queries",
    "dns_count_queries": "dns_count_queries",
    "dns.count.answers": "dns_count_answers",
    "dns_count_answers": "dns_count_answers",
    # http
    "http.request.method": "http_method",
    "http_method": "http_method",
    "http.content_length": "http_content_length",
    "http_content_length": "http_content_length",
    "http.request.uri.length": "http_request_uri_length",
    "http_request_uri_length": "http_request_uri_length",
    # mqtt
    "mqtt.msgtype": "mqtt_msgtype",
    "mqtt_msgtype": "mqtt_msgtype",
    "mqtt.len": "mqtt_len",
    "mqtt_len": "mqtt_len",
    "mqtt.topic_len": "mqtt_topic_len",
    "mqtt_topic_len": "mqtt_topic_len",
    "mqtt.payload_len": "mqtt_payload_len",
    "mqtt_payload_len": "mqtt_payload_len",
    "mqtt.qos": "mqtt_qos",
    "mqtt_qos": "mqtt_qos",
    "mqtt.retain": "mqtt_retain",
    "mqtt_retain": "mqtt_retain",
    # flow
    "flow.duration": "flow_duration",
    "flow_duration": "flow_duration",
    "flow.bytes_per_second": "flow_bytes_per_second",
    "flow_bytes_per_second": "flow_bytes_per_second",
    "flow.packets_per_second": "flow_packets_per_second",
    "flow_packets_per_second": "flow_packets_per_second",
    "flow.bytes_per_packet": "flow_bytes_per_packet",
    "flow_bytes_per_packet": "flow_bytes_per_packet",
    "flow.iat.mean": "flow_iat_mean",
    "flow_iat_mean": "flow_iat_mean",
    "flow.iat.std": "flow_iat_std",
    "flow_iat_std": "flow_iat_std",
    "flow.iat.max": "flow_iat_max",
    "flow_iat_max": "flow_iat_max",
    "flow.iat.min": "flow_iat_min",
    "flow_iat_min": "flow_iat_min",
    # forward / backward packet length
    "fwd_packet_length_mean": "fwd_packet_length_mean",
    "fwd_packet_length_std": "fwd_packet_length_std",
    "bwd_packet_length_mean": "bwd_packet_length_mean",
    "bwd_packet_length_std": "bwd_packet_length_std",
    # active / idle
    "active.mean": "active_mean",
    "active_mean": "active_mean",
    "idle.mean": "idle_mean",
    "idle_mean": "idle_mean",
    # timestamp
    "frame.time_epoch": "timestamp",
    "frame_time_epoch": "timestamp",
    "timestamp": "timestamp",
    # labels
    "Attack_label": "attack_label",
    "attack_label": "attack_label",
    "Attack_type": "attack_type",
    "attack_type": "attack_type",
}


# ──────────────────────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────────────────────


def load_edge_iiotset(
    path: str | Path,
    *,
    chunksize: int | None = None,
) -> pd.DataFrame:
    """Load and normalize an Edge-IIoTset CSV (or compatible subset).

    Args:
        path: Path to the CSV file.
        chunksize: If set, read in chunks (returns a concatenated DataFrame).

    Returns:
        Normalized DataFrame with columns:
          - ``timestamp`` (float, seconds since epoch)
          - all 56 numeric feature columns (float32, NaN → 0)
          - ``attack_label`` (int, 0 or 1)
          - ``attack_type`` (str, one of ATTACK_TYPES)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Edge-IIoTset CSV not found: {path}")

    if chunksize:
        chunks: list[pd.DataFrame] = []
        for chunk in pd.read_csv(path, chunksize=chunksize, low_memory=False):
            chunks.append(_normalize_df(chunk))
        df = pd.concat(chunks, ignore_index=True)
    else:
        df = pd.read_csv(path, low_memory=False)
        df = _normalize_df(df)

    return df


def _normalize_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename columns, coerce types, and fill missing features with 0."""
    # Rename known columns
    rename_map = {c: _COL_MAP[c] for c in raw.columns if c in _COL_MAP}
    df = raw.rename(columns=rename_map)

    # Ensure timestamp column exists (default to row index as float)
    if "timestamp" not in df.columns:
        df["timestamp"] = df.index.astype(float)
    else:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0.0)

    # Ensure all numeric feature columns are present, fill missing with 0
    for col in NUMERIC_FEATURE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype("float32")
        else:
            df[col] = np.float32(0.0)

    # Attack label: 0 or 1
    if "attack_label" in df.columns:
        df["attack_label"] = (
            pd.to_numeric(df["attack_label"], errors="coerce").fillna(0).astype(int).clip(0, 1)
        )
    else:
        df["attack_label"] = 0

    # Attack type: string, default to "Normal"
    if "attack_type" in df.columns:
        df["attack_type"] = df["attack_type"].astype(str).str.strip()
        df.loc[~df["attack_type"].isin(ATTACK_TYPES), "attack_type"] = "Normal"
    else:
        df["attack_type"] = "Normal"

    # Return only the columns we care about, sorted by timestamp
    keep_cols = ["timestamp"] + NUMERIC_FEATURE_COLS + ["attack_label", "attack_type"]
    df = df[[c for c in keep_cols if c in df.columns]].sort_values("timestamp").reset_index(drop=True)
    return df


def time_aware_split(
    df: pd.DataFrame,
    *,
    train_ratio: float = 0.8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split the DataFrame into train/test by time (no shuffling across time).

    Args:
        df: Normalized Edge-IIoTset DataFrame (must have a ``timestamp`` column).
        train_ratio: Fraction of rows (in time order) to use for training.

    Returns:
        ``(train_df, test_df)`` tuple.
    """
    if not 0.0 < train_ratio < 1.0:
        raise ValueError(f"train_ratio must be between 0 and 1, got {train_ratio}")

    n = len(df)
    split_idx = int(n * train_ratio)
    train = df.iloc[:split_idx].reset_index(drop=True)
    test = df.iloc[split_idx:].reset_index(drop=True)
    return train, test


def feature_matrix(df: pd.DataFrame) -> np.ndarray:
    """Extract the (N, 56) float32 feature matrix from a normalized DataFrame."""
    return cast(np.ndarray, df[NUMERIC_FEATURE_COLS].to_numpy(dtype=np.float32))


def labels(df: pd.DataFrame) -> dict[str, Any]:
    """Extract binary and multiclass labels from a normalized DataFrame."""
    return {
        "attack_label": df["attack_label"].to_numpy(dtype=np.int32),
        "attack_type": df["attack_type"].to_numpy(dtype=object),
    }
