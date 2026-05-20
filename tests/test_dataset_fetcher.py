from pathlib import Path
from zipfile import ZipFile

import pytest

import jetson_edge_ai_security.datasets.fetcher as fetcher
from jetson_edge_ai_security.datasets.catalog import DatasetSpec
from jetson_edge_ai_security.datasets.fetcher import DatasetDownloadError, prepare_dataset


def test_prepare_dataset_downloads_extracts_and_finds_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "fixture.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "nested/events.csv",
            "timestamp,source_ip,dest_ip,protocol,packet_size\n"
            "2026-01-01 00:00:00,10.0.0.1,10.0.0.2,TCP,128\n",
        )

    spec = DatasetSpec(
        key="fixture",
        name="Fixture",
        homepage_url="https://example.test/fixture",
        direct_download_url=archive_path.as_uri(),
        archive_type="zip",
        default_csv_glob="**/*.csv",
        description="Test fixture",
        citation_hint="Test fixture",
    )
    monkeypatch.setattr(fetcher, "dataset_by_key", lambda key: spec)

    prepared = prepare_dataset("fixture", cache_dir=tmp_path / "cache")

    assert prepared.csv_path.name == "events.csv"
    assert prepared.csv_path.read_text(encoding="utf-8").startswith("timestamp")


def test_prepare_dataset_rejects_manual_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = DatasetSpec(
        key="manual",
        name="Manual",
        homepage_url="https://example.test/manual",
        direct_download_url=None,
        archive_type=None,
        default_csv_glob="**/*.csv",
        description="Manual fixture",
        citation_hint="Manual fixture",
        requires_manual_download=True,
    )
    monkeypatch.setattr(fetcher, "dataset_by_key", lambda key: spec)

    with pytest.raises(DatasetDownloadError):
        prepare_dataset("manual", cache_dir=tmp_path / "cache")


def test_dataset_by_key_unknown_raises() -> None:
    from jetson_edge_ai_security.datasets.catalog import dataset_by_key

    with pytest.raises(KeyError, match="Unknown dataset"):
        dataset_by_key("nonexistent-dataset-xyz")


def test_prepare_dataset_force_re_extracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "fixture.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("events.csv", "timestamp,source_ip\n2026-01-01,10.0.0.1\n")

    spec = DatasetSpec(
        key="fixture2",
        name="Fixture2",
        homepage_url="https://example.test/fixture2",
        direct_download_url=archive_path.as_uri(),
        archive_type="zip",
        default_csv_glob="*.csv",
        description="Test fixture",
        citation_hint="Test",
    )
    monkeypatch.setattr(fetcher, "dataset_by_key", lambda key: spec)

    cache = tmp_path / "cache"
    # First run
    p1 = prepare_dataset("fixture2", cache_dir=cache)
    assert p1.csv_path.exists()

    # Force re-run — must succeed and produce the same CSV
    p2 = prepare_dataset("fixture2", cache_dir=cache, force=True)
    assert p2.csv_path.exists()
    assert p2.csv_path.name == "events.csv"

