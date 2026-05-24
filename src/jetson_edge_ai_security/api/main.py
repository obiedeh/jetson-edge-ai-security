"""FastAPI backend — Edge IDS web dashboard API.

Routes (§3 of the implementation brief):
    GET  /alerts              Cursor-paginated alert list.
    GET  /alerts/sse          Server-Sent Events stream.
    GET  /lookback            Bucketed attack counts for the last N minutes.
    GET  /forecast            Most recent ForecastReport snapshot.
    GET  /models              Available Detector + Forecaster implementations.
    POST /models/active       Set active Detector / Forecaster.
    GET  /model-health        Drift KPI: moving-average AUC, FPR, retrain flag.
    GET  /artifacts           List files under reports/, artifacts/, models/exports/.
    GET  /artifacts/{path}    Stream a single artifact.
    POST /benchmark/thor      Trigger Thor benchmark (409 when not on Thor).
    GET  /benchmark/runs      List benchmark runs.

Run with:
    uvicorn jetson_edge_ai_security.api.main:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from jetson_edge_ai_security.alerts.store import AlertStore
from jetson_edge_ai_security.api.sse import alert_event_stream

# ──────────────────────────────────────────────────────────────────────────────
# Shared state (module-level; tests may replace these before lifespan runs)
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR = Path(os.getenv("EDGE_IDS_DATA_DIR", "data"))
_STORE = AlertStore(db_path=_DATA_DIR / "alerts.db")

_REPORTS_DIR = Path(os.getenv("EDGE_IDS_REPORTS_DIR", "reports"))
_ARTIFACTS_DIR = Path(os.getenv("EDGE_IDS_ARTIFACTS_DIR", "artifacts"))
_MODELS_DIR = Path(os.getenv("EDGE_IDS_MODELS_DIR", "models/exports"))

_CONFIG_PATH = Path(os.getenv("EDGE_IDS_CONFIG", "configs/default.yaml"))

# ──────────────────────────────────────────────────────────────────────────────
# App + CORS
# ──────────────────────────────────────────────────────────────────────────────


_DEMO_ATTACK_TYPES = [
    "DDoS_ICMP", "DDoS_UDP", "DDoS_TCP", "DDoS_HTTP",
    "Uploading", "Ransomware", "Normal",
]
_DEMO_WEIGHTS = [20, 15, 15, 10, 15, 10, 15]
_demo_rng = random.Random()

# Mutable background-task registry so /runtime/restart can cancel+recreate.
_bg_tasks: list[asyncio.Task[None]] = []
_tick_interval: float = float(os.getenv("EDGE_IDS_DEMO_TICK", "30"))
_forecast_interval: float = float(os.getenv("EDGE_IDS_FORECAST_TICK", "300"))


def _active_source() -> str:
    """Return the currently configured input source (reads config each call)."""
    runtime = _load_config().get("runtime", {})
    if not isinstance(runtime, dict):
        return "replay-csv"
    return str(runtime.get("source", "replay-csv"))


async def _demo_alert_ticker(interval: float = 30.0) -> None:
    """Insert one synthetic alert every *interval* seconds using the active source.

    Reads the runtime source from config on each tick so a /runtime/restart
    takes effect immediately on the next alert without restarting the process.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            source = _active_source()
            attack_type = _demo_rng.choices(_DEMO_ATTACK_TYPES, weights=_DEMO_WEIGHTS)[0]
            await _STORE.insert_alert(
                timestamp=datetime.now(UTC),
                attack_type=attack_type,
                confidence=round(_demo_rng.uniform(0.55, 0.99), 4),
                severity=_demo_rng.choice(["low", "medium", "high", "critical"]),
                source=source,
                payload={
                    "source_ip": f"10.0.{_demo_rng.randint(0, 5)}.{_demo_rng.randint(1, 254)}",
                    "dest_ip": f"192.168.1.{_demo_rng.randint(1, 10)}",
                    "demo": True,
                },
            )
        except Exception:
            pass  # never crash the server over a demo tick


_FEATURE_DIM = 57
_LOOKBACK_BINS = 20
_BIN_SECONDS = 300  # 5 minutes per bin

