"""Safe subprocess wrappers for FFmpeg and ffprobe."""

import json
import logging
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MediaToolError(RuntimeError):
    """Base error raised by an external media tool."""


class MediaToolNotFoundError(MediaToolError):
    """Raised when a required executable is not installed or not in PATH."""


class MediaToolExecutionError(MediaToolError):
    """Raised when a media tool exits unsuccessfully."""


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
        executable = command[0]
        raise MediaToolNotFoundError(
            f"Executable '{executable}' was not found. Install it and ensure "
            "it is available in PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "No error output").strip()
        raise MediaToolExecutionError(
            f"Command '{shlex.join(command)}' failed with exit code {exc.returncode}: {details}"
        ) from exc


def run_ffmpeg(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg with the supplied arguments.

    ``command`` may contain only arguments or an explicit ``ffmpeg`` executable
    as its first item. Shell execution is deliberately disabled.
    """
    if not command:
        raise ValueError("FFmpeg command must not be empty.")
    full_command = list(command)
    if Path(full_command[0]).name != "ffmpeg":
        full_command.insert(0, "ffmpeg")
    return _run(full_command)


def probe_file(path: str | Path) -> dict[str, Any]:
    """Return parsed ffprobe JSON for a media file."""
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(f"Media file does not exist: {media_path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(media_path),
    ]
    result = _run(command)
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolExecutionError(
            f"ffprobe returned invalid JSON for '{media_path}': {exc}"
        ) from exc
    return payload
