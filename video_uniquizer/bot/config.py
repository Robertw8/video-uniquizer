"""Environment-based configuration for the Telegram application."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when Telegram application configuration is invalid."""


@dataclass(frozen=True, slots=True)
class BotConfig:
    """Validated runtime settings for long polling and media processing."""

    token: str
    max_concurrent_jobs: int = 2
    max_file_size_mb: float | None = None
    max_copies: int = 20
    max_batch_workers: int = 2

    @property
    def max_file_size_bytes(self) -> int | None:
        """Return the optional application limit converted to bytes."""
        if self.max_file_size_mb is None:
            return None
        return int(self.max_file_size_mb * 1024 * 1024)


def load_config(
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = None,
) -> BotConfig:
    """Load and validate bot settings without ever providing a token default."""
    if environ is None:
        load_dotenv(dotenv_path=dotenv_path)
        values: Mapping[str, str] = os.environ
    else:
        values = environ

    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "TELEGRAM_BOT_TOKEN is not configured. "
            "Create .env from .env.example and add the bot token."
        )

    concurrent_raw = values.get("MAX_CONCURRENT_JOBS", "2").strip() or "2"
    try:
        max_concurrent_jobs = int(concurrent_raw)
    except ValueError as exc:
        raise ConfigError("MAX_CONCURRENT_JOBS must be a positive integer.") from exc
    if max_concurrent_jobs < 1:
        raise ConfigError("MAX_CONCURRENT_JOBS must be a positive integer.")

    file_size_raw = values.get("MAX_FILE_SIZE_MB", "").strip()
    max_file_size_mb: float | None = None
    if file_size_raw:
        try:
            max_file_size_mb = float(file_size_raw)
        except ValueError as exc:
            raise ConfigError("MAX_FILE_SIZE_MB must be a positive number.") from exc
        if max_file_size_mb <= 0:
            raise ConfigError("MAX_FILE_SIZE_MB must be a positive number.")

    max_copies = _positive_integer(values, "MAX_COPIES", 20)
    max_batch_workers = _positive_integer(values, "MAX_BATCH_WORKERS", 2)

    return BotConfig(
        token=token,
        max_concurrent_jobs=max_concurrent_jobs,
        max_file_size_mb=max_file_size_mb,
        max_copies=max_copies,
        max_batch_workers=max_batch_workers,
    )


def _positive_integer(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = values.get(name, str(default)).strip() or str(default)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise ConfigError(f"{name} must be a positive integer.")
    return value
