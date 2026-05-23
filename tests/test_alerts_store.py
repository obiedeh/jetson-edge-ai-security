"""Tests for the async SQLite AlertStore.

All tests use a temporary database file so they do not affect the production
data directory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture()
def store(tmp_path: Path):
    from jetson_edge_ai_security.alerts.store import AlertStore

    return AlertStore(db_path=tmp_path / "test_alerts.db")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def _seed_alerts(store, n: int = 3) -> list[int]:
    ids = []
    for i in range(n):
        row_id = await store.insert_alert(
            timestamp=_NOW + timedelta(seconds=i),
            attack_type="DDoS_ICMP",
            severity="high",
            confidence=0.9,
            source="replay-csv",
            payload={"pkt": i},
        )
        ids.append(row_id)
    return ids


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_creates_tables(store) -> None:
    await store.init()
    # If tables already exist, second init is idempotent
    await store.init()


@pytest.mark.asyncio
async def test_insert_alert_returns_row_id(store) -> None:
    await store.init()
    row_id = await store.insert_alert(
        timestamp=_NOW,
        attack_type="DDoS_ICMP",
        severity="high",
        confidence=0.95,
    )
    assert isinstance(row_id, int)
    assert row_id >= 1


@pytest.mark.asyncio
async def test_get_alerts_empty(store) -> None:
    await store.init()
    rows = await store.get_alerts()
    assert rows == []


@pytest.mark.asyncio
async def test_get_alerts_returns_inserted_rows(store) -> None:
    await store.init()
    await _seed_alerts(store, 3)
    rows = await store.get_alerts()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_get_alerts_most_recent_first(store) -> None:
    await store.init()
    ids = await _seed_alerts(store, 3)
    rows = await store.get_alerts()
    # Most recent ID should appear first
    assert rows[0]["id"] == max(ids)


@pytest.mark.asyncio
async def test_get_alerts_filter_attack_type(store) -> None:
    await store.init()
    await _seed_alerts(store, 3)
    await store.insert_alert(
        timestamp=_NOW,
        attack_type="Ransomware",
        severity="critical",
        confidence=0.99,
    )
    rows = await store.get_alerts(attack_type="Ransomware")
    assert len(rows) == 1
    assert rows[0]["attack_type"] == "Ransomware"


@pytest.mark.asyncio
async def test_get_alerts_filter_severity(store) -> None:
    await store.init()
    await store.insert_alert(timestamp=_NOW, attack_type="DDoS_ICMP", severity="low", confidence=0.5)
    await store.insert_alert(timestamp=_NOW, attack_type="DDoS_ICMP", severity="critical", confidence=0.9)
    rows = await store.get_alerts(severity="critical")
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_get_alerts_filter_source(store) -> None:
    await store.init()
    await store.insert_alert(timestamp=_NOW, attack_type="DDoS_ICMP", severity="high",
                              confidence=0.8, source="replay-pcap")
    await store.insert_alert(timestamp=_NOW, attack_type="DDoS_ICMP", severity="high",
                              confidence=0.8, source="replay-csv")
    rows = await store.get_alerts(source="replay-pcap")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_alerts_cursor_pagination(store) -> None:
    await store.init()
    await _seed_alerts(store, 5)
    # Get first 3
    first_page = await store.get_alerts(limit=3)
    assert len(first_page) == 3
    # Cursor should allow paging
    cursor = first_page[-1]["id"]
    second_page = await store.get_alerts(limit=3, cursor=cursor)
    # Should return remaining 2
    assert len(second_page) == 2


@pytest.mark.asyncio
async def test_get_alerts_since_filter(store) -> None:
    await store.init()
    await _seed_alerts(store, 3)
    # Filter to only the last event
    since = (_NOW + timedelta(seconds=2)).isoformat()
    rows = await store.get_alerts(since=since)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_upsert_model_run(store) -> None:
    await store.init()
    await store.upsert_model_run(
        "run-001",
        started_at=_NOW,
        ended_at=_NOW + timedelta(seconds=60),
        auc=0.98,
        f1=0.95,
        detector_name="gbm-detector",
    )
    runs = await store.get_model_runs()
    assert len(runs) == 1
    assert runs[0]["id"] == "run-001"
    assert runs[0]["auc"] == pytest.approx(0.98)


@pytest.mark.asyncio
async def test_upsert_model_run_replaces_existing(store) -> None:
    await store.init()
    await store.upsert_model_run("run-001", started_at=_NOW, auc=0.90)
    await store.upsert_model_run("run-001", started_at=_NOW, auc=0.99)
    runs = await store.get_model_runs()
    assert len(runs) == 1
    assert runs[0]["auc"] == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_insert_forecast_snapshot_returns_id(store) -> None:
    await store.init()
    snap_id = await store.insert_forecast_snapshot(
        generated_at=_NOW,
        lookback_window_seconds=300,
        forecast_horizon_seconds=30,
        payload={"forecast": [1.2, 2.3]},
    )
    assert isinstance(snap_id, int)
    assert snap_id >= 1


@pytest.mark.asyncio
async def test_get_latest_forecast_none_when_empty(store) -> None:
    await store.init()
    result = await store.get_latest_forecast()
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_forecast_returns_most_recent(store) -> None:
    await store.init()
    await store.insert_forecast_snapshot(generated_at=_NOW, payload={"v": 1})
    await store.insert_forecast_snapshot(generated_at=_NOW + timedelta(seconds=5), payload={"v": 2})
    result = await store.get_latest_forecast()
    assert result is not None
    import json
    payload = json.loads(result["payload_json"])
    assert payload["v"] == 2


@pytest.mark.asyncio
async def test_get_forecasts_list(store) -> None:
    await store.init()
    for i in range(3):
        await store.insert_forecast_snapshot(generated_at=_NOW + timedelta(seconds=i))
    results = await store.get_forecasts()
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_lookback_buckets_empty(store) -> None:
    await store.init()
    buckets = await store.get_lookback_buckets(minutes=60, bucket_seconds=300)
    assert isinstance(buckets, list)
    assert buckets == []


@pytest.mark.asyncio
async def test_alert_payload_json_serialized(store) -> None:
    await store.init()
    payload = {"src_ip": "10.0.0.1", "packet_count": 500}
    await store.insert_alert(
        timestamp=_NOW,
        attack_type="Uploading",
        severity="medium",
        confidence=0.75,
        payload=payload,
    )
    rows = await store.get_alerts()
    assert len(rows) >= 1
    import json
    stored_payload = json.loads(rows[0]["payload_json"])
    assert stored_payload["src_ip"] == "10.0.0.1"
    assert stored_payload["packet_count"] == 500
