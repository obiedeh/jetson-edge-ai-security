#!/usr/bin/env python
"""Replay a telemetry CSV as JSON messages to an MQTT topic (local demo only).

Each CSV row is published as one JSON object whose keys are the CSV headers,
so ``edge-security run-mqtt`` maps them with the same aliases the CSV replay
source uses. Numeric-looking values are sent as numbers.

Example::

    python deploy/mqtt-demo/publish_sample.py --rate 200
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "tests" / "fixtures" / "telemetry_replay_sample.csv"


def _coerce(value: str) -> Any:
    text = value.strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV file to replay.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="edge-security/telemetry/demo-sensor")
    parser.add_argument("--qos", type=int, default=0, choices=(0, 1, 2))
    parser.add_argument("--rate", type=float, default=100.0, help="Messages per second (0 = as fast as possible).")
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many rows.")
    parser.add_argument("--loop", action="store_true", help="Replay the file repeatedly until Ctrl-C.")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-security-demo-publisher")
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()

    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    sent = 0
    try:
        while True:
            with args.csv.open("r", newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    payload = {key: _coerce(value) for key, value in row.items() if value is not None}
                    payload = {key: value for key, value in payload.items() if value is not None}
                    client.publish(args.topic, json.dumps(payload), qos=args.qos)
                    sent += 1
                    if args.limit is not None and sent >= args.limit:
                        raise StopIteration
                    if interval:
                        time.sleep(interval)
            if not args.loop:
                break
    except (StopIteration, KeyboardInterrupt):
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"published {sent} messages to {args.topic} on {args.host}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
