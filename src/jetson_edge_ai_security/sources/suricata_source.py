"""Suricata EVE JSON source adapter.

Reads ``eve.json`` (one JSON object per line) either as a one-shot replay or in
``follow`` mode, which tails the file with a polling loop the way ``tail -F``
does. Only ``flow``, ``alert`` and ``stats`` records are normalized into
``TelemetryEvent``; every other ``event_type`` is skipped and counted.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from pydantic import ValidationError

from jetson_edge_ai_security.schemas import TelemetryEvent
from jetson_edge_ai_security.sources.base import TrafficSource

LOGGER = logging.getLogger(__name__)

SUPPORTED_EVENT_TYPES: frozenset[str] = frozenset({"flow", "alert", "stats"})


class SuricataEveSource(TrafficSource):
    """Read Suricata EVE JSON alerts/flows and normalize them into TelemetryEvent.

    Parameters
    ----------
    path:
        Path to ``eve.json``.
    follow:
        Keep polling the file for appended lines after the existing content has
        been replayed. Truncation and rotation (inode change) reopen the file.
    event_types:
        Subset of :data:`SUPPORTED_EVENT_TYPES` to emit. Defaults to all three.
    limit:
        Stop after emitting this many events.
    strict:
        Raise on malformed lines instead of skipping and counting them.
    poll_interval:
        Seconds to sleep between polls in follow mode.
    idle_timeout:
        In follow mode, stop when no new data has arrived for this many seconds.
    stop_event:
        In follow mode, stop as soon as this :class:`threading.Event` is set.

    Counters ``lines_seen``, ``events_emitted``, ``rows_skipped`` (malformed
    lines) and ``events_skipped`` (per unsupported ``event_type``) are exposed
    for reporting.
    """

    name = "suricata-eve"

    def __init__(
        self,
        path: str | Path,
        *,
        follow: bool = False,
        event_types: set[str] | None = None,
        limit: int | None = None,
        strict: bool = False,
        poll_interval: float = 0.2,
        idle_timeout: float | None = None,
        stop_event: threading.Event | None = None,
        source_type: str = "suricata-eve",
    ) -> None:
        self.path = Path(path)
        self.follow = follow
        requested = set(event_types) if event_types is not None else set(SUPPORTED_EVENT_TYPES)
        unsupported = requested - SUPPORTED_EVENT_TYPES
        if unsupported:
            raise ValueError(
                f"Unsupported EVE event types {sorted(unsupported)}; "
                f"supported: {sorted(SUPPORTED_EVENT_TYPES)}"
            )
        self.event_types = requested
        self.limit = limit
        self.strict = strict
        self.poll_interval = poll_interval
        self.idle_timeout = idle_timeout
        self.stop_event = stop_event
        self.source_type = source_type
        self._handle: IO[str] | None = None
        self._inode: int | None = None
        self._partial = ""
        self.lines_seen = 0
        self.events_emitted = 0
        self.rows_skipped = 0
        self.events_skipped: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Suricata EVE file does not exist: {self.path}")
        self._open_handle()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._inode = None
        self._partial = ""

    def _open_handle(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = self.path.open("r", encoding="utf-8", errors="replace")
        self._inode = os.fstat(self._handle.fileno()).st_ino
        self._partial = ""

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def events(self) -> Iterator[TelemetryEvent]:
        should_close = self._handle is None
        if should_close:
            self.open()
        try:
            for line in self._lines():
                self.lines_seen += 1
                event = self._line_to_event(line)
                if event is None:
                    continue
                self.events_emitted += 1
                yield event
                if self.limit is not None and self.events_emitted >= self.limit:
                    return
        finally:
            if should_close:
                self.close()

    def _lines(self) -> Iterator[str]:
        """Yield complete lines; in follow mode keep polling until a stop condition."""
        last_data = time.monotonic()
        while True:
            if self._handle is None:
                raise RuntimeError("SuricataEveSource handle is None after open()")
            chunk = self._handle.readline()
            if chunk:
                if not chunk.endswith("\n"):
                    # Writer is mid-line; hold the fragment until the newline arrives.
                    if not self.follow:
                        yield self._partial + chunk
                        self._partial = ""
                        continue
                    self._partial += chunk
                    continue
                line = self._partial + chunk
                self._partial = ""
                last_data = time.monotonic()
                yield line
                continue

            if not self.follow:
                if self._partial:
                    yield self._partial
                    self._partial = ""
                return
            if self._should_stop(last_data):
                return
            self._reopen_if_rotated()
            time.sleep(self.poll_interval)

    def _should_stop(self, last_data: float) -> bool:
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        if self.idle_timeout is not None and (time.monotonic() - last_data) >= self.idle_timeout:
            return True
        return False

    def _reopen_if_rotated(self) -> None:
        if self._handle is None:
            return
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return
        position = self._handle.tell()
        if stat.st_ino != self._inode:
            LOGGER.info("EVE file rotated; reopening %s", self.path)
            self._open_handle()
        elif stat.st_size < position:
            LOGGER.info("EVE file truncated; restarting from the beginning of %s", self.path)
            self._handle.seek(0)
            self._partial = ""

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _line_to_event(self, line: str) -> TelemetryEvent | None:
        text = line.strip()
        if not text:
            return None
        try:
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError("EVE record is not a JSON object")
            event_type = str(record.get("event_type", ""))
            if event_type not in self.event_types:
                key = event_type or "<missing>"
                self.events_skipped[key] = self.events_skipped.get(key, 0) + 1
                return None
            return self._record_to_event(record, event_type)
        except (ValueError, TypeError, ValidationError) as exc:
            self.rows_skipped += 1
            if self.strict:
                raise
            LOGGER.warning("Skipping malformed EVE line %s: %s", self.lines_seen, exc)
            return None

    def _record_to_event(self, record: dict[str, Any], event_type: str) -> TelemetryEvent:
        metadata: dict[str, Any] = {"raw_source": self.name, "event_type": event_type}
        for key in ("in_iface", "app_proto", "community_id"):
            if record.get(key) not in (None, ""):
                metadata[key] = record[key]
        payload: dict[str, Any] = {
            "timestamp": record.get("timestamp"),
            "source_ip": str(record.get("src_ip") or ""),
            "dest_ip": str(record.get("dest_ip") or ""),
            "source_port": _optional_int(record.get("src_port")),
            "dest_port": _optional_int(record.get("dest_port")),
            "protocol": record.get("proto"),
            "flow_id": None if record.get("flow_id") is None else str(record["flow_id"]),
            "source_type": self.source_type,
            "metadata": metadata,
        }

        flow = record.get("flow") if isinstance(record.get("flow"), dict) else None
        if event_type == "flow":
            _apply_flow(payload, flow or {}, metadata)
            tcp = record.get("tcp")
            if isinstance(tcp, dict) and tcp.get("tcp_flags"):
                payload["tcp_flags"] = str(tcp["tcp_flags"])
        elif event_type == "alert":
            alert = record.get("alert")
            if not isinstance(alert, dict):
                raise ValueError("EVE alert record has no 'alert' object")
            _apply_alert(payload, alert, metadata)
            if flow:
                _apply_flow(payload, flow, metadata)
        elif event_type == "stats":
            _apply_stats(record.get("stats"), metadata)

        return TelemetryEvent(**payload)


def _apply_flow(payload: dict[str, Any], flow: dict[str, Any], metadata: dict[str, Any]) -> None:
    bytes_toserver = _optional_int(flow.get("bytes_toserver")) or 0
    bytes_toclient = _optional_int(flow.get("bytes_toclient")) or 0
    pkts_toserver = _optional_int(flow.get("pkts_toserver")) or 0
    pkts_toclient = _optional_int(flow.get("pkts_toclient")) or 0
    payload["packet_size"] = bytes_toserver + bytes_toclient
    metadata["flow"] = {
        "bytes_toserver": bytes_toserver,
        "bytes_toclient": bytes_toclient,
        "pkts_toserver": pkts_toserver,
        "pkts_toclient": pkts_toclient,
        "packets": pkts_toserver + pkts_toclient,
    }
    for key in ("start", "end", "age", "state", "reason", "alerted"):
        if flow.get(key) is not None:
            metadata["flow"][key] = flow[key]


def _apply_alert(payload: dict[str, Any], alert: dict[str, Any], metadata: dict[str, Any]) -> None:
    signature = str(alert.get("signature") or "")
    category = str(alert.get("category") or "")
    payload["attack_label"] = True
    payload["attack_type"] = category or signature or "suricata-alert"
    metadata["alert"] = {
        "signature": signature,
        "signature_id": _optional_int(alert.get("signature_id")),
        "gid": _optional_int(alert.get("gid")),
        "rev": _optional_int(alert.get("rev")),
        "severity": _optional_int(alert.get("severity")),
        "category": category,
        "action": alert.get("action"),
    }


def _apply_stats(stats: Any, metadata: dict[str, Any]) -> None:
    if not isinstance(stats, dict):
        return
    summary: dict[str, Any] = {}
    if stats.get("uptime") is not None:
        summary["uptime"] = stats["uptime"]
    capture = stats.get("capture")
    if isinstance(capture, dict):
        for key in ("kernel_packets", "kernel_drops", "errors"):
            if capture.get(key) is not None:
                summary[f"capture_{key}"] = capture[key]
    decoder = stats.get("decoder")
    if isinstance(decoder, dict):
        for key in ("pkts", "bytes", "invalid"):
            if decoder.get(key) is not None:
                summary[f"decoder_{key}"] = decoder[key]
    flow = stats.get("flow")
    if isinstance(flow, dict):
        for key in ("tcp", "udp", "icmpv4", "memuse"):
            if flow.get(key) is not None:
                summary[f"flow_{key}"] = flow[key]
    detect = stats.get("detect")
    if isinstance(detect, dict) and detect.get("alert") is not None:
        summary["detect_alert"] = detect["alert"]
    metadata["stats"] = summary


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    return int(float(str(value).strip()))
