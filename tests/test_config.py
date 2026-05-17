from pathlib import Path

import pytest

from jetson_edge_ai_security.config import AppConfig, load_config


def test_load_config_from_default_yaml():
    config_path = Path(__file__).parent.parent / "configs" / "default.yaml"

    config = load_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.runtime.window_size >= 1
    assert config.runtime.step >= 1


def test_load_config_applies_overrides(tmp_path: Path):
    cfg = tmp_path / "custom.yaml"
    cfg.write_text(
        "runtime:\n  window_size: 25\n  step: 5\n",
        encoding="utf-8",
    )

    config = load_config(cfg)

    assert config.runtime.window_size == 25
    assert config.runtime.step == 5


def test_load_config_empty_file_uses_defaults(tmp_path: Path):
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("", encoding="utf-8")

    config = load_config(cfg)

    assert config.runtime.window_size == 50


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(tmp_path / "nonexistent.yaml")


def test_appconfig_validates_window_size_ge_1():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AppConfig.model_validate({"runtime": {"window_size": 0}})
