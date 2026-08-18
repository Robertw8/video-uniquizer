"""Subprocess wrapper for reading and updating media metadata with ExifTool."""

import json
import logging
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExifToolError(RuntimeError):
    """Base error raised by ExifTool operations."""


class ExifToolNotFoundError(ExifToolError):
    """Raised when ExifTool is unavailable."""


class ExifToolExecutionError(ExifToolError):
    """Raised when ExifTool reports a failure."""


MetadataValue = str | int | float | bool
METADATA_TAG_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    logger.info("Executing command: %s", shlex.join(command))
    try:
        return subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ExifToolNotFoundError(
            "Executable 'exiftool' was not found. Install ExifTool and ensure "
            "it is available in PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "No error output").strip()
        raise ExifToolExecutionError(
            f"Command '{shlex.join(command)}' failed with exit code {exc.returncode}: {details}"
        ) from exc


def _existing_file(path: str | Path) -> Path:
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(f"Media file does not exist: {media_path}")
    return media_path


def read_metadata(path: str | Path) -> dict[str, Any]:
    """Read metadata and return the first ExifTool JSON object."""
    media_path = _existing_file(path)
    result = _run(("exiftool", "-json", "-G", "-n", str(media_path)))
    try:
        payload: list[dict[str, Any]] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExifToolExecutionError(
            f"ExifTool returned invalid JSON for '{media_path}': {exc}"
        ) from exc
    if not payload:
        return {}
    return payload[0]


def clear_metadata(path: str | Path) -> subprocess.CompletedProcess[str]:
    """Remove writable metadata without leaving ExifTool backup files."""
    media_path = _existing_file(path)
    return _run(("exiftool", "-overwrite_original", "-all=", str(media_path)))


def write_metadata(
    path: str | Path,
    metadata: Mapping[str, MetadataValue],
) -> subprocess.CompletedProcess[str]:
    """Write metadata tags without invoking a shell."""
    media_path = _existing_file(path)
    if not metadata:
        raise ValueError("Metadata must contain at least one tag.")
    invalid_tags = [key for key in metadata if not METADATA_TAG_PATTERN.fullmatch(key)]
    if invalid_tags:
        raise ValueError(f"Invalid metadata tag name: {invalid_tags[0]!r}")

    assignments = [f"-{key}={value}" for key, value in metadata.items()]
    return _run(("exiftool", "-overwrite_original", *assignments, str(media_path)))
