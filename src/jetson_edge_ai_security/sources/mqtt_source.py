"""MQTT telemetry source adapter (paho-mqtt v2 callback API).

Subscribes to one or more topics and normalizes JSON object payloads into
``TelemetryEvent`` through a field map in the same style as the CSV alias
table: ``canonical_field -> accepted payload keys``. Unmapped keys are kept in
``metadata.unmapped``; the topic is kept in ``metadata.topic``.

The MQTT client is created by an injectable ``client_factory`` so tests can
supply a fake client and never need a broker.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import ValidationError

from jetson_edge_ai_security.config import MqttConfig
from jetson_edge_ai_security.schemas import TelemetryEvent
from jetson_edge_ai_security.sources.base import TrafficSource
from jetson_edge_ai_security.sources.csv_replay import COLUMN_ALIASES

LOGGER = logging.getLogger(__name__)

DEFAULT_FIELD_MAP: dict[str, tuple[str, ...]] = {
    **COLUMN_ALIASES,
    "timestamp": COLUMN_ALIASES["timestamp"] + ("event_time", "sent_at"),
    "source_ip": COLUMN_ALIASES["source_ip"] + ("src", "device_ip", "client_ip"),
    "dest_ip": COLUMN_ALIASES["dest_ip"] + ("dst", "server_ip", "broker_ip"),
    "packet_size": COLUMN_ALIASES["packet_size"] + ("size", "payload_len", "payload_length"),
    "flow_id": COLUMN_ALIASES["flow_id"] + ("session_id", "device_id"),
}
"""Default ``canonical_field -> accepted payload keys`` mapping (case-insensitive)."""

_MAPPABLE_FIELDS: frozenset[str] = frozenset(DEFAULT_FIELD_MAP)


class MqttClientLike(Protocol):
    """The subset of ``paho.mqtt.client.Client`` the source relies on."""

    on_connect: Any
    on_message: Any

    def connect(self, host: str, port: int, keepalive: int) -> Any: ...

    def subscribe(self, topic: list[tuple[str, int]]) -> Any: ...

    def loop_start(self) -> Any: ...

    def loop_stop(self) -> Any: ...

    def disconnect(self) -> Any: ...


ClientFactory = Callable[[str, bool], MqttClientLike]
"""``client_factory(client_id, use_tls) -> client``."""


def paho_client_factory(client_id: str, use_tls: bool) -> MqttClientLike:
    """Build a real paho-mqtt v2 client. Imported lazily so tests never need it."""

    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if use_tls:
        client.tls_set()
    return client


def parse_broker_url(broker_url: str) -> tuple[str, int, bool]:
    """Return ``(host, port, use_tls)`` for ``mqtt://``, ``mqtts://``, ``tcp://``, ``ssl://`` URLs.

    A bare ``host[:port]`` is accepted as plain MQTT.
    """

    text = broker_url.strip()
    if "://" not in text:
        text = f"mqtt://{text}"
    parsed = urlparse(text)
    scheme = (parsed.scheme or "mqtt").lower()
    if scheme in {"mqtt", "tcp"}:
        use_tls = False
    elif scheme in {"mqtts", "ssl", "tls"}:
        use_tls = True
    else:
        raise ValueError(f"Unsupported MQTT broker URL scheme: {scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"MQTT broker URL has no host: {broker_url!r}")
    port = parsed.port or (8883 if use_tls else 1883)
    return host, port, use_tls


def merge_field_map(overrides: Mapping[str, Sequence[str]] | None) -> dict[str, tuple[str, ...]]:
    """Overlay config-provided aliases on :data:`DEFAULT_FIELD_MAP`, validating field names."""

    merged = dict(DEFAULT_FIELD_MAP)
    for field, aliases in (overrides or {}).items():
        if field not in _MAPPABLE_FIELDS:
            raise ValueError(
                f"Unknown TelemetryEvent field in mqtt field_map: {field!r}; "
                f"allowed: {sorted(_MAPPABLE_FIELDS)}"
            )
        merged[field] = tuple(str(alias) for alias in aliases)
    return merged


class MqttTelemetrySource(TrafficSource):
    """Read JSON telemetry from MQTT topics and normalize it into TelemetryEvent.

    Parameters
    ----------
    broker_url:
        ``mqtt://host:port`` or ``mqtts://host:port``.
    topic:
        One topic filter or a sequence of them.
    client_id, qos, keepalive:
        Passed to the MQTT client / subscriptions.
    field_map:
        ``canonical_field -> accepted payload keys`` overrides merged over
        :data:`DEFAULT_FIELD_MAP`.
    client_factory:
        ``(client_id, use_tls) -> client``; defaults to a real paho client.
    queue_size:
        Bound on buffered raw messages. When full, the newest message is
        dropped and ``messages_dropped`` is incremented, so the network
        thread never blocks.
    limit, idle_timeout, stop_event:
        Stop conditions for :meth:`events`.
    strict:
        Raise on malformed payloads instead of counting them in ``rows_skipped``.
    """

    name = "mqtt-telemetry"

    def __init__(
        self,
        broker_url: str,
        topic: str | Sequence[str],
        *,
        client_id: str = "edge-security",
        qos: int = 0,
        keepalive: int = 60,
        field_map: Mapping[str, Sequence[str]] | None = None,
        client_factory: ClientFactory | None = None,
        queue_size: int = 10000,
        limit: int | None = None,
        idle_timeout: float | None = None,
        stop_event: threading.Event | None = None,
        poll_interval: float = 0.1,
        strict: bool = False,
        source_type: str = "mqtt-telemetry",
    ) -> None:
        self.broker_url = broker_url
        self.topics: list[str] = [topic] if isinstance(topic, str) else [str(t) for t in topic]
        if not self.topics:
            raise ValueError("MqttTelemetrySource needs at least one topic")
        self.topic = self.topics[0]
        self.client_id = client_id
        self.qos = qos
        self.keepalive = keepalive
        self.field_map = merge_field_map(field_map)
        self._client_factory: ClientFactory = client_factory or paho_client_factory
        self.limit = limit
        self.idle_timeout = idle_timeout
        self.stop_event = stop_event
        self.poll_interval = poll_interval
        self.strict = strict
        self.source_type = source_type
        self.host, self.port, self.use_tls = parse_broker_url(broker_url)
        self._client: MqttClientLike | None = None
        self._queue: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=queue_size)
        self.connected = threading.Event()
        self.messages_seen = 0
        self.messages_dropped = 0
        self.events_emitted = 0
        self.rows_skipped = 0
        self._known_keys = {alias.lower() for aliases in self.field_map.values() for alias in aliases}

    @classmethod
    def from_config(
        cls,
        config: MqttConfig,
        *,
        client_factory: ClientFactory | None = None,
        **overrides: Any,
    ) -> MqttTelemetrySource:
        """Construct from the ``mqtt`` section of :class:`AppConfig`."""

        return cls(
            config.broker_url,
            config.topics,
            client_id=config.client_id,
            qos=config.qos,
            keepalive=config.keepalive,
            field_map=config.field_map,
            client_factory=client_factory,
            queue_size=config.queue_size,
            **overrides,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        if self._client is not None:
            return
        client = self._client_factory(self.client_id, self.use_tls)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._client = client
        LOGGER.info("Connecting to MQTT broker %s:%s (tls=%s)", self.host, self.port, self.use_tls)
        client.connect(self.host, self.port, self.keepalive)
        client.loop_start()

    def close(self) -> None:
        client = self._client
        self._client = None
        self.connected.clear()
        if client is None:
            return
        for step in (client.loop_stop, client.disconnect):
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                LOGGER.warning("MQTT client shutdown step failed: %s", exc)

    # ------------------------------------------------------------------
    # Callbacks (run on the client's network thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        if _is_failure(reason_code):
            LOGGER.warning("MQTT connect refused: %s", reason_code)
            return
        client.subscribe([(topic, self.qos) for topic in self.topics])
        self.connected.set()
        LOGGER.info("Subscribed to %s", self.topics)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        self.messages_seen += 1
        payload = message.payload
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        try:
            self._queue.put_nowait((str(message.topic), bytes(payload)))
        except queue.Full:
            self.messages_dropped += 1

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def events(self) -> Iterator[TelemetryEvent]:
        should_close = self._client is None
        if should_close:
            self.open()
        last_data = time.monotonic()
        try:
            while not self._should_stop(last_data):
                try:
                    topic, payload = self._queue.get(timeout=self.poll_interval)
                except queue.Empty:
                    continue
                last_data = time.monotonic()
                event = self._payload_to_event(topic, payload)
                if event is None:
                    continue
                self.events_emitted += 1
                yield event
        finally:
            if should_close:
                self.close()

    def _should_stop(self, last_data: float) -> bool:
        if self.limit is not None and self.events_emitted >= self.limit:
            return True
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        if self.idle_timeout is not None and self._queue.empty():
            return (time.monotonic() - last_data) >= self.idle_timeout
        return False

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _payload_to_event(self, topic: str, payload: bytes) -> TelemetryEvent | None:
        try:
            record = json.loads(payload.decode("utf-8"))
            if not isinstance(record, dict):
                raise ValueError("MQTT payload is not a JSON object")
            return self._record_to_event(topic, record)
        except (ValueError, TypeError, ValidationError) as exc:
            self.rows_skipped += 1
            if self.strict:
                raise
            LOGGER.warning("Skipping malformed MQTT payload on %s: %s", topic, exc)
            return None

    def _record_to_event(self, topic: str, record: dict[str, Any]) -> TelemetryEvent:
        lower_map = {str(key).lower(): value for key, value in record.items()}
        payload: dict[str, Any] = {
            "source_type": self.source_type,
            "metadata": {"raw_source": self.name, "topic": topic},
        }
        for field, aliases in self.field_map.items():
            for alias in aliases:
                value = lower_map.get(alias.lower())
                if value not in (None, ""):
                    payload[field] = value
                    break
        for field in ("source_port", "dest_port", "packet_size"):
            if field in payload:
                payload[field] = _optional_int(payload[field])
        for field in ("source_ip", "dest_ip", "attack_type", "flow_id", "tcp_flags"):
            if field in payload and not isinstance(payload[field], str):
                payload[field] = str(payload[field])
        payload["metadata"]["unmapped"] = {
            key: value
            for key, value in record.items()
            if str(key).lower() not in self._known_keys and value not in (None, "")
        }
        return TelemetryEvent(**payload)


def _is_failure(reason_code: Any) -> bool:
    is_failure = getattr(reason_code, "is_failure", None)
    if isinstance(is_failure, bool):
        return is_failure
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return False


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    return int(float(str(value).strip()))
