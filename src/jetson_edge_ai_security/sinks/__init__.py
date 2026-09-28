"""Alert sinks: destinations for emitted alerts."""

from jetson_edge_ai_security.sinks.base import AlertSink
from jetson_edge_ai_security.sinks.factory import build_sinks, resolve_iot_core_settings
from jetson_edge_ai_security.sinks.iot_core import IotCoreAlertSink, IotCoreSettings
from jetson_edge_ai_security.sinks.jsonl import JsonlAlertSink
from jetson_edge_ai_security.sinks.sqlite import SqliteAlertSink

__all__ = [
    "AlertSink",
    "IotCoreAlertSink",
    "IotCoreSettings",
    "JsonlAlertSink",
    "SqliteAlertSink",
    "build_sinks",
    "resolve_iot_core_settings",
]
