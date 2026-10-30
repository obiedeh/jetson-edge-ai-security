# MQTT ingestion demo (local Mosquitto)

Runs a Mosquitto broker in Docker, replays a sample telemetry CSV to it as
JSON messages, and consumes those messages with `edge-security run-mqtt`.
Everything stays on `127.0.0.1`; the broker allows anonymous connections and
must not be exposed beyond the workstation.

The sample data is `tests/fixtures/telemetry_replay_sample.csv`: 360 synthetic
Edge-IIoT-style rows with two labelled burst phases so the baseline detector
emits alerts. (`tests/fixtures/edge_iiotset_sample_5k.csv` is a z-scored
feature matrix and cannot be replayed through `TelemetryEvent`.)

## Commands

All commands run from the repository root with the project virtualenv active
(`uv pip install --python .venv/bin/python -e ".[dev]"` installs `paho-mqtt`).

1. Start the broker:

   ```bash
   docker compose -f deploy/mqtt-demo/docker-compose.yml up -d
   docker compose -f deploy/mqtt-demo/docker-compose.yml logs --tail 5
   ```

   Without the Compose plugin, the equivalent single container is:

   ```bash
   docker run -d --name edge-security-mosquitto -p 127.0.0.1:1883:1883 \
     -v "$PWD/deploy/mqtt-demo/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
     eclipse-mosquitto:2
   ```

2. Start the consumer in one terminal. It subscribes to the topics in the
   `mqtt:` section of `configs/default.yaml` (`edge-security/telemetry/#`) and
   prints alerts as they are emitted. `--idle-timeout` makes it exit on its own
   once the publisher is done; omit it to run until Ctrl-C.

   ```bash
   .venv/bin/edge-security run-mqtt --config configs/default.yaml --idle-timeout 5 --json-output
   ```

3. Publish the sample in a second terminal:

   ```bash
   .venv/bin/python deploy/mqtt-demo/publish_sample.py --rate 200
   ```

   Useful flags: `--loop` to replay continuously, `--limit N`, `--topic`,
   `--csv path/to/other.csv`.

4. Stop the broker:

   ```bash
   docker compose -f deploy/mqtt-demo/docker-compose.yml down
   # or: docker rm -f edge-security-mosquitto
   ```

## Field mapping

Payload keys are matched case-insensitively against the `mqtt.field_map`
section of the config (canonical `TelemetryEvent` field -> accepted keys),
which overlays the built-in defaults in
`jetson_edge_ai_security.sources.mqtt_source.DEFAULT_FIELD_MAP`. Keys that map
to nothing are kept under `metadata.unmapped`; the topic is kept in
`metadata.topic`. Payloads that are not JSON objects, or that fail
`TelemetryEvent` validation, are counted in `rows_skipped` (or raised with
`--strict`).

## Expected output

With the default `configs/default.yaml` thresholds (`window_size: 50`,
`step: 10`, `attack_count_threshold: 1`) the two burst phases produce alerts
for every window that contains labelled rows. Verified once on 2026-09-28
against `eclipse-mosquitto:2` (Docker 29.1.3, `docker run` form) with
`--rate 200`; the consumer's final line was:

```text
events=360 windows=32 alerts=20 messages=360 dropped=0 skipped_rows=0
```

Tests never start the broker; `tests/test_mqtt_source.py` uses a fake client.
