"""SQLite-backed alerts store (async, append-only).

Tables:
    alerts              — individual detection events
    model_runs          — training run metadata
    forecast_snapshots  — pipeline forecast outputs

All writes are append-only; no UPDATE or DELETE.  Uses ``aiosqlite`` for
async access from the FastAPI event loop.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text()

_DEFAULT_DB = Path("data/alerts.db")


class AlertStore:
    """Async SQLite store for alerts and forecast snapshots.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Created on first open.
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Create tables if they do not exist."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def insert_alert(
        self,
        *,
        timestamp: datetime | str,
        attack_type: str,
        severity: str,
        confidence: float,
        source: str = "replay-csv",
        model_run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Insert a single alert row; returns the new row id."""
        ts = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                """
                INSERT INTO alerts
                    (timestamp, attack_type, severity, confidence, source, model_run_id, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, attack_type, severity, float(confidence), source, model_run_id,
                 json.dumps(payload or {})),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def get_alerts(
        self,
        *,
        since: datetime | str | None = None,
        attack_type: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        limit: int = 100,
        cursor: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return paginated alert rows (most recent first)."""
        clauses = []
        params: list[Any] = []

        if since is not None:
            ts = since.isoformat() if isinstance(since, datetime) else since
            clauses.append("timestamp >= ?")
            params.append(ts)
        if attack_type is not None:
            clauses.append("attack_type = ?")
            params.append(attack_type)
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if cursor is not None:
            clauses.append("id < ?")
            params.append(cursor)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"SELECT * FROM alerts {where} ORDER BY id DESC LIMIT ?",
                params,
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Model runs
    # ------------------------------------------------------------------

    async def upsert_model_run(
        self,
        run_id: str,
        *,
        started_at: datetime | str,
        ended_at: datetime | str | None = None,
        dataset_hash: str | None = None,
        training_run_hash: str | None = None,
        detector_name: str | None = None,
        detector_version: str | None = None,
        forecaster_name: str | None = None,
        forecaster_version: str | None = None,
        auc: float | None = None,
        f1: float | None = None,
        fpr: float | None = None,
        mae: float | None = None,
    ) -> None:
        """Insert or replace a model_run row."""
        s = started_at.isoformat() if isinstance(started_at, datetime) else started_at
        e = ended_at.isoformat() if isinstance(ended_at, datetime) else ended_at
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO model_runs
                    (id, started_at, ended_at, dataset_hash, training_run_hash,
                     detector_name, detector_version, forecaster_name, forecaster_version,
                     auc, f1, fpr, mae)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, s, e, dataset_hash, training_run_hash,
                 detector_name, detector_version, forecaster_name, forecaster_version,
                 auc, f1, fpr, mae),
            )
            await db.commit()

    async def get_model_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM model_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Forecast snapshots
    # ------------------------------------------------------------------

    async def insert_forecast_snapshot(
        self,
        *,
        generated_at: datetime | str,
        model_run_id: str | None = None,
        lookback_window_seconds: int = 300,
        forecast_horizon_seconds: int = 30,
        payload: dict[str, Any] | None = None,
    ) -> int:
        ts = generated_at.isoformat() if isinstance(generated_at, datetime) else generated_at
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                """
                INSERT INTO forecast_snapshots
                    (generated_at, model_run_id, lookback_window_seconds,
                     forecast_horizon_seconds, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, model_run_id, lookback_window_seconds, forecast_horizon_seconds,
                 json.dumps(payload or {})),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def get_latest_forecast(self) -> dict[str, Any] | None:
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM forecast_snapshots ORDER BY id DESC LIMIT 1"
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_forecasts(self, limit: int = 20) -> list[dict[str, Any]]:
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM forecast_snapshots ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Lookback helper
    # ------------------------------------------------------------------

    async def get_lookback_buckets(
        self,
        *,
        minutes: int = 60,
        bucket_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        """Return attack-count buckets for the last *minutes* minutes.

        Each bucket covers ``bucket_seconds`` seconds and contains counts per
        attack type.
        """
        since_dt = datetime.now(UTC).replace(second=0, microsecond=0)
        # Floor to bucket boundary
        from datetime import timedelta

        since_dt -= timedelta(minutes=minutes)
        since_str = since_dt.isoformat()

        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT
                    strftime('%Y-%m-%dT%H:%M:00Z',
                        datetime(timestamp,
                            '-' || CAST((strftime('%M', timestamp) % ?) AS TEXT) || ' minutes')
                    ) AS bucket,
                    attack_type,
                    COUNT(*) AS count,
                    AVG(confidence) AS avg_confidence
                FROM alerts
                WHERE timestamp >= ?
                GROUP BY bucket, attack_type
                ORDER BY bucket ASC, attack_type ASC
                """,
                (bucket_seconds // 60, since_str),
            )
            return [dict(r) for r in await cur.fetchall()]
