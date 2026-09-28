"""Streaming telemetry pipeline."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime

from jetson_edge_ai_security.alerts import AlertBuilder
from jetson_edge_ai_security.detection import BaselineDetector, Detector
from jetson_edge_ai_security.features import SlidingWindowExtractor
from jetson_edge_ai_security.runtime.metrics import RuntimeMetrics
from jetson_edge_ai_security.schemas import Alert, TelemetryEvent
from jetson_edge_ai_security.sinks.base import AlertSink
from jetson_edge_ai_security.sources import TrafficSource

LOGGER = logging.getLogger(__name__)


class PipelineRunner:
    """Run source ingestion, feature extraction, detection, and alerting."""

    def __init__(
        self,
        source: TrafficSource,
        *,
        window_size: int = 50,
        step: int = 10,
        detector: Detector | None = None,
        alert_builder: AlertBuilder | None = None,
        sinks: Sequence[AlertSink] | None = None,
        health_interval_windows: int = 0,
    ) -> None:
        self.source = source
        self.window_extractor = SlidingWindowExtractor(window_size=window_size, step=step)
        self.detector = detector or BaselineDetector()
        self.alert_builder = alert_builder or AlertBuilder()
        self.sinks: list[AlertSink] = list(sinks or [])
        self.health_interval_windows = health_interval_windows
        self.metrics = RuntimeMetrics()
        self.sink_errors = 0

    def run(self, *, max_alerts: int | None = None) -> list[Alert]:
        alerts = list(self.stream_alerts(max_alerts=max_alerts))
        self.metrics.finish()
        return alerts

    def stream_alerts(self, *, max_alerts: int | None = None) -> Iterator[Alert]:
        """Yield alerts as they are emitted, publishing each to every configured sink.

        Sinks are opened on entry and closed when the stream ends (including
        early termination). Sink failures are logged and counted in
        ``sink_errors``; they never interrupt detection.
        """

        with ExitStack() as stack:
            for sink in self.sinks:
                stack.enter_context(sink)
            try:
                event_stream = self._count_events(self.source.events())
                for window in self.window_extractor.windows(event_stream):
                    self.metrics.windows_seen += 1
                    result = self.detector.detect(window)
                    if result.is_anomaly:
                        self.metrics.detections_seen += 1
                    alert = self.alert_builder.from_detection(result)
                    if self.health_interval_windows and self.metrics.windows_seen % self.health_interval_windows == 0:
                        self._publish_health()
                    if alert is None:
                        continue
                    self.metrics.alerts_emitted += 1
                    self._publish(alert)
                    yield alert
                    if max_alerts is not None and self.metrics.alerts_emitted >= max_alerts:
                        break
            finally:
                if self.sinks:
                    self._publish_health(final=True)

    def _publish(self, alert: Alert) -> None:
        for sink in self.sinks:
            try:
                sink.publish(alert)
            except Exception as exc:  # noqa: BLE001 - a sink must not break detection
                self.sink_errors += 1
                LOGGER.warning("Alert sink %s failed: %s", getattr(sink, "name", sink), exc)

    def _publish_health(self, *, final: bool = False) -> None:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": getattr(self.source, "name", "unknown"),
            "final": final,
            "sink_errors": self.sink_errors,
            **self.metrics.model_dump(mode="json"),
        }
        for sink in self.sinks:
            try:
                sink.publish_health(payload)
            except Exception as exc:  # noqa: BLE001
                self.sink_errors += 1
                LOGGER.warning("Alert sink %s health publish failed: %s", getattr(sink, "name", sink), exc)

    def _count_events(self, events: Iterator[TelemetryEvent]) -> Iterator[TelemetryEvent]:
        for event in events:
            self.metrics.events_seen += 1
            yield event