_ATTACK_TYPES_ORDERED = [
    "Normal", "DDoS_ICMP", "DDoS_UDP", "DDoS_TCP", "DDoS_HTTP",
    "Uploading", "Downloading", "SQL_Injection", "Password",
    "Vulnerability_scanner", "Backdoor", "Port_Scanning",
    "XSS", "Ransomware", "MITM",
]


async def _run_forecast_once() -> None:
    """Build a feature history from recent alert buckets, run the active
    forecaster, and write a snapshot to the store."""
    import numpy as np

    # Pull enough history to fill 20 bins (each 5 min = 100 min total)
    lookback_minutes = _LOOKBACK_BINS * (_BIN_SECONDS // 60)
    buckets = await _STORE.get_lookback_buckets(
        minutes=lookback_minutes, bucket_seconds=_BIN_SECONDS
    )
    if not buckets:
        return

    # Group counts by bucket timestamp
    from collections import defaultdict
    by_bucket: dict[str, dict[str, float]] = defaultdict(dict)
    for b in buckets:
        by_bucket[b["bucket"]][b["attack_type"]] = float(b["count"])

    sorted_keys = sorted(by_bucket)[-_LOOKBACK_BINS:]

    # Build (lookback_bins, feature_dim) float32 matrix
    history = np.zeros((_LOOKBACK_BINS, _FEATURE_DIM), dtype=np.float32)
    offset = _LOOKBACK_BINS - len(sorted_keys)
    for i, key in enumerate(sorted_keys):
        counts = by_bucket[key]
        total = max(sum(counts.values()), 1.0)
        for j, atype in enumerate(_ATTACK_TYPES_ORDERED):
            history[offset + i, j] = counts.get(atype, 0.0) / total
        history[offset + i, len(_ATTACK_TYPES_ORDERED)] = min(total / 50.0, 1.0)

    # Load the active forecaster
    cfg = _load_config()
    active_name = cfg.get("models", {}).get("forecaster_active", "mock-forecaster")

    try:
        if active_name == "mock-forecaster":
            from jetson_edge_ai_security.models.mock_forecaster import MockForecaster
            forecaster = MockForecaster(
                lookback_bins=_LOOKBACK_BINS, bin_seconds=_BIN_SECONDS
            )
        else:
            import pickle
            pkl = _MODELS_DIR / "ar_forecaster.pkl"
            if not pkl.exists():
                return
            with pkl.open("rb") as fh:
                forecaster = pickle.load(fh)

        result = forecaster.forecast(history)
    except Exception:
        return

    # ── History-aware type override ────────────────────────────────────────
    # The mock forecaster has a hardcoded class-0 (Normal) bias that makes
    # it always predict Normal regardless of input.  For the live API
    # forecast we instead derive type predictions directly from the actual
    # recent alert distribution so the chart reflects real anomalies.
    #
    # Strategy: sum counts across the most-recent 6 bins (last 30 min).
    # If attacks are present, dominant attack type carries forward with a
    # linear decay across the 6 forecast bins (attacks are expected to
    # persist near-term but diminish further out).  Pure-Normal history
    # keeps the Normal prediction unchanged.
    n_horizon = result.forecast_horizon_bins
    recent_keys = sorted_keys[-n_horizon:] if len(sorted_keys) >= n_horizon else sorted_keys
    recent_counts: dict[str, float] = {}
    for key in recent_keys:
        for atype, cnt in by_bucket[key].items():
            recent_counts[atype] = recent_counts.get(atype, 0.0) + cnt

    total_recent = max(sum(recent_counts.values()), 1.0)
    attack_counts = {k: v for k, v in recent_counts.items() if k != "Normal"}
    attack_total = sum(attack_counts.values())
    attack_rate = attack_total / total_recent

    # Per-class probabilities from real counts
    per_class_probs = {
        atype: recent_counts.get(atype, 0.0) / total_recent
        for atype in _ATTACK_TYPES_ORDERED
    }

    if attack_counts:
        dominant_type = max(attack_counts, key=lambda k: attack_counts[k])
        # Decay: 6 bins → 100 % → 80 % → 60 % → 45 % → 30 % → 15 %
        decay = [1.0, 0.8, 0.6, 0.45, 0.3, 0.15]
        type_per_bin = []
        intensity_per_bin = []
        for i in range(n_horizon):
            d = decay[i] if i < len(decay) else 0.1
            # Bin is labelled attack while decay > 0.5, else Normal
            type_per_bin.append(dominant_type if d > 0.5 else "Normal")
            intensity_per_bin.append(float(attack_rate * d))
        forecast_attack_type = dominant_type
        forecast_probability = min(attack_rate * 1.5, 0.99)
    else:
        # No recent attacks → keep forecaster output as-is
        type_per_bin = result.predicted_attack_type_per_bin
        intensity_per_bin = result.predicted_attack_intensity.tolist()
        forecast_attack_type = result.attack_type
        forecast_probability = result.probability
    # ── end override ───────────────────────────────────────────────────────

    from datetime import timedelta
    now = datetime.now(UTC)
    horizon_seconds = n_horizon * _BIN_SECONDS
    await _STORE.insert_forecast_snapshot(
        generated_at=now,
        model_run_id=f"live-{now.isoformat()}",
        lookback_window_seconds=lookback_minutes * 60,
        forecast_horizon_seconds=horizon_seconds,
        payload={
            "probability": forecast_probability,
            "attack_type": forecast_attack_type,
            "per_class_probabilities": per_class_probs,
            "forecast_horizon_bins": n_horizon,
            "predicted_attack_intensity": intensity_per_bin,
            "predicted_attack_type_per_bin": type_per_bin,
            "generated_at": now.isoformat(),
            "horizon_end": (now + timedelta(seconds=horizon_seconds)).isoformat(),
            "active_forecaster": active_name,
            "bin_seconds": _BIN_SECONDS,
        },
    )


async def _forecast_ticker(interval: float = 300.0) -> None:
    """Generate and persist a forecast snapshot every *interval* seconds.
    Runs once immediately on startup, then repeats.
    Controlled by EDGE_IDS_FORECAST_TICK (set to '0' to disable).
    """
    # First run right away so there's data before the first 5-min wait
    await asyncio.sleep(2)  # let the demo ticker seed a few alerts first
    try:
        await _run_forecast_once()
    except Exception:
        pass
    while True:
        await asyncio.sleep(interval)
        try:
            await _run_forecast_once()
        except Exception:
            pass


def _start_bg_tasks() -> None:
    """Spawn (or re-spawn) the demo-ticker and forecast-ticker tasks."""
    global _bg_tasks
    if _tick_interval > 0:
        _bg_tasks.append(asyncio.create_task(_demo_alert_ticker(_tick_interval)))
    if _forecast_interval > 0:
        _bg_tasks.append(asyncio.create_task(_forecast_ticker(_forecast_interval)))


async def _stop_bg_tasks() -> None:
    """Cancel all running background tasks and drain them."""
    global _bg_tasks
    for t in _bg_tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    _bg_tasks.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    await _STORE.init()
    _start_bg_tasks()
    try:
        yield
    finally:
        await _stop_bg_tasks()


app = FastAPI(
    title="Edge IDS API",
    description="Defensive edge-security telemetry runtime — web dashboard backend.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_config() -> dict[str, Any]:
    if _CONFIG_PATH.exists():
        with _CONFIG_PATH.open() as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _save_config(cfg: dict[str, Any]) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _CONFIG_PATH.open("w") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)


def _load_training_run() -> dict[str, Any]:
    path = _REPORTS_DIR / "training_run.json"
    if path.exists():
        with path.open() as fh:
            data = json.load(fh)
            return cast(dict[str, Any], data) if isinstance(data, dict) else {}
    return {}


def _load_benchmark_runs() -> list[dict[str, Any]]:
    path = _REPORTS_DIR / "thor_benchmark.json"
    if path.exists():
        with path.open() as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else [data]
    return []


def _is_on_thor() -> bool:
    """Return True if running on Jetson hardware (basic heuristic)."""
    soc = os.getenv("JETSON_SOC", "")
    if soc:
        return True
    machine = platform.machine().lower()
    return machine in ("aarch64", "arm64") and Path("/etc/nv_tegra_release").exists()


# ──────────────────────────────────────────────────────────────────────────────
# GET /alerts
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/alerts")
async def get_alerts(
    since: str | None = None,
    attack_type: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: int | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated alerts, most recent first."""
    rows = await _STORE.get_alerts(
        since=since,
        attack_type=attack_type,
        severity=severity,
        source=source,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = rows[-1]["id"] if len(rows) == limit else None
    return {
        "alerts": rows,
        "count": len(rows),
        "next_cursor": next_cursor,
        "source_badge": "replay-csv",
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /alerts/sse
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/alerts/sse")
async def alerts_sse() -> EventSourceResponse:
    """Server-Sent Events stream — one event per new alert."""
    return EventSourceResponse(alert_event_stream())


# ──────────────────────────────────────────────────────────────────────────────
# GET /lookback
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/lookback")
async def get_lookback(
    minutes: int = Query(default=60, ge=1, le=1440),
    bucket_seconds: int = Query(default=300, ge=60, le=3600),
) -> dict[str, Any]:
    """Return bucketed attack counts for the last *minutes* minutes."""
    buckets = await _STORE.get_lookback_buckets(
        minutes=minutes,
        bucket_seconds=bucket_seconds,
    )
    return {
        "minutes": minutes,
        "bucket_seconds": bucket_seconds,
        "buckets": buckets,
        "source_badge": "replay-csv",
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /forecast
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/forecast")
async def get_forecast() -> dict[str, Any]:
    """Return the most recent ForecastReport snapshot from the store."""
    snapshot = await _STORE.get_latest_forecast()
    if snapshot is None:
        return {
            "forecast": None,
            "source_badge": "replay-csv",
            "message": "No forecast snapshots available yet.",
        }
    # Parse payload_json
    payload: dict[str, Any] = {}
    if snapshot.get("payload_json"):
        try:
            payload = json.loads(snapshot["payload_json"])
        except json.JSONDecodeError:
            payload = {}
    return {
        "forecast": {**snapshot, "payload": payload},
        "source_badge": "replay-csv",
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /models
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/models")
async def list_models() -> dict[str, Any]:
    """List available Detector and Forecaster implementations."""
    training_run = _load_training_run()
    cfg = _load_config()
    active_detector = cfg.get("models", {}).get("detector_active", "mock-detector")
    active_forecaster = cfg.get("models", {}).get("forecaster_active", "mock-forecaster")

    detectors: list[dict[str, Any]] = []
    forecasters: list[dict[str, Any]] = []

    # Mock detector (always available)
    detectors.append({
        "name": "mock-detector",
        "architecture": "mock",
        "available": True,
        "active": active_detector == "mock-detector",
        "onnx_path": None,
        "metrics": {},
        "latency": {},
    })

    # Reference GBM detector
    det_pkl = _MODELS_DIR / "gbm_detector.pkl"
    det_onnx = _MODELS_DIR / "gbm_detector.onnx"
    if det_pkl.exists():
        det_info = training_run.get("detector", {})
        det_eval = det_info.get("evaluation") or det_info.get("metrics") or {}
        detectors.append({
            "name": "gbm-detector",
            "architecture": "GradientBoostingClassifier",
            "available": True,
            "active": active_detector == "gbm-detector",
            "onnx_path": str(det_onnx) if det_onnx.exists() else None,
            "metrics": det_eval,
            "gate": det_info.get("gate", {}),
            "latency": det_info.get("latency_cpu", {}),
        })

    # Mock forecaster (always available)
    forecasters.append({
        "name": "mock-forecaster",
        "architecture": "mock",
        "available": True,
        "active": active_forecaster == "mock-forecaster",
        "onnx_path": None,
        "metrics": {},
        "latency": {},
    })

    # Reference AR forecaster
    fcast_pkl = _MODELS_DIR / "ar_forecaster.pkl"
    fcast_onnx = _MODELS_DIR / "ar_forecaster.onnx"
    if fcast_pkl.exists():
        fcast_info = training_run.get("forecaster", {})
        fcast_eval = fcast_info.get("evaluation") or fcast_info.get("metrics") or {}
        forecasters.append({
            "name": "ar-forecaster",
            "architecture": "Pipeline(StandardScaler, Ridge)",
            "available": True,
            "active": active_forecaster == "ar-forecaster",
            "onnx_path": str(fcast_onnx) if fcast_onnx.exists() else None,
            "metrics": fcast_eval,
            "gate": fcast_info.get("gate", {}),
            "latency": fcast_info.get("latency_cpu", {}),
        })

    return {
        "detectors": detectors,
        "forecasters": forecasters,
        "active_detector": active_detector,
        "active_forecaster": active_forecaster,
    }


# ──────────────────────────────────────────────────────────────────────────────
# POST /models/active
# ──────────────────────────────────────────────────────────────────────────────


class SetActiveModelRequest(BaseModel):
    model_type: str  # "detector" | "forecaster"
    model_name: str


@app.post("/models/active")
async def set_active_model(req: SetActiveModelRequest) -> dict[str, Any]:
    """Set the active Detector or Forecaster."""
    if req.model_type not in ("detector", "forecaster"):
        raise HTTPException(
            status_code=400,
            detail="model_type must be 'detector' or 'forecaster'",
        )
    cfg = _load_config()
    cfg.setdefault("models", {})
    key = "detector_active" if req.model_type == "detector" else "forecaster_active"
    cfg["models"][key] = req.model_name
    _save_config(cfg)
    return {"ok": True, "model_type": req.model_type, "model_name": req.model_name}


# ──────────────────────────────────────────────────────────────────────────────
# GET /model-health
# ──────────────────────────────────────────────────────────────────────────────

_RETRAIN_AUC_FLOOR = float(os.getenv("RETRAIN_AUC_FLOOR", "0.90"))


@app.get("/model-health")
async def model_health() -> dict[str, Any]:
    """Drift KPI: moving-average AUC, FPR per class, retrain_recommended flag."""
    training_run = _load_training_run()
    model_runs = await _STORE.get_model_runs(limit=10)

    # Build AUC history from model_runs table for sparkline
    auc_history: list[float] = [r["auc"] for r in model_runs if r.get("auc") is not None]
    moving_avg_auc = sum(auc_history) / len(auc_history) if auc_history else None

    det_info = training_run.get("detector", {})
    det_eval = det_info.get("evaluation") or det_info.get("metrics") or {}
    train_auc: float | None = det_eval.get("gbc_auc")
    retrain_recommended = (
        (moving_avg_auc is not None and moving_avg_auc < _RETRAIN_AUC_FLOOR)
        or (train_auc is not None and train_auc < _RETRAIN_AUC_FLOOR)
    )

    fcast_info = training_run.get("forecaster", {})
    fcast_eval = fcast_info.get("evaluation") or fcast_info.get("metrics") or {}

    return {
        "detector": {
            "name": "gbm-detector",
            "train_auc": train_auc,
            "train_f1": det_eval.get("f1"),
            "auc_history": auc_history,
            "moving_avg_auc": moving_avg_auc,
            "retrain_auc_floor": _RETRAIN_AUC_FLOOR,
            "retrain_recommended": retrain_recommended,
            "latency": det_info.get("latency_cpu", {}),
            "gate": det_info.get("gate", {}),
        },
        "forecaster": {
            "name": "ar-forecaster",
            "train_mae": fcast_eval.get("ridge_mae"),
            "mae_reduction_pct": fcast_eval.get("mae_reduction_pct"),
            "latency": fcast_info.get("latency_cpu", {}),
            "gate": fcast_info.get("gate", {}),
        },
        "recent_model_runs": model_runs,
        "source_badge": "replay-csv",
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /artifacts
# ──────────────────────────────────────────────────────────────────────────────


def _scan_artifacts() -> list[dict[str, Any]]:
    """Walk known artifact directories and return file metadata."""
    dirs = [
        (_REPORTS_DIR, "report"),
        (_ARTIFACTS_DIR, "artifact"),
        (_MODELS_DIR, "model"),
    ]
    results: list[dict[str, Any]] = []
    for base, kind in dirs:
        if not base.exists():
            continue
        base_abs = base.resolve()
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            try:
                stat = p.stat()
                p_abs = p.resolve()
                try:
                    relative = str(p_abs.relative_to(base_abs.parent))
                except ValueError:
                    relative = str(p_abs)
                results.append({
                    "path": str(p_abs),
                    "relative_path": relative,
                    "name": p.name,
                    "kind": kind,
                    "size_bytes": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    "suffix": p.suffix,
                })
            except OSError:
                continue
    return results


@app.get("/artifacts")
async def list_artifacts() -> dict[str, Any]:
    """List files under reports/, artifacts/, and models/exports/."""
    return {
        "artifacts": _scan_artifacts(),
        "source_badge": "replay-csv",
    }


@app.get("/artifacts/{artifact_path:path}")
async def get_artifact(artifact_path: str) -> Response:
    """Stream a single artifact file."""
    # Accept both absolute and relative paths; resolve to absolute
    candidate = Path(artifact_path)
    if not candidate.is_absolute():
        candidate = Path(".") / candidate
    target = candidate.resolve()

    # Security: only allow files inside known directories
    allowed = [
        _REPORTS_DIR.resolve(),
        _ARTIFACTS_DIR.resolve(),
        _MODELS_DIR.resolve(),
    ]
    if not any(str(target).startswith(str(base)) for base in allowed):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    return FileResponse(path=str(target), filename=target.name)


# ──────────────────────────────────────────────────────────────────────────────
# POST /benchmark/thor
# ──────────────────────────────────────────────────────────────────────────────


@app.post("/benchmark/thor")
async def trigger_thor_benchmark() -> dict[str, Any]:
    """Trigger a Thor benchmark run.  Returns 409 when not running on Thor."""
    if not _is_on_thor():
        raise HTTPException(
            status_code=409,
            detail="Not running on Jetson hardware. Thor benchmark is only valid on aarch64 with JETSON_SOC set.",
        )
    script = Path("deploy/thor/run_benchmark.py")
    if not script.exists():
        raise HTTPException(status_code=503, detail="Benchmark script not found.")
    # Fire and forget — run detached so the endpoint returns immediately
    subprocess.Popen(
        ["python3", str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "started": True,
        "message": "Benchmark started in background. Poll /benchmark/runs for results.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /benchmark/runs
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/benchmark/runs")
async def benchmark_runs() -> dict[str, Any]:
    """List benchmark runs with run-hash, hardware tag, latency, throughput, power."""
    return {
        "runs": _load_benchmark_runs(),
        "source_badge": "validated-thor-benchmark" if _load_benchmark_runs() else "replay-csv",
    }


# ──────────────────────────────────────────────────────────────────────────────
# POST /runtime/restart
# ──────────────────────────────────────────────────────────────────────────────

_VALID_SOURCES = {"replay-csv", "replay-pcap", "live-mirror"}


class RestartRuntimeRequest(BaseModel):
    source: str


@app.post("/runtime/restart")
async def restart_runtime(req: RestartRuntimeRequest) -> dict[str, Any]:
    """Persist the new input source to config then hot-restart the background tasks.

    Steps:
      1. Validate the requested source.
      2. Write runtime.source to configs/default.yaml.
      3. Cancel the demo-ticker and forecast-ticker.
      4. Re-spawn both tasks (they will pick up the new source immediately).
      5. Trigger one forecast snapshot so the Lookback chart reflects the
         new source right away.
    """
    if req.source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source '{req.source}'. Must be one of: {sorted(_VALID_SOURCES)}",
        )

    # 1. Persist to config
    cfg = _load_config()
    cfg.setdefault("runtime", {})["source"] = req.source
    _save_config(cfg)

    # 2. Hot-restart background tasks
    await _stop_bg_tasks()
    _start_bg_tasks()

    # 3. Immediate forecast snapshot so the UI updates without waiting 5 min
    try:
        await _run_forecast_once()
    except Exception:
        pass

    return {
        "ok": True,
        "source": req.source,
        "message": f"Runtime restarted with source '{req.source}'. "
                   "Demo ticker and forecaster are now using the new source.",
        "restarted_at": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /runtime/status
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/runtime/status")
async def runtime_status() -> dict[str, Any]:
    """Return current runtime config (active source, bg-task count, uptime)."""
    return {
        "source": _active_source(),
        "bg_tasks_running": len([t for t in _bg_tasks if not t.done()]),
        "demo_tick_interval_s": _tick_interval,
        "forecast_tick_interval_s": _forecast_interval,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}
