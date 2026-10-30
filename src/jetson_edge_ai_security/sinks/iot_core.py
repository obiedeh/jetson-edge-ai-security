"""AWS IoT Core alert sink (MQTT5 over mTLS via ``awsiotsdk``).

Topics follow the fleet convention ``{topic_root}/{thing_name}/alerts`` and
``{topic_root}/{thing_name}/health``. Publishing is asynchronous: ``publish``
only enqueues, a background thread delivers with retry and exponential
backoff, and nothing here ever raises into the pipeline.

Drop policy
-----------
The queue is bounded (``queue_size``). When it is full the *newest* alert is
dropped and ``dropped`` is incremented. Rationale: alerts already queued are
older and were accepted first; dropping the incoming one keeps ``publish``
O(1), never blocks the detection loop, and makes the loss observable in the
``dropped`` counter and the health payload.

Credentials
-----------
Endpoint, thing name and certificate/key/CA paths come from config or the
``EDGE_SECURITY_IOT_*`` environment variables (see ``sinks/factory.py``).
Nothing is read from the repository. ``awsiot`` is imported lazily inside the
default client factory, so the runtime has no hard dependency on the SDK and
tests inject a fake client.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from jetson_edge_ai_security.schemas import Alert
from jetson_edge_ai_security.sinks.base import AlertSink

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IotCoreSettings:
    """Connection settings for one device (thing)."""

    endpoint: str
    thing_name: str
    cert_path: str
    key_path: str
    ca_path: str | None = None
    port: int = 8883
    client_id: str | None = None

    @property
    def effective_client_id(self) -> str:
        return self.client_id or self.thing_name


class IotCoreClientLike(Protocol):
    """What the sink needs from a client: blocking connect/publish/disconnect."""

    def connect(self) -> None: ...

    def publish(self, topic: str, payload: bytes, qos: int) -> None: ...

    def disconnect(self) -> None: ...


ClientFactory = Callable[[IotCoreSettings], IotCoreClientLike]


class AwsIotMqtt5Client:
    """Thin blocking adapter over the awsiotsdk MQTT5 client."""

    def __init__(self, settings: IotCoreSettings, *, connect_timeout: float = 10.0, publish_timeout: float = 10.0) -> None:
        self.settings = settings
        self.connect_timeout = connect_timeout
        self.publish_timeout = publish_timeout
        self._client: Any = None
        self._connected = threading.Event()
        self._mqtt5: Any = None

    def connect(self) -> None:
        from awscrt import mqtt5  # lazy: optional `cloud` extra
        from awsiot import mqtt5_client_builder

        self._mqtt5 = mqtt5
        self._connected.clear()

        def on_success(_data: Any) -> None:
            self._connected.set()

        def on_failure(data: Any) -> None:
            LOGGER.warning("IoT Core connection failure: %s", getattr(data, "exception", data))

        def on_disconnect(_data: Any) -> None:
            self._connected.clear()

        kwargs: dict[str, Any] = {
            "endpoint": self.settings.endpoint,
            "port": self.settings.port,
            "cert_filepath": self.settings.cert_path,
            "pri_key_filepath": self.settings.key_path,
            "client_id": self.settings.effective_client_id,
            "on_lifecycle_connection_success": on_success,
            "on_lifecycle_connection_failure": on_failure,
            "on_lifecycle_disconnection": on_disconnect,
        }
        if self.settings.ca_path:
            kwargs["ca_filepath"] = self.settings.ca_path
        self._client = mqtt5_client_builder.mtls_from_path(**kwargs)
        self._client.start()
        if not self._connected.wait(self.connect_timeout):
            raise TimeoutError(f"IoT Core connect to {self.settings.endpoint} timed out")

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if self._client is None or self._mqtt5 is None:
            raise RuntimeError("IoT Core client is not connected")
        qos_enum = self._mqtt5.QoS.AT_LEAST_ONCE if qos >= 1 else self._mqtt5.QoS.AT_MOST_ONCE
        future = self._client.publish(self._mqtt5.PublishPacket(topic=topic, payload=payload, qos=qos_enum))
        future.result(self.publish_timeout)

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.stop()
            finally:
                self._client = None
                self._connected.clear()


def aws_iot_client_factory(settings: IotCoreSettings) -> IotCoreClientLike:
    """Default factory; imports ``awsiot`` lazily so the SDK stays optional."""

    try:
        import awsiot  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "IoT Core sink requires the 'cloud' extra: pip install 'jetson-edge-ai-security[cloud]'"
        ) from exc
    return AwsIotMqtt5Client(settings)


class IotCoreAlertSink(AlertSink):
    """Publish alerts and health snapshots to AWS IoT Core from a background thread.

    Parameters
    ----------
    settings:
        Endpoint, thing name and credential paths.
    topic_root:
        Topic prefix; alerts go to ``{root}/{thing}/alerts`` and health to
        ``{root}/{thing}/health``.
    qos:
        MQTT QoS (1 = at least once, the default).
    queue_size:
        Bound on pending messages; see the module docstring for the drop policy.
    max_retries, backoff_base, backoff_max:
        Per-message retry budget and exponential backoff bounds in seconds.
    client_factory:
        ``(settings) -> client``; defaults to the awsiotsdk adapter.
    sleep:
        Injection point for the backoff sleep (tests pass a recorder).
    """

    name = "iot-core"

    def __init__(
        self,
        settings: IotCoreSettings,
        *,
        topic_root: str = "edge-security",
        qos: int = 1,
        queue_size: int = 1000,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least 1")
        self.settings = settings
        self.topic_root = topic_root.strip("/")
        self.qos = qos
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._client_factory: ClientFactory = client_factory or aws_iot_client_factory
        self._sleep = sleep
        self._queue: queue.Queue[tuple[str, bytes] | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._client: IotCoreClientLike | None = None
        self._connected = False
        self.published = 0
        self.dropped = 0
        self.failed = 0
        self.retries = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    @property
    def alerts_topic(self) -> str:
        return f"{self.topic_root}/{self.settings.thing_name}/alerts"

    @property
    def health_topic(self) -> str:
        return f"{self.topic_root}/{self.settings.thing_name}/health"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        if self._thread is not None:
            return
        # Build the client eagerly so a missing SDK or bad settings surface at
        # startup; the network connect itself happens lazily on the worker.
        self._client = self._client_factory(self.settings)
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="iot-core-sink", daemon=True)
        self._thread.start()

    def publish(self, alert: Alert) -> None:
        self._enqueue(self.alerts_topic, alert.model_dump(mode="json"))

    def publish_health(self, payload: dict[str, Any]) -> None:
        body = {
            "thing": self.settings.thing_name,
            "published_at": datetime.now(UTC).isoformat(),
            "sink": self.stats(),
            **payload,
        }
        self._enqueue(self.health_topic, body)

    def flush(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if self._thread is None or not self._thread.is_alive():
                return
            if deadline is not None and time.monotonic() >= deadline:
                LOGGER.warning("IoT Core sink flush timed out with %d pending", self._queue.qsize())
                return
            time.sleep(0.01)

    def close(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self.flush(timeout=timeout)
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        thread.join(timeout=timeout)
        self._thread = None
        client, self._client = self._client, None
        self._connected = False
        if client is not None:
            try:
                client.disconnect()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                LOGGER.warning("IoT Core disconnect failed: %s", exc)

    def stats(self) -> dict[str, Any]:
        return {
            "published": self.published,
            "dropped": self.dropped,
            "failed": self.failed,
            "retries": self.retries,
            "pending": self._queue.qsize(),
            "connected": self._connected,
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _enqueue(self, topic: str, body: dict[str, Any]) -> None:
        try:
            payload = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            self.failed += 1
            self.last_error = f"serialize: {exc}"
            LOGGER.warning("IoT Core sink could not serialize message for %s: %s", topic, exc)
            return
        try:
            self._queue.put_nowait((topic, payload))
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                LOGGER.warning("IoT Core sink queue full; dropped %d message(s) so far", self.dropped)

    def _worker(self) -> None:
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                return
            try:
                self._deliver(*item)
            except Exception as exc:  # noqa: BLE001 - the worker must survive anything
                self.failed += 1
                self.last_error = repr(exc)
                LOGGER.error("IoT Core sink worker error: %s", exc)
            finally:
                self._queue.task_done()

    def _deliver(self, topic: str, payload: bytes) -> None:
        attempt = 0
        while True:
            try:
                self._ensure_connected()
                assert self._client is not None
                self._client.publish(topic, payload, self.qos)
                self.published += 1
                return
            except Exception as exc:  # noqa: BLE001 - retried, then counted
                self.last_error = repr(exc)
                self._connected = False
                if attempt >= self.max_retries or self._stop.is_set():
                    self.failed += 1
                    LOGGER.warning("IoT Core publish to %s failed after %d attempt(s): %s", topic, attempt + 1, exc)
                    return
                delay = min(self.backoff_max, self.backoff_base * (2**attempt))
                attempt += 1
                self.retries += 1
                LOGGER.info("IoT Core publish retry %d/%d in %.2fs: %s", attempt, self.max_retries, delay, exc)
                self._sleep(delay)

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        if self._client is None:
            raise RuntimeError("IoT Core sink is not open")
        self._client.connect()
        self._connected = True
