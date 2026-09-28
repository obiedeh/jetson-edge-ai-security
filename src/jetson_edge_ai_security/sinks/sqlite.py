"""SQLite sink: feed pipeline alerts into the dashboard's ``AlertStore``.

``AlertStore`` is async (aiosqlite); the pipeline is synchronous, so each
write runs in a short-lived event loop. That is adequate for alert rates
(windows, not packets) and keeps the dashboard's schema untouched.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from jetson_edge_ai_security.alerts.store import AlertStore
from jetson_edge_ai_security.schemas import Alert
from jetson_edge_ai_security.sinks.base import AlertSink

LOGGER = logging.getLogger(__name__)

# BaselineDetector scores count triggered rules; four or more is "critical".
_SCORE_SCALE = 4.0


def confidence_from_alert(alert: Alert) -> float:
    """Map the detector score (rule count) onto the store's 0..1 confidence column."""

    score = alert.metadata.get("score", 0.0)
    try:
        value = float(score) / _SCORE_SCALE
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(1.0, value))


class SqliteAlertSink(AlertSink):
    """Insert each alert as a row the FastAPI dashboard can read."""

    name = "sqlite"

    def __init__(self, db_path: str | Path, *, store: AlertStore | None = None) -> None:
        self.db_path = Path(db_path)
        self._store = store
        self.published = 0
        self.failures = 0

    def open(self) -> None:
        if self._store is None:
            self._store = AlertStore(db_path=self.db_path)
        asyncio.run(self._store.init())

    def publish(self, alert: Alert) -> None:
        if self._store is None:
            self.open()
        assert self._store is not None
        payload: dict[str, Any] = {
            "title": alert.title,
            "description": alert.description,
            "recommended_action": alert.recommended_action,
            "features": alert.features,
            "metadata": alert.metadata,
        }
        try:
            asyncio.run(
                self._store.insert_alert(
                    timestamp=alert.timestamp,
                    attack_type=str(alert.metadata.get("attack_type") or "anomaly"),
                    severity=alert.severity,
                    confidence=confidence_from_alert(alert),
                    source=alert.source,
                    payload=payload,
                )
            )
            self.published += 1
        except Exception as exc:  # noqa: BLE001 - sink failures never reach the pipeline
            self.failures += 1
            LOGGER.warning("SQLite sink failed to insert alert into %s: %s", self.db_path, exc)

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self) -> None:
        return None
