"""Tests for environment-only Telegram configuration."""

import pytest

from bot.config import ConfigError, load_config


def test_config_requires_token() -> None:
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config({})


def test_config_uses_safe_defaults() -> None:
    config = load_config({"TELEGRAM_BOT_TOKEN": "test-token"})

    assert config.token == "test-token"
    assert config.max_concurrent_jobs == 2
    assert config.max_file_size_mb is None
    assert config.max_file_size_bytes is None
    assert config.max_copies == 20
    assert config.max_batch_workers == 2


def test_config_loads_concurrency_and_file_limit() -> None:
    config = load_config(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "MAX_CONCURRENT_JOBS": "3",
            "MAX_FILE_SIZE_MB": "1.5",
            "MAX_COPIES": "50",
            "MAX_BATCH_WORKERS": "3",
        }
    )

    assert config.max_concurrent_jobs == 3
    assert config.max_file_size_bytes == 1_572_864
    assert config.max_copies == 50
    assert config.max_batch_workers == 3


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("MAX_CONCURRENT_JOBS", "0", "positive integer"),
        ("MAX_CONCURRENT_JOBS", "two", "positive integer"),
        ("MAX_FILE_SIZE_MB", "0", "positive number"),
        ("MAX_FILE_SIZE_MB", "large", "positive number"),
        ("MAX_COPIES", "0", "positive integer"),
        ("MAX_BATCH_WORKERS", "workers", "positive integer"),
    ),
)
def test_config_rejects_invalid_limits(name: str, value: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config({"TELEGRAM_BOT_TOKEN": "token", name: value})
