"""Tests for /lookback and /forecast API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# ──────────────────────────────────────────────────────────────────────────────
# App fixture — patch STORE to use a temp DB
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def client(tmp_path: Path):
    """AsyncClient pointed at the FastAPI app, using a temp DB."""
    import jetson_edge_ai_security.api.main as main_module
    from jetson_edge_ai_security.alerts.store import AlertStore

    # Override store + data dir with temp paths
    main_module._STORE = AlertStore(db_path=tmp_path / "alerts.db")
    main_module._DATA_DIR = tmp_path
    main_module._REPORTS_DIR = tmp_path / "reports"
    main_module._ARTIFACTS_DIR = tmp_path / "artifacts"
    main_module._MODELS_DIR = tmp_path / "models"
    (tmp_path / "reports").mkdir()

    from jetson_edge_ai_security.api.main import app

    await main_module._STORE.init()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ──────────────────────────────────────────────────────────────────────────────
# /health
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(client) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ──────────────────────────────────────────────────────────────────────────────
# /lookback
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookback_returns_200(client) -> None:
    resp = await client.get("/lookback")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_lookback_response_structure(client) -> None:
    resp = await client.get("/lookback")
    data = resp.json()
    assert "minutes" in data
    assert "bucket_seconds" in data
    assert "buckets" in data
    assert "source_badge" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_lookback_default_params(client) -> None:
    resp = await client.get("/lookback")
    data = resp.json()
    assert data["minutes"] == 60
    assert data["bucket_seconds"] == 300


@pytest.mark.asyncio
async def test_lookback_custom_params(client) -> None:
    resp = await client.get("/lookback?minutes=30&bucket_seconds=60")
    assert resp.status_code == 200
    data = resp.json()
    assert data["minutes"] == 30
    assert data["bucket_seconds"] == 60


@pytest.mark.asyncio
async def test_lookback_empty_buckets_when_no_alerts(client) -> None:
    resp = await client.get("/lookback")
    data = resp.json()
    assert data["buckets"] == []


@pytest.mark.asyncio
async def test_lookback_source_badge(client) -> None:
    resp = await client.get("/lookback")
    data = resp.json()
    assert data["source_badge"] in ("replay-csv", "replay-pcap", "live-mirror", "validated-thor-benchmark")


# ──────────────────────────────────────────────────────────────────────────────
# /forecast
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forecast_returns_200(client) -> None:
    resp = await client.get("/forecast")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_forecast_null_when_no_snapshots(client) -> None:
    resp = await client.get("/forecast")
    data = resp.json()
    assert data["forecast"] is None
    assert "message" in data


@pytest.mark.asyncio
async def test_forecast_returns_latest_snapshot(client, tmp_path: Path) -> None:
    import jetson_edge_ai_security.api.main as main_module

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    await main_module._STORE.insert_forecast_snapshot(
        generated_at=ts,
        payload={"predicted_intensity": [1.0, 2.0, 3.0]},
    )
    resp = await client.get("/forecast")
    data = resp.json()
    assert data["forecast"] is not None
    assert data["source_badge"] is not None


@pytest.mark.asyncio
async def test_forecast_structure(client, tmp_path: Path) -> None:
    import jetson_edge_ai_security.api.main as main_module

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    await main_module._STORE.insert_forecast_snapshot(generated_at=ts)
    resp = await client.get("/forecast")
    data = resp.json()
    assert "source_badge" in data
    assert "forecast" in data
