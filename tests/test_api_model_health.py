"""Tests for /models, /models/active, /model-health, /artifacts, and /benchmark endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def client(tmp_path: Path):
    """AsyncClient with isolated temp DB and directories."""
    import jetson_edge_ai_security.api.main as main_module
    from jetson_edge_ai_security.alerts.store import AlertStore

    main_module._STORE = AlertStore(db_path=tmp_path / "alerts.db")
    main_module._DATA_DIR = tmp_path
    main_module._REPORTS_DIR = tmp_path / "reports"
    main_module._ARTIFACTS_DIR = tmp_path / "artifacts"
    main_module._MODELS_DIR = tmp_path / "models"
    main_module._CONFIG_PATH = tmp_path / "configs" / "default.yaml"

    (tmp_path / "reports").mkdir()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "configs").mkdir()

    from jetson_edge_ai_security.api.main import app

    await main_module._STORE.init()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ──────────────────────────────────────────────────────────────────────────────
# /alerts
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alerts_endpoint_200(client) -> None:
    resp = await client.get("/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert "count" in data
    assert "source_badge" in data


@pytest.mark.asyncio
async def test_alerts_empty_list(client) -> None:
    resp = await client.get("/alerts")
    data = resp.json()
    assert data["alerts"] == []
    assert data["count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# /models
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_models_endpoint_200(client) -> None:
    resp = await client.get("/models")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_models_response_structure(client) -> None:
    resp = await client.get("/models")
    data = resp.json()
    assert "detectors" in data
    assert "forecasters" in data
    assert "active_detector" in data
    assert "active_forecaster" in data


@pytest.mark.asyncio
async def test_models_always_includes_mock(client) -> None:
    resp = await client.get("/models")
    data = resp.json()
    detector_names = [d["name"] for d in data["detectors"]]
    forecaster_names = [f["name"] for f in data["forecasters"]]
    assert "mock-detector" in detector_names
    assert "mock-forecaster" in forecaster_names


@pytest.mark.asyncio
async def test_models_active_defaults(client) -> None:
    resp = await client.get("/models")
    data = resp.json()
    assert data["active_detector"] == "mock-detector"
    assert data["active_forecaster"] == "mock-forecaster"


# ──────────────────────────────────────────────────────────────────────────────
# POST /models/active
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_active_model_detector(client) -> None:
    resp = await client.post(
        "/models/active",
        json={"model_type": "detector", "model_name": "gbm-detector"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["model_name"] == "gbm-detector"


@pytest.mark.asyncio
async def test_set_active_model_forecaster(client) -> None:
    resp = await client.post(
        "/models/active",
        json={"model_type": "forecaster", "model_name": "ar-forecaster"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_set_active_model_invalid_type(client) -> None:
    resp = await client.post(
        "/models/active",
        json={"model_type": "invalid", "model_name": "test"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_set_active_model_persists(client, tmp_path: Path) -> None:

    await client.post(
        "/models/active",
        json={"model_type": "detector", "model_name": "gbm-detector"},
    )
    resp = await client.get("/models")
    data = resp.json()
    assert data["active_detector"] == "gbm-detector"


# ──────────────────────────────────────────────────────────────────────────────
# /model-health
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_health_endpoint_200(client) -> None:
    resp = await client.get("/model-health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_model_health_response_structure(client) -> None:
    resp = await client.get("/model-health")
    data = resp.json()
    assert "detector" in data
    assert "forecaster" in data
    assert "source_badge" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_model_health_retrain_flag_structure(client) -> None:
    resp = await client.get("/model-health")
    data = resp.json()
    assert "retrain_recommended" in data["detector"]
    assert isinstance(data["detector"]["retrain_recommended"], bool)


@pytest.mark.asyncio
async def test_model_health_with_training_run(client, tmp_path: Path) -> None:
    import jetson_edge_ai_security.api.main as main_module

    training_run = {
        "run_id": "test-run-001",
        "detector": {
            "metrics": {"gbc_auc": 0.98, "f1": 0.90, "if_auc": 0.64, "delta_auc": 0.34},
            "gate": {"result": "PASS"},
            "latency_cpu": {"p50_ms": 0.014, "p95_ms": 0.015},
        },
        "forecaster": {
            "metrics": {"ridge_mae": 7.5, "mae_reduction_pct": 26.84},
            "gate": {"result": "PASS"},
            "latency_cpu": {"p50_ms": 0.007},
        },
    }
    training_path = main_module._REPORTS_DIR / "training_run.json"
    training_path.parent.mkdir(parents=True, exist_ok=True)
    with training_path.open("w") as fh:
        json.dump(training_run, fh)

    resp = await client.get("/model-health")
    data = resp.json()
    assert data["detector"]["train_auc"] == pytest.approx(0.98)
    assert data["detector"]["train_f1"] == pytest.approx(0.90)
    assert data["forecaster"]["mae_reduction_pct"] == pytest.approx(26.84)


# ──────────────────────────────────────────────────────────────────────────────
# /artifacts
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifacts_endpoint_200(client) -> None:
    resp = await client.get("/artifacts")
    assert resp.status_code == 200
    data = resp.json()
    assert "artifacts" in data
    assert "source_badge" in data


@pytest.mark.asyncio
async def test_artifacts_lists_files(client, tmp_path: Path) -> None:
    import jetson_edge_ai_security.api.main as main_module

    # Write a test artifact
    test_file = main_module._REPORTS_DIR / "test_report.json"
    test_file.write_text('{"test": true}')

    resp = await client.get("/artifacts")
    data = resp.json()
    names = [a["name"] for a in data["artifacts"]]
    assert "test_report.json" in names


@pytest.mark.asyncio
async def test_artifact_stream_file(client, tmp_path: Path) -> None:
    import jetson_edge_ai_security.api.main as main_module

    test_file = main_module._REPORTS_DIR / "data.json"
    test_file.write_text('{"hello": "world"}')

    # Pass absolute path — the endpoint accepts absolute paths within allowed dirs
    resp = await client.get(f"/artifacts/{test_file.resolve()}")
    assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# /benchmark
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_benchmark_runs_endpoint_200(client) -> None:
    resp = await client.get("/benchmark/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "source_badge" in data


@pytest.mark.asyncio
async def test_benchmark_thor_returns_409_not_on_jetson(client) -> None:
    # We are not on Jetson, so this should return 409
    resp = await client.post("/benchmark/thor")
    assert resp.status_code == 409
