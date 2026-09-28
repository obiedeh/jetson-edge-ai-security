# Traffic Source API

`TrafficSource` is the stable ingestion contract for the runtime.

```python
class TrafficSource(ABC):
    name: str

    def open(self) -> None: ...
    def events(self) -> Iterator[TelemetryEvent]: ...
    def close(self) -> None: ...
```

Sources are also context managers:

```python
with CsvReplaySource("data/sample.csv", limit=1000) as source:
    for event in source.events():
        ...
```

## Source Responsibilities

A source should:

- Own file handles, network clients, and capture sessions.
- Normalize records into `TelemetryEvent`.
- Put source-specific raw fields in `metadata`.
- Tolerate optional missing fields when safe.
- Use clear errors for unrecoverable source failures.

A source should not:

- Run detection logic.
- Generate alerts directly.
- Depend on notebook state.
- Require labels for live production traffic.
- Include offensive malware behavior or attack execution.

## CSV Replay

`CsvReplaySource` maps Edge-IIoT style columns and common IDS aliases into normalized events. It supports:

- `limit`
- `replay_delay_seconds`
- strict or forgiving malformed-row behavior
- unmapped column preservation in event metadata

## Suricata EVE JSON

`SuricataEveSource` reads `eve.json` lines in replay or `follow` (tail) mode and
normalizes `flow`, `alert` and `stats` records. Flow byte counts fill
`packet_size`; alert signature, category and severity fill `attack_label`,
`attack_type` and `metadata.alert`; stats counters land in `metadata.stats`.
Other event types are counted in `events_skipped` and malformed lines in
`rows_skipped` (or raised with `strict=True`). Follow mode stops on a
`threading.Event`, an `idle_timeout`, or a `limit`, and survives truncation
and rotation.

## MQTT Telemetry

`MqttTelemetrySource` subscribes with paho-mqtt (v2 callback API) to one or
more topics and maps JSON object payloads through a `canonical_field ->
accepted keys` map (`DEFAULT_FIELD_MAP`, overridable per field from the
`mqtt.field_map` config section). Unmapped keys go to `metadata.unmapped`
and the topic to `metadata.topic`. Messages are buffered in a bounded queue on
the network thread; the newest message is dropped and counted when it is
full. The client is created by an injectable factory so tests use a fake
client without a broker.

## Alert Sinks

Emitted alerts go to `AlertSink` implementations (`sinks/`): JSONL file, the
dashboard's SQLite store, and AWS IoT Core. Sinks are context managers with
`open`, `publish`, `flush`, `close`, and an optional `publish_health`; they
must never raise into the pipeline. `PipelineRunner(sinks=[...])` opens them
for the duration of the stream.

## Adding a Source

1. Create a module in `jetson_edge_ai_security.sources`.
2. Subclass `TrafficSource`.
3. Implement `open`, `events`, and `close`.
4. Normalize every output into `TelemetryEvent`.
5. Add tests for lifecycle, mapping, malformed data, and stream behavior.
6. Export the source from `sources/__init__.py`.

