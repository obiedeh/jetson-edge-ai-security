"""JSONL file sink: one ``Alert.model_dump(mode="json")`` per line."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import IO

from jetson_edge_ai_security.schemas import Alert
from jetson_edge_ai_security.sinks.base import AlertSink

LOGGER = logging.getLogger(__name__)


class JsonlAlertSink(AlertSink):
    """Append alerts to a JSON-lines file, creating parent directories as needed."""

    name = "jsonl"

    def __init__(self, path: str | Path, *, append: bool = True) -> None:
        self.path = Path(path)
        self.append = append
        self._handle: IO[str] | None = None
        self.published = 0
        self.failures = 0

    def open(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a" if self.append else "w", encoding="utf-8")

    def publish(self, alert: Alert) -> None:
        if self._handle is None:
            self.open()
        assert self._handle is not None
        try:
            self._handle.write(json.dumps(alert.model_dump(mode="json"), sort_keys=True) + "\n")
            self._handle.flush()
            self.published += 1
        except OSError as exc:
            self.failures += 1
            LOGGER.warning("JSONL sink failed to write alert to %s: %s", self.path, exc)

    def flush(self, timeout: float | None = None) -> None:
        if self._handle is not None:
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
