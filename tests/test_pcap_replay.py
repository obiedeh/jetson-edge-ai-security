"""Tests for pcap_replay module.

Tests use a synthetic in-memory PCAP file (written with dpkt) so they do not
depend on any external fixture files.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers — build a minimal PCAP bytes blob in memory
# ──────────────────────────────────────────────────────────────────────────────


def _make_pcap_bytes(packets: list[tuple[float, bytes]]) -> bytes:
    """Build a PCAP file in memory from (timestamp, raw_bytes) pairs."""
    # Global header: magic, version major/minor, thiszone, sigfigs, snaplen, network (1=Ethernet)
    hdr = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    buf = io.BytesIO()
    buf.write(hdr)
    for ts, raw in packets:
        ts_sec = int(ts)
        ts_usec = int((ts - ts_sec) * 1_000_000)
        pkt_hdr = struct.pack("<IIII", ts_sec, ts_usec, len(raw), len(raw))
        buf.write(pkt_hdr)
        buf.write(raw)
    return buf.getvalue()


def _make_tcp_frame(
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
) -> bytes:
    """Build a minimal Ethernet+IP+TCP frame."""
    try:
        import dpkt
    except ImportError:
        pytest.skip("dpkt not installed")

    import socket

    tcp = dpkt.tcp.TCP(sport=src_port, dport=dst_port, data=b"", off=5)
    tcp.flags = dpkt.tcp.TH_SYN
    ip = dpkt.ip.IP(
        src=socket.inet_aton(src_ip),
        dst=socket.inet_aton(dst_ip),
        p=dpkt.ip.IP_PROTO_TCP,
        data=tcp,
        ttl=64,
    )
    ip.len = len(ip)
    eth = dpkt.ethernet.Ethernet(
        src=b"\x00" * 6,
        dst=b"\xff" * 6,
        data=ip,
        type=dpkt.ethernet.ETH_TYPE_IP,
    )
    return bytes(eth)


@pytest.fixture()
def tmp_pcap(tmp_path: Path) -> Path:
    """Write a small synthetic PCAP to a temp file."""
    try:
        import dpkt  # noqa: F401
    except ImportError:
        pytest.skip("dpkt not installed")

    frame = _make_tcp_frame("192.168.1.10", "10.0.0.1", 54321, 443)
    base_ts = 1700000000.0
    # 20 packets at 0.1s intervals → 2 windows at 1s granularity
    packets = [(base_ts + i * 0.1, frame) for i in range(20)]
    pcap_bytes = _make_pcap_bytes(packets)

    path = tmp_path / "test.pcap"
    path.write_bytes(pcap_bytes)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


def test_iter_pcap_events_yields_telemetry_events(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events
    from jetson_edge_ai_security.schemas import TelemetryEvent

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    assert len(events) >= 1
    for event in events:
        assert isinstance(event, TelemetryEvent)


def test_iter_pcap_events_fields_populated(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    assert len(events) >= 1
    ev = events[0]
    assert ev.source_ip == "192.168.1.10"
    assert ev.dest_ip == "10.0.0.1"
    assert ev.source_port == 54321
    assert ev.dest_port == 443
    assert ev.protocol == "6"  # TCP protocol number as string


def test_iter_pcap_events_limit(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0, limit=1))
    assert len(events) == 1


def test_iter_pcap_events_file_not_found() -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    with pytest.raises(FileNotFoundError):
        list(iter_pcap_events("/nonexistent/path/test.pcap", replay_rate=0.0))


def test_iter_pcap_events_metadata_fields_present(tmp_pcap: Path) -> None:
    """Each event should carry flow stats in the metadata dict."""
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    ev = events[0]
    assert "flow_bytes_per_second" in ev.metadata
    assert "flow_packets_per_second" in ev.metadata
    assert "flow_duration" in ev.metadata
    assert "packet_count" in ev.metadata


def test_iter_pcap_events_attack_label_false(tmp_pcap: Path) -> None:
    """PCAP replay has no ground-truth labels — attack_label must be False."""
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    for ev in events:
        assert ev.attack_label is False
        assert ev.attack_type is None


def test_iter_pcap_events_source_type_badge(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    for ev in events:
        assert ev.source_type == "replay-pcap"


def test_pcap_replay_source_context_manager(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import PcapReplaySource

    with PcapReplaySource(tmp_pcap, replay_rate=0.0) as src:
        events = list(src)

    assert len(events) >= 1
    assert src.events_emitted == len(events)


def test_pcap_replay_source_badge(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import PcapReplaySource

    src = PcapReplaySource(tmp_pcap, replay_rate=0.0)
    assert src.source_badge == "replay-pcap"


def test_pcap_replay_source_limit(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import PcapReplaySource

    with PcapReplaySource(tmp_pcap, replay_rate=0.0, limit=1) as src:
        events = list(src)

    assert len(events) == 1
    assert src.events_emitted == 1


def test_iter_pcap_events_window_aggregation(tmp_pcap: Path) -> None:
    """20 packets at 0.1s intervals = 2s total; expect at least 1 window emitted."""
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, window_seconds=1.0, replay_rate=0.0))
    assert len(events) >= 1


def test_iter_pcap_events_packet_size_positive(tmp_pcap: Path) -> None:
    from jetson_edge_ai_security.datasets.pcap_replay import iter_pcap_events

    events = list(iter_pcap_events(tmp_pcap, replay_rate=0.0))
    for ev in events:
        assert ev.packet_size is not None
        assert ev.packet_size > 0
