"""Build alert sinks from the ``sinks:`` config section."""

from __future__ import annotations

import os

from jetson_edge_ai_security.config import IotCoreSinkConfig, SinksConfig
from jetson_edge_ai_security.sinks.base import AlertSink
from jetson_edge_ai_security.sinks.iot_core import ClientFactory, IotCoreAlertSink, IotCoreSettings
from jetson_edge_ai_security.sinks.jsonl import JsonlAlertSink
from jetson_edge_ai_security.sinks.sqlite import SqliteAlertSink

ENV_PREFIX = "EDGE_SECURITY_IOT_"
_ENV_FIELDS = {
    "endpoint": f"{ENV_PREFIX}ENDPOINT",
    "thing_name": f"{ENV_PREFIX}THING",
    "cert_path": f"{ENV_PREFIX}CERT",
    "key_path": f"{ENV_PREFIX}KEY",
    "ca_path": f"{ENV_PREFIX}CA",
}


def resolve_iot_core_settings(config: IotCoreSinkConfig) -> IotCoreSettings:
    """Merge config values with ``EDGE_SECURITY_IOT_*`` env fallbacks; fail on missing required ones."""

    values: dict[str, str] = {}
    for field, env_name in _ENV_FIELDS.items():
        configured = str(getattr(config, field) or "").strip()
        values[field] = configured or os.environ.get(env_name, "").strip()
    missing = [
        _ENV_FIELDS[field]
        for field in ("endpoint", "thing_name", "cert_path", "key_path")
        if not values[field]
    ]
    if missing:
        raise ValueError(
            "sinks.iot_core is enabled but these settings are missing (set them in the config "
            f"or via environment variables): {', '.join(missing)}"
        )
    return IotCoreSettings(
        endpoint=values["endpoint"],
        thing_name=values["thing_name"],
        cert_path=values["cert_path"],
        key_path=values["key_path"],
        ca_path=values["ca_path"] or None,
        port=config.port,
        client_id=config.client_id or None,
    )


def build_sinks(config: SinksConfig, *, iot_client_factory: ClientFactory | None = None) -> list[AlertSink]:
    """Instantiate every enabled sink. All sinks are disabled by default."""

    sinks: list[AlertSink] = []
    if config.jsonl.enabled:
        sinks.append(JsonlAlertSink(config.jsonl.path, append=config.jsonl.append))
    if config.sqlite.enabled:
        sinks.append(SqliteAlertSink(config.sqlite.db_path))
    if config.iot_core.enabled:
        iot = config.iot_core
        sinks.append(
            IotCoreAlertSink(
                resolve_iot_core_settings(iot),
                topic_root=iot.topic_root,
                qos=iot.qos,
                queue_size=iot.queue_size,
                max_retries=iot.max_retries,
                backoff_base=iot.backoff_base_seconds,
                backoff_max=iot.backoff_max_seconds,
                client_factory=iot_client_factory,
            )
        )
    return sinks
