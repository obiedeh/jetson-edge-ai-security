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


class MqttConfig(BaseModel):
    """Settings for the MQTT telemetry source (``edge-security run-mqtt``)."""

    broker_url: str = "mqtt://localhost:1883"
    topics: list[str] = Field(default_factory=lambda: ["edge-security/telemetry/#"])
    client_id: str = "edge-security"
    qos: int = Field(default=0, ge=0, le=2)
    keepalive: int = Field(default=60, ge=1)
    queue_size: int = Field(default=10000, ge=1)
    field_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="canonical TelemetryEvent field -> accepted payload keys; overlays the defaults.",
    )


class JsonlSinkConfig(BaseModel):
    enabled: bool = False
    path: Path = Path("reports/live/alerts.jsonl")
    append: bool = True


class SqliteSinkConfig(BaseModel):
    """Feed the dashboard's AlertStore (data/alerts.db) from the pipeline."""

    enabled: bool = False
    db_path: Path = Path("data/alerts.db")


class IotCoreSinkConfig(BaseModel):
    """AWS IoT Core publishing. Off by default; credentials never live in git.

    Empty ``endpoint``/``thing_name``/``cert_path``/``key_path``/``ca_path``
    fall back to ``EDGE_SECURITY_IOT_ENDPOINT`` / ``_THING`` / ``_CERT`` /
    ``_KEY`` / ``_CA`` environment variables.
    """

    enabled: bool = False
    endpoint: str = ""
    thing_name: str = ""
    cert_path: str = ""
    key_path: str = ""
    ca_path: str = ""
    client_id: str = ""
    port: int = Field(default=8883, ge=1, le=65535)
    topic_root: str = "edge-security"
    qos: int = Field(default=1, ge=0, le=1)
    queue_size: int = Field(default=1000, ge=1)
    max_retries: int = Field(default=5, ge=0)
    backoff_base_seconds: float = Field(default=0.5, ge=0)
    backoff_max_seconds: float = Field(default=30.0, ge=0)
    health_interval_windows: int = Field(
        default=100, ge=0, description="Publish a health snapshot every N windows (0 = only at the end)."
    )


class SinksConfig(BaseModel):
    jsonl: JsonlSinkConfig = Field(default_factory=JsonlSinkConfig)
    sqlite: SqliteSinkConfig = Field(default_factory=SqliteSinkConfig)
    iot_core: IotCoreSinkConfig = Field(default_factory=IotCoreSinkConfig)


class AppConfig(BaseModel):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    sinks: SinksConfig = Field(default_factory=SinksConfig)


def load_config(path: str | Path) -> AppConfig:
    import yaml

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(data)
