"""Alert sink abstraction.

A sink receives every ``Alert`` the pipeline emits. Sinks are context managers
(``open`` on enter, ``close`` on exit) and must never let a delivery failure
propagate into the pipeline; they log and count instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any

from jetson_edge_ai_security.schemas import Alert


class AlertSink(ABC):
    """Destination for emitted alerts (file, database, cloud broker, ...)."""

    name: str

    def __enter__(self) -> AlertSink:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @abstractmethod
    def open(self) -> None:
        """Acquire resources (open files, start clients or worker threads)."""

    @abstractmethod
    def publish(self, alert: Alert) -> None:
        """Deliver one alert. Must not block the pipeline or raise on delivery failure."""

    @abstractmethod
    def flush(self, timeout: float | None = None) -> None:
        """Wait (bounded by ``timeout`` seconds) for buffered alerts to be delivered."""

    @abstractmethod
    def close(self) -> None:
        """Flush and release resources. Safe to call more than once."""

    def publish_health(self, payload: dict[str, Any]) -> None:
        """Optionally publish a pipeline health snapshot. No-op by default."""
        return None
