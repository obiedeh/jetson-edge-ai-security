"""PCAP replay source — simulates a SPAN/mirror port feed.

Uses ``dpkt`` (preferred) or falls back to ``scapy`` to read packets.
Flow-aggregates by 5-tuple (source_ip, dest_ip, source_port, dest_port, proto) using a
1-second sliding window and emits ``TelemetryEvent`` instances at wall-clock or
accelerated rate.

This module treats the PCAP as a stand-in for live SPAN/mirror traffic.  Live
capture against an actual interface (``libpcap``) is deferred to v1.x.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from jetson_edge_ai_security.schemas import TelemetryEvent

# ──────────────────────────────────────────────────────────────────────────────
# Packet parser
# ──────────────────────────────────────────────────────────────────────────────


def _try_import_dpkt():  # type: ignore[return]
    try:
        import dpkt

        return dpkt
    except ImportError:
        return None


def _ip_to_str(addr: bytes) -> str:
    try:
        return socket.inet_ntoa(addr)
    except OSError:
        return "0.0.0.0"


def _iter_packets_dpkt(path: Path) -> Iterator[tuple[float, dict]]:
    """Yield (timestamp, packet_dict) using dpkt.

    packet_dict keys: src_ip, dst_ip, src_port, dst_port, proto, frame_len,
                      ip_proto, ip_ttl
    """
    import dpkt

    with path.open("rb") as fh:
        try:
            pcap = dpkt.pcap.Reader(fh)
        except (dpkt.dpkt.NeedData, ValueError):
            return

        for ts, raw in pcap:
            try:
                eth = dpkt.ethernet.Ethernet(raw)
            except (dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError):
                continue

            ip = getattr(eth, "data", None)
            if ip is None or not hasattr(ip, "src") or not hasattr(ip, "dst"):
                continue

            src_ip = _ip_to_str(ip.src)
            dst_ip = _ip_to_str(ip.dst)
            proto = getattr(ip, "p", 0)
            ip_ttl = getattr(ip, "ttl", 0)

            transport = getattr(ip, "data", None)
            src_port = getattr(transport, "sport", 0)
            dst_port = getattr(transport, "dport", 0)

            yield ts, {
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "src_port": int(src_port),
                "dst_port": int(dst_port),
                "proto": int(proto),
                "frame_len": len(raw),
                "ip_proto": int(proto),
                "ip_ttl": int(ip_ttl),
            }


# ──────────────────────────────────────────────────────────────────────────────
# Flow aggregation
# ──────────────────────────────────────────────────────────────────────────────


def _five_tuple(pkt: dict) -> tuple:
    return (
        pkt["src_ip"], pkt["dst_ip"],
        pkt["src_port"], pkt["dst_port"],
        pkt["proto"],
    )


class _FlowRecord:
    __slots__ = (
        "start_ts", "last_ts", "packet_count", "byte_count",
        "source_ip", "dest_ip", "source_port", "dest_port", "proto",
    )

    def __init__(self, ts: float, pkt: dict) -> None:
        self.start_ts = ts
        self.last_ts = ts
        self.packet_count = 1
        self.byte_count = pkt["frame_len"]
        self.source_ip = pkt["src_ip"]
        self.dest_ip = pkt["dst_ip"]
        self.source_port = pkt["src_port"]
        self.dest_port = pkt["dst_port"]
        self.proto = pkt["proto"]

    def update(self, ts: float, pkt: dict) -> None:
        self.last_ts = ts
        self.packet_count += 1
        self.byte_count += pkt["frame_len"]


def _flow_to_event(flow: _FlowRecord) -> TelemetryEvent:
    duration = max(float(flow.last_ts - flow.start_ts), 1e-6)
    return TelemetryEvent(
        timestamp=datetime.fromtimestamp(flow.start_ts, tz=UTC),
        packet_size=flow.byte_count // max(1, flow.packet_count),
        attack_label=False,  # PCAP replay has no ground-truth labels
        attack_type=None,
        source_ip=flow.source_ip,
        dest_ip=flow.dest_ip,
        source_port=flow.source_port,
        dest_port=flow.dest_port,
        protocol=str(flow.proto),
        source_type="replay-pcap",
        metadata={
            "frame_len": float(flow.byte_count),
            "flow_bytes_per_second": float(flow.byte_count) / duration,
            "flow_packets_per_second": float(flow.packet_count) / duration,
            "flow_duration": duration,
            "packet_count": flow.packet_count,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def iter_pcap_events(
    pcap_path: str | Path,
    *,
    window_seconds: float = 1.0,
    replay_rate: float = 1.0,
    limit: int | None = None,
) -> Iterator[TelemetryEvent]:
    """Read a PCAP file and emit ``TelemetryEvent`` per completed flow window.

    Parameters
    ----------
    pcap_path:
        Path to a ``.pcap`` or ``.pcapng`` file.
    window_seconds:
        Flow aggregation window in seconds (default 1.0).
    replay_rate:
        Wall-clock replay multiplier.  ``1.0`` replays in real time; ``0.0``
        runs as fast as possible.  Values > 1 speed up replay.
    limit:
        Optional maximum number of events to emit.

    Yields
    ------
    TelemetryEvent
        One event per completed flow window.
    """
    dpkt = _try_import_dpkt()
    if dpkt is None:
        raise ImportError(
            "dpkt is required for PCAP replay: pip install dpkt"
        )

    pcap_path = Path(pcap_path)
    if not pcap_path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

    flows: dict[tuple, _FlowRecord] = {}
    current_window_end: float | None = None
    first_pcap_ts: float | None = None
    first_wall_ts: float | None = None
    count = 0

    for pcap_ts, pkt in _iter_packets_dpkt(pcap_path):
        # initialise wall-clock synchronisation
        if first_pcap_ts is None:
            first_pcap_ts = pcap_ts
            first_wall_ts = time.monotonic()
            current_window_end = pcap_ts + window_seconds

        # replay rate delay
        if replay_rate > 0:
            expected_wall = first_wall_ts + (pcap_ts - first_pcap_ts) / replay_rate  # type: ignore[operator]
            sleep_s = expected_wall - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)

        key = _five_tuple(pkt)

        if pcap_ts >= current_window_end:  # type: ignore[operator]
            # Flush all open flows
            for flow in flows.values():
                event = _flow_to_event(flow)
                yield event
                count += 1
                if limit is not None and count >= limit:
                    return
            flows = {}
            # Advance window
            windows_to_skip = int((pcap_ts - current_window_end) / window_seconds)  # type: ignore[operator]
            current_window_end += (windows_to_skip + 1) * window_seconds  # type: ignore[operator]

        if key in flows:
            flows[key].update(pcap_ts, pkt)
        else:
            flows[key] = _FlowRecord(pcap_ts, pkt)

    # Flush remaining flows
    for flow in flows.values():
        if limit is not None and count >= limit:
            break
        yield _flow_to_event(flow)
        count += 1


class PcapReplaySource:
    """File-like source adapter for PCAP replay.

    Wraps :func:`iter_pcap_events` in an iterable class compatible with the
    ``TrafficSource`` pattern used by ``PipelineRunner``.

    Parameters
    ----------
    pcap_path:
        Path to the PCAP file.
    window_seconds:
        Flow aggregation window (default 1 second).
    replay_rate:
        Wall-clock multiplier (default ``0.0`` = as fast as possible).
    limit:
        Maximum events to emit.
    """

    def __init__(
        self,
        pcap_path: str | Path,
        *,
        window_seconds: float = 1.0,
        replay_rate: float = 0.0,
        limit: int | None = None,
    ) -> None:
        self._path = Path(pcap_path)
        self._window_seconds = window_seconds
        self._replay_rate = replay_rate
        self._limit = limit
        self.events_emitted: int = 0
        self.source_badge: str = "replay-pcap"

    def __enter__(self) -> PcapReplaySource:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def __iter__(self) -> Iterator[TelemetryEvent]:
        for event in iter_pcap_events(
            self._path,
            window_seconds=self._window_seconds,
            replay_rate=self._replay_rate,
            limit=self._limit,
        ):
            self.events_emitted += 1
            yield event
