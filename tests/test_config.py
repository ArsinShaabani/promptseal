"""Config loading tests."""

import pytest

from promptseal.config import load_config


def _write(tmp_path, text):
    path = tmp_path / "promptseal.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_flaky_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, "suite: t\n"))
    assert cfg.repeat == 1
    assert cfg.flaky_pass_rate == 1.0


def test_repeat_and_flaky_from_yaml(tmp_path):
    cfg = load_config(_write(tmp_path, "defaults:\n  repeat: 5\n  flaky_pass_rate: 0.8\n"))
    assert cfg.repeat == 5
    assert cfg.flaky_pass_rate == 0.8


def test_invalid_repeat_raises(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "defaults:\n  repeat: 0\n"))


def test_invalid_flaky_rate_raises(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "defaults:\n  flaky_pass_rate: 1.5\n"))


def test_concurrency_default(tmp_path):
    cfg = load_config(_write(tmp_path, "suite: t\n"))
    assert cfg.concurrency == 1


def test_concurrency_from_yaml(tmp_path):
    cfg = load_config(_write(tmp_path, "defaults:\n  concurrency: 4\n"))
    assert cfg.concurrency == 4


def test_invalid_concurrency_raises(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "defaults:\n  concurrency: 0\n"))