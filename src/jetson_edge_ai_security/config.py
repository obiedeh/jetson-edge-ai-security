"""Runtime configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    window_size: int = Field(default=50, ge=1)
    step: int = Field(default=10, ge=1)
    replay_delay_seconds: float = Field(default=0.0, ge=0)
    strict_csv: bool = False


class DetectorConfig(BaseModel):
    packet_count_threshold: int = Field(default=500, ge=1)
    event_rate_threshold: float = Field(default=200.0, ge=0)
    unique_source_ip_threshold: int = Field(default=100, ge=1)
    attack_count_threshold: int = Field(default=1, ge=0)
    use_isolation_forest: bool = False


class AlertConfig(BaseModel):
    source: str = "edge-security-runtime"
    default_recommended_action: str = (
        "Review source telemetry, correlate with IDS logs, and isolate affected lab systems if confirmed."
    )


class AppConfig(BaseModel):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)


def load_config(path: str | Path) -> AppConfig:
    import yaml

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(data)
