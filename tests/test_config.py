"""Config loading and path resolution: config.json, overrides, '~' expansion."""

import json
import os

import pytest


# ---------------------------------------------------------------- load_config


def test_missing_config_file_uses_defaults(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    cfg = runner.load_config()
    assert cfg == {"h3_binary": "", "model_dir": ""}


def test_empty_object_uses_defaults(runner, monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(p))
    cfg = runner.load_config()
    assert cfg["h3_binary"] == "" and cfg["model_dir"] == ""


def test_config_values_are_read(runner, monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(
        {"h3_binary": "/opt/h3.c/h3", "model_dir": "/models/MiniMax-H3"}),
        encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(p))
    cfg = runner.load_config()
    assert cfg["h3_binary"] == "/opt/h3.c/h3"
    assert cfg["model_dir"] == "/models/MiniMax-H3"


def test_non_string_values_are_ignored(runner, monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"h3_binary": 123, "model_dir": "/models"}),
                 encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(p))
    cfg = runner.load_config()
    assert cfg["h3_binary"] == ""          # non-string rejected, default kept
    assert cfg["model_dir"] == "/models"


def test_broken_json_falls_back_to_defaults(runner, monkeypatch, tmp_path, capsys):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(p))
    cfg = runner.load_config()
    assert cfg == {"h3_binary": "", "model_dir": ""}
    assert "failed to read config.json" in capsys.readouterr().out


def test_config_is_cached(runner, monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(p))
    assert runner.load_config() is runner.load_config()


# ---------------------------------------------------------------- resolve_path


def test_unconfigured_raises_with_setup_guidance(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    with pytest.raises(ValueError) as exc_info:
        runner.resolve_path("", "h3_binary")
    msg = str(exc_info.value)
    assert "h3_binary" in msg
    assert "config.json" in msg
    assert "README.md" in msg  # points at the setup docs


def test_node_value_overrides_config(runner, monkeypatch):
    monkeypatch.setattr(runner, "_config_cache",
                        {"h3_binary": "/from/config", "model_dir": "/m"})
    assert runner.resolve_path("/from/node", "h3_binary") == "/from/node"


def test_empty_value_falls_back_to_config(runner, monkeypatch):
    monkeypatch.setattr(runner, "_config_cache",
                        {"h3_binary": "/from/config", "model_dir": "/m"})
    assert runner.resolve_path("", "h3_binary") == "/from/config"


def test_whitespace_value_falls_back_to_config(runner, monkeypatch):
    monkeypatch.setattr(runner, "_config_cache",
                        {"h3_binary": "/from/config", "model_dir": "/m"})
    assert runner.resolve_path("   \n ", "h3_binary") == "/from/config"


def test_tilde_expansion_from_node_value(runner):
    resolved = runner.resolve_path("~/h3.c/h3", "h3_binary")
    assert resolved == os.path.join(os.path.expanduser("~"), "h3.c/h3")


def test_tilde_expansion_from_config(runner, monkeypatch):
    monkeypatch.setattr(runner, "_config_cache",
                        {"h3_binary": "~/h3.c/h3", "model_dir": ""})
    resolved = runner.resolve_path("", "h3_binary")
    assert resolved == os.path.join(os.path.expanduser("~"), "h3.c/h3")
    assert not resolved.startswith("~")


def test_relative_paths_become_absolute(runner):
    resolved = runner.resolve_path("relative/h3", "h3_binary")
    assert os.path.isabs(resolved)
